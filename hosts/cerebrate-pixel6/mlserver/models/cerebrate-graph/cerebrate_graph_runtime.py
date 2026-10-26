"""Generic MLServer custom runtime for cerebrate-graph and cerebrate-hetero
workers (Segmentation and Labeling Lane).

A tensor passthrough by default: each V2 request input becomes one named
tensor for the worker, and each worker output becomes one V2 response output,
with the same names, shapes, and dtypes. Models that take photos add a hook
(cerebrate_graph_photo.py, model_hooks.py) for pre- and postprocessing.

Which model, slot, and backend come from model-settings.json's
parameters.extra:
  cerebrate_graph_worker      supervisor slot (graph1-3, hetero1-2, gpu-*)
  cerebrate_graph_port        that slot's fixed port
  cerebrate_graph_model_path  flat file in /data/local/tmp on the Android host
  cerebrate_graph_backend     cerebrate-graph: cpu | nnapi | ...; cerebrate-hetero:
                              the supervisor profile name (e.g. yoloe-v8s-fast)
  cerebrate_graph_host        optional; default is the AVF gateway
  cerebrate_graph_request_timeout_s  optional; default 120
  cerebrate_graph_photo       optional; a hook name from cerebrate_graph_photo.HOOKS
                              (yoloe | sam | depth | migan | dinov2 | sam2 |
                              rfdetr | esam3 | owlv2): accept the encoded photo
                              ("photo", BYTES), preprocess it here and return
                              final results as JSON; needs OpenCV
  cerebrate_graph_supervisor_port  optional; default from cerebrate_lifecycle
                              (8767, or CEREBRATE_SUPERVISOR_PORT for a test stack)

A hook either maps one request to one worker call (prepare/finish) or, for
pipelines with a host step between graphs, drives several calls itself (an
async run(inputs, params, call) method).

Starting, stopping, idle stops, making room and the lost-worker retry are the
shared lifecycle's (cerebrate_lifecycle.py), the same for every Pixel model;
this module keeps the request handling and checks, by DESCRIBE after each
start, that the worker serves this model with this backend.
"""
import asyncio
import os
import sys

from mlserver import MLModel
from mlserver.codecs import NumpyCodec
from mlserver.errors import MLServerError
from mlserver.types import InferenceRequest, InferenceResponse, Parameters, ResponseOutput

# The shared modules live beside this module's real file (model folders
# symlink this one).
_HERE = os.path.dirname(os.path.realpath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import cerebrate_graph_protocol as protocol  # noqa: E402
import cerebrate_lifecycle as lifecycle  # noqa: E402

CONNECT_TIMEOUT_S = 5.0
DEFAULT_REQUEST_TIMEOUT_S = 120.0


class CerebrateGraphRuntime(MLModel):
    async def load(self) -> bool:
        extra = {}
        if self.settings.parameters is not None:
            extra = self.settings.parameters.extra or {}
        self._worker_slot = extra.get("cerebrate_graph_worker")
        self._model_path = extra.get("cerebrate_graph_model_path")
        self._backend = extra.get("cerebrate_graph_backend", "cpu")
        if not self._worker_slot or not self._model_path or "cerebrate_graph_port" not in extra:
            print(
                f"cerebrate-graph ({self.name}): model-settings.json extra needs "
                "cerebrate_graph_worker, cerebrate_graph_port and cerebrate_graph_model_path"
            )
            self.ready = False
            return self.ready
        self._host = extra.get("cerebrate_graph_host") or lifecycle.discover_gateway()
        self._port = int(extra["cerebrate_graph_port"])
        self._request_timeout = float(
            extra.get("cerebrate_graph_request_timeout_s", DEFAULT_REQUEST_TIMEOUT_S)
        )
        self._hooks = None
        photo = extra.get("cerebrate_graph_photo")
        if photo:
            # Imported only for models that take photos (it needs OpenCV).
            try:
                import cerebrate_graph_photo
                self._hooks = cerebrate_graph_photo.HOOKS[photo]()
            except (ImportError, KeyError) as exc:
                print(f"cerebrate-graph ({self.name}): cerebrate_graph_photo {photo!r} unavailable: {exc}")
                self.ready = False
                return self.ready
        self._lock = asyncio.Lock()
        self._reader = None
        self._writer = None
        supervisor_port = extra.get("cerebrate_graph_supervisor_port")
        self._worker = lifecycle.Worker(
            self.name,
            {"worker": self._worker_slot, "model": self._model_path, "backend": self._backend},
            host=self._host, supervisor_port=int(supervisor_port) if supervisor_port else None,
            verify=self._verify, drop=self._drop_connection,
        )
        self._worker.activate()
        self.ready = True
        return self.ready

    async def _verify(self) -> None:
        """After START: the process on this port serves *this* model with
        *this* backend, not something left over on the slot."""
        description, _ = await self._call({})
        if description.get("model") != self._model_path or description.get("backend") != self._backend:
            raise ValueError(
                f"worker on port {self._port} serves {description.get('model')} "
                f"({description.get('backend')}), expected {self._model_path} ({self._backend})"
            )
        print(f"cerebrate-graph ({self.name}): ready on {self._worker_slot} "
              f"(backend={self._backend}, load_us={description.get('load_us')})")

    async def unload(self) -> bool:
        stopped = await self._worker.deactivate() if getattr(self, "_worker", None) else True
        if stopped:
            self.ready = False
        return stopped

    async def _drop_connection(self) -> None:
        if getattr(self, "_writer", None) is not None:
            self._writer.close()
        self._reader = None
        self._writer = None

    async def _call(self, inputs: dict):
        """One request/response with one reconnect-and-retry on a connection
        failure. Inference is stateless, so a retry can't double-apply
        anything. An ERROR frame is the worker's answer, not a transport
        failure, and is never retried. Returns (outputs, done_fields), or for
        an empty DESCRIBE request (description, done_fields)."""
        async with self._lock:
            last_error: Exception = RuntimeError("unreachable")
            for _ in range(2):
                try:
                    if self._writer is None or self._writer.is_closing():
                        self._reader, self._writer = await asyncio.wait_for(
                            asyncio.open_connection(self._host, self._port),
                            timeout=CONNECT_TIMEOUT_S,
                        )
                    return await protocol.call_async(
                        self._reader, self._writer, inputs, self._request_timeout
                    )
                except (ConnectionError, OSError, asyncio.TimeoutError, asyncio.IncompleteReadError) as exc:
                    last_error = exc
                    await self._drop_connection()
            raise ConnectionError(
                f"cerebrate-graph at {self._host}:{self._port} unreachable"
            ) from last_error

    async def _call_worker(self, inputs: dict):
        """One worker call through the shared lifecycle (started on demand,
        room made if needed, one retry on a lost worker)."""
        try:
            return await self._worker.run(lambda: self._call(inputs))
        except lifecycle.WorkerUnavailable as exc:
            raise MLServerError(f"cerebrate-graph ({self.name}): could not start {self._worker_slot}: {exc}") from exc
        except protocol.WorkerError as exc:
            raise MLServerError(f"cerebrate-graph rejected the request: {exc}") from exc
        except TypeError as exc:
            raise MLServerError(str(exc)) from exc

    async def predict(self, payload: InferenceRequest) -> InferenceResponse:
        if not payload.inputs:
            raise MLServerError("no inputs provided")
        if self._hooks is not None and hasattr(self._hooks, "run"):
            # A multi-call hook (host step between graphs) drives the worker
            # itself; held for the whole request, so it isn't stopped between
            # calls (a cached image must survive until the last one).
            try:
                async with self._worker.use():
                    outputs, done = await self._hooks.run({i.name: i for i in payload.inputs}, payload.parameters, self._call_worker)
            except lifecycle.WorkerUnavailable as exc:
                raise MLServerError(f"cerebrate-graph ({self.name}): could not start {self._worker_slot}: {exc}") from exc
            except ValueError as exc:
                raise MLServerError(f"{self.name}: {exc}") from exc
            return InferenceResponse(
                model_name=self.name, model_version=self.version,
                outputs=[ResponseOutput(name=name, datatype="BYTES", shape=[1], data=[value]) if isinstance(value, bytes)
                         else NumpyCodec.encode_output(name, value) for name, value in outputs.items()],
                parameters=Parameters(**done),
            )
        inputs, ctx = None, None
        if self._hooks is not None:
            try:
                prepared = self._hooks.prepare({request_input.name: request_input for request_input in payload.inputs}, payload.parameters)
            except ValueError as exc:
                raise MLServerError(f"{self.name}: {exc}") from exc
            if prepared is not None:
                inputs, ctx = prepared
        if inputs is None:
            inputs = {request_input.name: NumpyCodec.decode_input(request_input) for request_input in payload.inputs}
        outputs, done = await self._call_worker(inputs)
        if ctx is not None:
            outputs = self._hooks.finish(outputs, ctx)
        return InferenceResponse(
            model_name=self.name,
            model_version=self.version,
            # bytes (a hook's JSON result) go out as BYTES, untouched by MLServer's list encoding
            outputs=[ResponseOutput(name=name, datatype="BYTES", shape=[1], data=[value]) if isinstance(value, bytes)
                     else NumpyCodec.encode_output(name, value) for name, value in outputs.items()],
            parameters=Parameters(**done),
        )
