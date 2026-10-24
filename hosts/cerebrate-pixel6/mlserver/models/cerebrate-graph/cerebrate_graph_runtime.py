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

Lifecycle, refcounting, gateway discovery, and readiness handling follow
cerebrate_infer_runtime.py (duplicated, not shared, per that module's own
precedent); see its comments for the reasoning behind each.
"""
import asyncio
import fcntl
import os
import socket
import subprocess

from mlserver import MLModel
from mlserver.codecs import NumpyCodec
from mlserver.errors import MLServerError
from mlserver.types import InferenceRequest, InferenceResponse, Parameters

import cerebrate_graph_protocol as protocol

DEFAULT_HOST = "10.70.217.78"
CONNECT_TIMEOUT_S = 5.0
DEFAULT_REQUEST_TIMEOUT_S = 120.0

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
        self._refcount_path = REFCOUNT_PATH_TEMPLATE.format(worker=self._worker)
        self._lock = asyncio.Lock()
        self._reader = None
        self._writer = None
        self._counted = False

        fields = {"worker": self._worker, "model": self._model_path, "backend": self._backend}
        try:
            response = await asyncio.to_thread(_supervisor_request, self._host, "START", fields)
        except OSError as exc:
            print(f"cerebrate-graph ({self.name}): cerebrate-supervisor unreachable: {exc}")
            self.ready = False
            return self.ready
        if not response.startswith("OK"):
            print(f"cerebrate-graph ({self.name}): supervisor refused START: {response.strip()}")
            self.ready = False
            return self.ready
        await asyncio.to_thread(_adjust_refcount, self._refcount_path, 1)
        self._counted = True

        # Confirm the process on this port is serving *this* model with
        # *this* backend, not something left over on the slot.
        try:
            description, _ = await self._call({})
        except (ConnectionError, protocol.WorkerError, ValueError) as exc:
            print(f"cerebrate-graph ({self.name}): DESCRIBE failed: {exc}")
            self.ready = False
            return self.ready
        if description.get("model") != self._model_path or description.get("backend") != self._backend:
            print(
                f"cerebrate-graph ({self.name}): worker on port {self._port} serves "
                f"{description.get('model')} ({description.get('backend')}), expected "
                f"{self._model_path} ({self._backend})"
            )
            self.ready = False
            return self.ready
        print(
            f"cerebrate-graph ({self.name}): ready on {self._worker} "
            f"(backend={self._backend}, load_us={description.get('load_us')})"
        )
        self.ready = True
        return self.ready

    async def unload(self) -> bool:
        await self._drop_connection()
        if not getattr(self, "_counted", False):
            self.ready = False
            return True
        remaining = await asyncio.to_thread(_adjust_refcount, self._refcount_path, -1)
        self._counted = False
        if remaining > 0:
            self.ready = False
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
        self.ready = False
        return True

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
        inputs = {request_input.name: NumpyCodec.decode_input(request_input) for request_input in payload.inputs}
        try:
            outputs, done = await self._call(inputs)
        except protocol.WorkerError as exc:
            raise MLServerError(f"cerebrate-graph rejected the request: {exc}") from exc
        except TypeError as exc:
            raise MLServerError(str(exc)) from exc
        return InferenceResponse(
            model_name=self.name,
            model_version=self.version,
            outputs=[NumpyCodec.encode_output(name, array) for name, array in outputs.items()],
            parameters=Parameters(**done),
        )
