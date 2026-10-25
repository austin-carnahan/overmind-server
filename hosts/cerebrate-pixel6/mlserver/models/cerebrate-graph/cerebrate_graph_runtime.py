"""Generic MLServer custom runtime for cerebrate-graph (Segmentation and
Labeling Lane, Step 1).

A pure tensor passthrough: each V2 request input becomes one named tensor
for the worker, and each worker output becomes one V2 response output, with
the same names, shapes, and dtypes. Model-specific preprocessing (image
decode, resize, normalization) and postprocessing (boxes, masks, labels)
deliberately live outside this adapter, so one adapter serves every ONNX
model the worker can load.

Which model, slot, and execution provider come from model-settings.json's
parameters.extra:
  cerebrate_graph_worker      supervisor slot: graph1 | graph2 | graph3
  cerebrate_graph_port        that slot's fixed port (8769 | 8770 | 8771)
  cerebrate_graph_model_path  flat file in /data/local/tmp on the Android host
  cerebrate_graph_backend     cpu | nnapi | nnapi16 | xnnpack | webgpu
  cerebrate_graph_host        optional; default is the AVF gateway
  cerebrate_graph_request_timeout_s  optional; default 120
  cerebrate_graph_residency   optional; pinned (default) | on_demand
  cerebrate_graph_idle_stop_s optional, on_demand only; default 600
  cerebrate_graph_photo       optional; yoloe | sam: accept the encoded photo
                              ("photo", BYTES) and preprocess it here into
                              the worker's uint8 input (see
                              cerebrate_graph_photo.py); needs OpenCV

Residency (catalog v4 Section 9). pinned: START at load, STOP at unload --
the worker runs for as long as the MLServer model is loaded. on_demand:
load only validates the settings (the model reports ready without a
worker); the first request STARTs the worker (paying its load and any
accelerator compile), and it is STOPped again after idle_stop_s without
requests. Starts and idle stops take the same refcount as pinned loads, so
a rolling reload still never STOPs a worker another instance is using.
An on_demand model stays ready (= able to start its worker on request):
MLServer refuses requests to a model that isn't ready before predict()
runs, so marking it unready after a failure would block the very request
that restarts it. A failed start or a lost worker is a failed request
(and a log line); the slot is released and the next request starts afresh.

The slot may also be cerebrate-hetero's (hetero1, port 8772); its
"backend" is then one of the supervisor's fixed profile names (e.g.
yoloe-v8s-fast) and model_path that profile's declared model. The worker
speaks the same protocol and DESCRIBEs the same two fields.

Lifecycle, refcounting, gateway discovery, and readiness handling follow
cerebrate_infer_runtime.py (duplicated, not shared, per that module's own
precedent); see its comments for the reasoning behind each.
"""
import asyncio
import fcntl
import os
import socket
import subprocess
import sys
import time

from mlserver import MLModel
from mlserver.codecs import NumpyCodec
from mlserver.errors import MLServerError
from mlserver.types import InferenceRequest, InferenceResponse, Parameters

import cerebrate_graph_protocol as protocol

DEFAULT_HOST = "10.70.217.78"
CONNECT_TIMEOUT_S = 5.0
DEFAULT_REQUEST_TIMEOUT_S = 120.0
DEFAULT_IDLE_STOP_S = 600.0

SUPERVISOR_PORT = 8767
SUPERVISOR_CONNECT_TIMEOUT_S = 5.0
# Covers cerebrate-supervisor's up-to-120s readiness wait for graph slots
# (large models and NNAPI compilation load slowly).
SUPERVISOR_COMMAND_TIMEOUT_S = 150.0

# One refcount file per slot: two MLServer models must never share a slot,
# but each slot needs the rolling-reload protection cerebrate-infer's does.
REFCOUNT_PATH_TEMPLATE = "/tmp/cerebrate-graph-{worker}.refcount"


def _adjust_refcount(path: str, delta: int) -> int:
    my_pid = os.getpid()
    with open(path, "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        owner_pid, _, count_str = f.read().strip().partition(":")
        count = int(count_str) if owner_pid == str(my_pid) and count_str else 0
        count = max(0, count + delta)
        f.seek(0)
        f.truncate()
        f.write(f"{my_pid}:{count}")
        fcntl.flock(f, fcntl.LOCK_UN)
    return count


def _discover_avf_gateway() -> str:
    try:
        out = subprocess.check_output(
            ["ip", "route", "show", "default"], text=True, timeout=2
        )
        for line in out.splitlines():
            parts = line.split()
            if "via" in parts:
                return parts[parts.index("via") + 1]
    except (subprocess.SubprocessError, OSError, ValueError):
        pass
    return DEFAULT_HOST


def _supervisor_request(host: str, command: str, fields: dict) -> str:
    lines = [command] + [f"{k}: {v}" for k, v in fields.items()]
    message = ("\n".join(lines) + "\n\n").encode("utf-8")
    with socket.create_connection((host, SUPERVISOR_PORT), timeout=SUPERVISOR_CONNECT_TIMEOUT_S) as sock:
        sock.settimeout(SUPERVISOR_COMMAND_TIMEOUT_S)
        sock.sendall(message)
        sock.shutdown(socket.SHUT_WR)
        chunks = []
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
    return b"".join(chunks).decode("utf-8", "replace")


class CerebrateGraphRuntime(MLModel):
    async def load(self) -> bool:
        extra = {}
        if self.settings.parameters is not None:
            extra = self.settings.parameters.extra or {}
        self._worker = extra.get("cerebrate_graph_worker")
        self._model_path = extra.get("cerebrate_graph_model_path")
        self._backend = extra.get("cerebrate_graph_backend", "cpu")
        if not self._worker or not self._model_path or "cerebrate_graph_port" not in extra:
            print(
                f"cerebrate-graph ({self.name}): model-settings.json extra needs "
                "cerebrate_graph_worker, cerebrate_graph_port and cerebrate_graph_model_path"
            )
            self.ready = False
            return self.ready
        self._host = extra.get("cerebrate_graph_host") or _discover_avf_gateway()
        self._port = int(extra["cerebrate_graph_port"])
        self._request_timeout = float(
            extra.get("cerebrate_graph_request_timeout_s", DEFAULT_REQUEST_TIMEOUT_S)
        )
        self._residency = extra.get("cerebrate_graph_residency", "pinned")
        if self._residency not in ("pinned", "on_demand"):
            print(f"cerebrate-graph ({self.name}): unknown cerebrate_graph_residency {self._residency!r}")
            self.ready = False
            return self.ready
        self._idle_stop_s = float(extra.get("cerebrate_graph_idle_stop_s", DEFAULT_IDLE_STOP_S))
        self._hooks = None
        photo = extra.get("cerebrate_graph_photo")
        if photo:
            # Imported only for models that take photos (it needs OpenCV); it
            # lives beside this module's real file (model folders symlink it).
            here = os.path.dirname(os.path.realpath(__file__))
            if here not in sys.path:
                sys.path.insert(0, here)
            try:
                import cerebrate_graph_photo
                self._hooks = cerebrate_graph_photo.HOOKS[photo]()
            except (ImportError, KeyError) as exc:
                print(f"cerebrate-graph ({self.name}): cerebrate_graph_photo {photo!r} unavailable: {exc}")
                self.ready = False
                return self.ready
        self._refcount_path = REFCOUNT_PATH_TEMPLATE.format(worker=self._worker)
        self._lock = asyncio.Lock()
        self._start_lock = asyncio.Lock()
        self._reader = None
        self._writer = None
        self._counted = False
        self._last_used = time.monotonic()
        self._idle_task = None

        if self._residency == "on_demand":
            self._idle_task = asyncio.create_task(self._idle_stopper())
            print(
                f"cerebrate-graph ({self.name}): on demand on {self._worker} "
                f"(backend={self._backend}, idle stop after {self._idle_stop_s:.0f}s)"
            )
            self.ready = True
            return self.ready
        self.ready = await self._start_worker()
        return self.ready

    async def _start_worker(self) -> bool:
        """START the slot and confirm by DESCRIBE that it serves this model
        with this backend. True when ready."""
        fields = {"worker": self._worker, "model": self._model_path, "backend": self._backend}
        try:
            response = await asyncio.to_thread(_supervisor_request, self._host, "START", fields)
        except OSError as exc:
            print(f"cerebrate-graph ({self.name}): cerebrate-supervisor unreachable: {exc}")
            return False
        if not response.startswith("OK"):
            print(f"cerebrate-graph ({self.name}): supervisor refused START: {response.strip()}")
            return False
        await asyncio.to_thread(_adjust_refcount, self._refcount_path, 1)
        self._counted = True

        # Confirm the process on this port is serving *this* model with
        # *this* backend, not something left over on the slot.
        try:
            description, _ = await self._call({})
        except (ConnectionError, protocol.WorkerError, ValueError) as exc:
            print(f"cerebrate-graph ({self.name}): DESCRIBE failed: {exc}")
            return False
        if description.get("model") != self._model_path or description.get("backend") != self._backend:
            print(
                f"cerebrate-graph ({self.name}): worker on port {self._port} serves "
                f"{description.get('model')} ({description.get('backend')}), expected "
                f"{self._model_path} ({self._backend})"
            )
            return False
        print(
            f"cerebrate-graph ({self.name}): ready on {self._worker} "
            f"(backend={self._backend}, load_us={description.get('load_us')})"
        )
        return True

    async def _stop_worker(self) -> bool:
        """Drop this instance's hold on the slot; STOP it if no other
        instance holds it."""
        await self._drop_connection()
        if not getattr(self, "_counted", False):
            return True
        remaining = await asyncio.to_thread(_adjust_refcount, self._refcount_path, -1)
        self._counted = False
        if remaining > 0:
            return True
        try:
            response = await asyncio.to_thread(
                _supervisor_request, self._host, "STOP", {"worker": self._worker}
            )
        except OSError as exc:
            print(f"cerebrate-graph ({self.name}): failed to STOP {self._worker}: {exc}")
            return False
        if not response.startswith("OK"):
            print(f"cerebrate-graph ({self.name}): supervisor STOP did not confirm: {response.strip()}")
            return False
        return True

    async def _idle_stopper(self) -> None:
        """on_demand: STOP the worker once no request has arrived for
        idle_stop_s. Rechecks under both locks, so a request that arrived
        meanwhile keeps it (or restarts it right after)."""
        while True:
            await asyncio.sleep(min(30.0, self._idle_stop_s / 2))
            if not self._counted or time.monotonic() - self._last_used < self._idle_stop_s:
                continue
            async with self._start_lock:
                async with self._lock:
                    if not self._counted or time.monotonic() - self._last_used < self._idle_stop_s:
                        continue
                    if await self._stop_worker():
                        print(f"cerebrate-graph ({self.name}): stopped {self._worker} after "
                              f"{self._idle_stop_s:.0f}s idle")

    async def _ensure_started(self) -> None:
        self._last_used = time.monotonic()
        if self._residency != "on_demand":
            return
        async with self._start_lock:
            if self._counted:
                return
            if not await self._start_worker():
                await self._stop_worker()
                self.ready = True
                raise MLServerError(f"cerebrate-graph ({self.name}): could not start {self._worker} on demand")

    async def unload(self) -> bool:
        if getattr(self, "_idle_task", None) is not None:
            self._idle_task.cancel()
            self._idle_task = None
        stopped = await self._stop_worker()
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
            self.ready = False
            raise ConnectionError(
                f"cerebrate-graph at {self._host}:{self._port} unreachable"
            ) from last_error

    async def predict(self, payload: InferenceRequest) -> InferenceResponse:
        if not payload.inputs:
            raise MLServerError("no inputs provided")
        inputs, ctx = None, None
        if self._hooks is not None:
            try:
                prepared = self._hooks.prepare({request_input.name: request_input for request_input in payload.inputs})
            except ValueError as exc:
                raise MLServerError(f"{self.name}: {exc}") from exc
            if prepared is not None:
                inputs, ctx = prepared
        if inputs is None:
            inputs = {request_input.name: NumpyCodec.decode_input(request_input) for request_input in payload.inputs}
        await self._ensure_started()
        try:
            outputs, done = await self._call(inputs)
        except protocol.WorkerError as exc:
            raise MLServerError(f"cerebrate-graph rejected the request: {exc}") from exc
        except ConnectionError:
            # on_demand: release the slot so the next request starts it afresh.
            if self._residency == "on_demand":
                async with self._start_lock:
                    await self._stop_worker()
                self.ready = True
            raise
        except TypeError as exc:
            raise MLServerError(str(exc)) from exc
        if ctx is not None:
            outputs = self._hooks.finish(outputs, ctx)
        return InferenceResponse(
            model_name=self.name,
            model_version=self.version,
            outputs=[NumpyCodec.encode_output(name, array) for name, array in outputs.items()],
            parameters=Parameters(**done),
        )
