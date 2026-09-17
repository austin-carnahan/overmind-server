"""Thin MLServer custom runtime: translates a V2 inference request into
cerebrate-infer's line-based TCP protocol and back.

This is deliberately a protocol/data-shape adapter, not a reimplementation
of TensorFlow Lite, NNAPI, or accelerator selection -- all of that stays
inside cerebrate-infer on the Android host. Image decode/resize (Pillow)
and label-index lookup live here instead, since they're generic,
reusable concerns unrelated to the accelerator boundary.

Phase 3 scope: accept a real image (any format Pillow can decode),
resize/convert it to the exact tensor cerebrate-infer's current model
(MobileNet v1 1.0 224 quantized) expects, and return a human-readable
label + confidence alongside the raw diagnostic fields. This is tied to
that one model/input shape for now -- not a general multi-model runtime.
"""
import asyncio
import fcntl
import io
import os
import socket
import subprocess

from PIL import Image

from mlserver import MLModel
from mlserver.codecs.base64 import Base64Codec
from mlserver.types import InferenceRequest, InferenceResponse, ResponseOutput

DEFAULT_HOST = "10.70.217.78"
DEFAULT_PORT = 8765
CONNECT_TIMEOUT_S = 5.0
REQUEST_TIMEOUT_S = 10.0

# cerebrate-supervisor (Phase B Stage 1) -- the execution channel that
# actually starts/stops the worker process. Duplicated rather than shared
# with cerebrate_generate_runtime.py's identical client, matching this
# module's existing precedent for _discover_avf_gateway().
SUPERVISOR_PORT = 8767
SUPERVISOR_CONNECT_TIMEOUT_S = 5.0
# Covers cerebrate-supervisor's own up-to-15s worker-readiness wait inside
# its START handler.
SUPERVISOR_COMMAND_TIMEOUT_S = 20.0

# File-backed, not in-process: MLServer reloads this module (importlib.reload)
# on every load()/unload() call for a model-settings.json-backed model -- a
# deliberate hot-reload feature -- so any class/module-level Python state is
# wiped between calls and can't be used as a refcount. Found empirically: a
# class-attribute refcount here still let a second load() call kill the
# worker, because MLServer's own "rolling reload" (new.load() then
# old.unload(), see mlserver/registry.py's _reload_model) ran against two
# instances that, after the reload, no longer shared any live Python state
# at all.
#
# Tagged with the owning process's PID, not a bare count: /tmp survives an
# `systemctl restart cerebrate-mlserver`, but MLServer doesn't call unload()
# on a killed process's models on the way out -- a bare counter would climb
# by one on every restart and never come back down, eventually making
# unload() never actually STOP anything again. A PID mismatch means the
# file is stale from a previous MLServer process, so it's reset to zero
# before applying this call's delta.
REFCOUNT_PATH = "/tmp/cerebrate-infer.refcount"


def _adjust_refcount(delta: int) -> int:
    my_pid = os.getpid()
    with open(REFCOUNT_PATH, "a+") as f:
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

# MobileNet v1 1.0 224 quantized: fixed for this phase, not model-agnostic.
INPUT_WIDTH = 224
INPUT_HEIGHT = 224
INPUT_CHANNELS = 3
INPUT_SIZE = INPUT_WIDTH * INPUT_HEIGHT * INPUT_CHANNELS

LABELS_PATH = os.path.join(os.path.dirname(__file__), "imagenet_labels.txt")

REQUIRED_FIELDS = ("request_id", "top_class", "top_score", "inference_us", "handle_us")


def _parse_response_line(line: str) -> dict:
    fields = {}
    for token in line.strip().split():
        key, _, value = token.partition("=")
        fields[key] = int(value)
    missing = [f for f in REQUIRED_FIELDS if f not in fields]
    if missing:
        raise ValueError(f"cerebrate-infer response missing {missing}: {line!r}")
    return fields


def _load_labels() -> list:
    with open(LABELS_PATH, "r", encoding="utf-8") as f:
        return [line.rstrip("\n") for line in f]


def _discover_avf_gateway() -> str:
    """The AVF gateway address is dynamically assigned per VM boot and not
    guaranteed stable (observed firsthand: it changed across restarts
    during this project). Read it from the guest's own default route at
    load() time instead of hardcoding it, so a VM restart doesn't require
    a manual config update to keep cerebrate-infer reachable."""
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
    """Blocking by design (plain socket, not asyncio) -- matches this
    module's existing _discover_avf_gateway() precedent of a small
    synchronous call inside load()/unload(), just longer-lived. Callers
    wrap it in asyncio.to_thread so a slow worker start doesn't stall
    the shared event loop (MLSERVER_PARALLEL_WORKERS=0 means this runs
    in the same process as request handling)."""
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


def _ensure_worker_started(host: str, model_path: str) -> str:
    """START is idempotent on the supervisor side -- a worker already
    running with this exact model succeeds harmlessly. If it's running
    with a *different* model, this raises rather than silently forcing a
    STOP+START, since load() only knows about its own configured model,
    not why something else might already be running."""
    response = _supervisor_request(host, "START", {"worker": "infer", "model": model_path})
    if not response.startswith("OK"):
        raise RuntimeError(f"cerebrate-supervisor refused START: {response.strip()}")
    return response


def _decode_image_bytes(payload: InferenceRequest) -> bytes:
    if not payload.inputs:
        raise ValueError("no inputs provided")
    request_input = payload.inputs[0]
    images = Base64Codec.decode_input(request_input)
    if not images:
        raise ValueError("image input was empty")
    return images[0]


def _preprocess(raw_image_bytes: bytes) -> bytes:
    img = Image.open(io.BytesIO(raw_image_bytes)).convert("RGB")
    img = img.resize((INPUT_WIDTH, INPUT_HEIGHT))
    tensor_bytes = img.tobytes()  # row-major HWC uint8, matches TFLite NHWC layout
    if len(tensor_bytes) != INPUT_SIZE:
        raise ValueError(
            f"preprocessed image is {len(tensor_bytes)} bytes, expected {INPUT_SIZE}"
        )
    return tensor_bytes


class CerebrateInferRuntime(MLModel):
    # See REFCOUNT_PATH above for why this is a file, not a class attribute:
    # MLServer's own repository.load() on an *already-loaded* model does a
    # "rolling reload" (mlserver/registry.py's _reload_model) -- new
    # instance's load() runs, THEN the old instance's unload() runs for
    # cleanup. Both share the same underlying Android process, so without a
    # refcount the old instance's unload() would unconditionally STOP a
    # worker the new instance is still relying on. Found empirically: a
    # second `load()` call against an already-loaded model silently killed
    # it, even with a class-attribute refcount, because the module reload
    # between calls resets class state too.

    async def load(self) -> bool:
        extra = {}
        if self.settings.parameters is not None:
            extra = self.settings.parameters.extra or {}
        self._host = extra.get("cerebrate_infer_host") or _discover_avf_gateway()
        self._port = int(extra.get("cerebrate_infer_port", DEFAULT_PORT))
        self._model_path = extra.get("cerebrate_infer_model_path")
        self._lock = asyncio.Lock()
        self._reader = None
        self._writer = None
        self._labels = _load_labels()
        self._counted = False

        if self._model_path:
            try:
                await asyncio.to_thread(_ensure_worker_started, self._host, self._model_path)
            except (OSError, RuntimeError) as exc:
                print(f"cerebrate-infer: failed to start worker via cerebrate-supervisor: {exc}")
                self.ready = False
                return self.ready
            await asyncio.to_thread(_adjust_refcount, 1)
            self._counted = True
        else:
            # No model path configured: pre-Stage-2 behavior, assume a
            # worker is already running externally. Logged so this
            # fallback is visible rather than silently taken.
            print(
                "cerebrate-infer: cerebrate_infer_model_path not set in "
                "model-settings.json extra -- assuming the worker is "
                "already running (legacy, pre-supervisor mode)"
            )

        self.ready = True
        return self.ready

    async def unload(self) -> bool:
        await self._drop_connection()
        if not getattr(self, "_model_path", None):
            self.ready = False
            return True

        remaining = await asyncio.to_thread(_adjust_refcount, -1) if self._counted else None
        self._counted = False
        if remaining is not None and remaining > 0:
            # Another instance (MLServer's own reload path, most likely)
            # still depends on this worker process -- leave it running.
            self.ready = False
            return True

        try:
            response = await asyncio.to_thread(
                _supervisor_request, self._host, "STOP", {"worker": "infer"}
            )
        except OSError as exc:
            print(f"cerebrate-infer: failed to STOP worker via cerebrate-supervisor: {exc}")
            return False
        if not response.startswith("OK"):
            print(f"cerebrate-infer: supervisor STOP did not confirm: {response.strip()}")
            return False
        self.ready = False
        return True

    async def _ensure_connected(self) -> None:
        if self._writer is not None and not self._writer.is_closing():
            return
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self._host, self._port),
            timeout=CONNECT_TIMEOUT_S,
        )

    async def _drop_connection(self) -> None:
        if self._writer is not None:
            self._writer.close()
        self._reader = None
        self._writer = None

    async def _send_tensor(self, tensor_bytes: bytes) -> dict:
        async with self._lock:
            last_error: Exception = RuntimeError("unreachable")
            for attempt in range(2):
                try:
                    await self._ensure_connected()
                    self._writer.write(tensor_bytes)
                    await self._writer.drain()
                    line = await asyncio.wait_for(
                        self._reader.readline(), timeout=REQUEST_TIMEOUT_S
                    )
                    if not line:
                        raise ConnectionError("cerebrate-infer closed the connection")
                    return _parse_response_line(line.decode("utf-8", "replace"))
                except (ConnectionError, OSError, asyncio.TimeoutError) as exc:
                    last_error = exc
                    await self._drop_connection()
            # Both attempts exhausted, not just one transient blip: reflect
            # this in readiness so /ready and the repository index report
            # reality instead of a stale "READY" from load() time. Found
            # via Phase B Stage 3: a killed worker left MLServer reporting
            # READY indefinitely until the next explicit unload().
            self.ready = False
            raise ConnectionError(
                f"cerebrate-infer at {self._host}:{self._port} unreachable"
            ) from last_error

    def _label_for(self, class_index: int) -> str:
        if 0 <= class_index < len(self._labels):
            return self._labels[class_index]
        return "unknown"

    async def predict(self, payload: InferenceRequest) -> InferenceResponse:
        raw_image_bytes = _decode_image_bytes(payload)
        tensor_bytes = _preprocess(raw_image_bytes)
        result = await self._send_tensor(tensor_bytes)

        label = self._label_for(result["top_class"])
        confidence = result["top_score"] / 255.0

        outputs = [
            ResponseOutput(name="label", shape=[1], datatype="BYTES", data=[label]),
            ResponseOutput(
                name="confidence", shape=[1], datatype="FP32", data=[confidence]
            ),
        ]
        outputs += [
            ResponseOutput(name=name, shape=[1], datatype="INT64", data=[result[name]])
            for name in ("request_id", "top_class", "inference_us", "handle_us")
        ]
        return InferenceResponse(
            model_name=self.name,
            model_version=self.version,
            outputs=outputs,
        )
