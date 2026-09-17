"""Thin MLServer custom runtime: translates a V2 text-generation request
into cerebrate-generate's typed-frame TCP protocol and back.

Deliberately a separate, standalone adapter -- not a shared base class
with cerebrate_infer_runtime.py, and not a request-type branch inside
that adapter. Session Execution (this) and Graph Execution
(cerebrate-infer) are composed together only at the MLServer layer, per
the Multi-Runtime Execution Plane design notes; the two Android-host
processes never share code or a config file, and neither should their
adapters.

Wire protocol (streaming update): [1-byte type][4-byte BE length]
[payload], types DATA(0)/DONE(1)/ERROR(2) -- replaces the earlier bare
length-prefixed single response, since cerebrate-generate now always
generates via LiteRT-LM's streaming C API internally (one native code
path, not two). `predict()` buffers all DATA chunks into one response,
for plain /infer callers; `predict_stream()` yields one InferenceResponse
per chunk, for /generate_stream callers. Both share the same underlying
frame-reading generator -- that sharing is fine (it's all one adapter
module); what's kept separate is this whole module from cerebrate-infer's.
"""
import asyncio
import fcntl
import os
import socket
import struct
import subprocess
import time

from mlserver import MLModel
from mlserver.codecs.string import StringCodec
from mlserver.types import InferenceRequest, InferenceResponse, ResponseOutput

DEFAULT_HOST = "10.70.217.78"
DEFAULT_PORT = 8766
CONNECT_TIMEOUT_S = 5.0
# Generation can take much longer than a graph-inference call -- give it room.
REQUEST_TIMEOUT_S = 120.0
MAX_FRAME_BYTES = 1024 * 1024

# cerebrate-supervisor (Phase B Stage 1) -- the execution channel that
# actually starts/stops the worker process. Duplicated rather than shared
# with cerebrate_infer_runtime.py's identical client, matching this
# module's existing precedent for _discover_avf_gateway().
SUPERVISOR_PORT = 8767
SUPERVISOR_CONNECT_TIMEOUT_S = 5.0
# Covers cerebrate-supervisor's own up-to-15s worker-readiness wait inside
# its START handler.
SUPERVISOR_COMMAND_TIMEOUT_S = 20.0

# File-backed, not in-process -- see the identical comment/rationale next to
# REFCOUNT_PATH in cerebrate_infer_runtime.py (MLServer reloads this module
# on every load()/unload() call for a model-settings.json-backed model,
# wiping any in-process Python state between calls; and the PID tag exists
# so a `systemctl restart cerebrate-mlserver` resets to zero instead of the
# count climbing by one on every restart forever).
REFCOUNT_PATH = "/tmp/cerebrate-generate.refcount"


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


FRAME_DATA = 0
FRAME_DONE = 1
FRAME_ERROR = 2


def _discover_avf_gateway() -> str:
    """The AVF gateway address is dynamically assigned per VM boot and not
    guaranteed stable. Duplicated from cerebrate_infer_runtime.py's
    identical helper rather than shared, since these two adapters are
    meant to stay fully independent (see module docstring)."""
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
    """Blocking by design -- see the identical helper in
    cerebrate_infer_runtime.py for the full rationale (duplicated
    intentionally, not shared)."""
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


def _ensure_worker_started(host: str, model_path: str, backend: str) -> str:
    """START is idempotent on the supervisor side for a matching
    (model, backend) pair. A worker already running with a *different*
    one raises rather than silently forcing a STOP+START -- switching
    models/backends is an explicit operator action (STOP then START),
    not something load() decides on its own."""
    response = _supervisor_request(
        host, "START", {"worker": "generate", "model": model_path, "backend": backend}
    )
    if not response.startswith("OK"):
        raise RuntimeError(f"cerebrate-supervisor refused START: {response.strip()}")
    return response


def _decode_prompt(payload: InferenceRequest) -> str:
    if not payload.inputs:
        raise ValueError("no inputs provided")
    prompts = StringCodec.decode_input(payload.inputs[0])
    if not prompts:
        raise ValueError("prompt input was empty")
    return prompts[0]


class CerebrateGenerateRuntime(MLModel):
    # See REFCOUNT_PATH above for why this is a file, not a class attribute
    # -- and cerebrate_infer_runtime.py's CerebrateInferRuntime for the full
    # rationale (MLServer's own rolling-reload semantics on an
    # already-loaded model, discovered empirically: a second `load()` call
    # silently killed the worker even with a class-attribute refcount,
    # since the module reload between calls resets class state too).

    async def load(self) -> bool:
        extra = {}
        if self.settings.parameters is not None:
            extra = self.settings.parameters.extra or {}
        self._host = extra.get("cerebrate_generate_host") or _discover_avf_gateway()
        self._port = int(extra.get("cerebrate_generate_port", DEFAULT_PORT))
        self._model_path = extra.get("cerebrate_generate_model_path")
        self._backend = extra.get("cerebrate_generate_backend", "cpu")
        self._lock = asyncio.Lock()
        self._reader = None
        self._writer = None
        self._counted = False

        if self._model_path:
            try:
                await asyncio.to_thread(
                    _ensure_worker_started, self._host, self._model_path, self._backend
                )
            except (OSError, RuntimeError) as exc:
                print(f"cerebrate-generate: failed to start worker via cerebrate-supervisor: {exc}")
                self.ready = False
                return self.ready
            await asyncio.to_thread(_adjust_refcount, 1)
            self._counted = True
        else:
            # No model path configured: pre-Stage-2 behavior, assume a
            # worker is already running externally. Logged so this
            # fallback is visible rather than silently taken.
            print(
                "cerebrate-generate: cerebrate_generate_model_path not set in "
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
                _supervisor_request, self._host, "STOP", {"worker": "generate"}
            )
        except OSError as exc:
            print(f"cerebrate-generate: failed to STOP worker via cerebrate-supervisor: {exc}")
            return False
        if not response.startswith("OK"):
            print(f"cerebrate-generate: supervisor STOP did not confirm: {response.strip()}")
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

    async def _read_frame(self) -> tuple:
        header = await asyncio.wait_for(
            self._reader.readexactly(5), timeout=REQUEST_TIMEOUT_S
        )
        frame_type = header[0]
        (length,) = struct.unpack(">I", header[1:5])
        if length > MAX_FRAME_BYTES:
            raise ValueError(
                f"cerebrate-generate reported an implausible frame size: {length}"
            )
        payload = b""
        if length > 0:
            payload = await asyncio.wait_for(
                self._reader.readexactly(length), timeout=REQUEST_TIMEOUT_S
            )
        return frame_type, payload

    async def _stream_generate(self, prompt: str):
        """Yields decoded text chunks for one prompt. Raises ConnectionError
        on transport failure, RuntimeError on a server-reported generation
        error. Holds the shared connection lock for the whole request --
        cerebrate-generate is single-threaded and serial, so only one
        request can be in flight against it at a time regardless."""
        data = prompt.encode("utf-8")
        async with self._lock:
            last_error: Exception = RuntimeError("unreachable")
            connected = False
            for _attempt in range(2):
                try:
                    await self._ensure_connected()
                    self._writer.write(struct.pack(">I", len(data)) + data)
                    await self._writer.drain()
                    connected = True
                    break
                except (ConnectionError, OSError, asyncio.TimeoutError) as exc:
                    last_error = exc
                    await self._drop_connection()
            if not connected:
                raise ConnectionError(
                    f"cerebrate-generate at {self._host}:{self._port} unreachable"
                ) from last_error

            while True:
                try:
                    frame_type, frame_payload = await self._read_frame()
                except (
                    ConnectionError,
                    OSError,
                    asyncio.TimeoutError,
                    asyncio.IncompleteReadError,
                ) as exc:
                    await self._drop_connection()
                    raise ConnectionError(
                        f"cerebrate-generate at {self._host}:{self._port} "
                        "unreachable mid-stream"
                    ) from exc

                if frame_type == FRAME_DATA:
                    yield frame_payload.decode("utf-8", "replace")
                elif frame_type == FRAME_DONE:
                    return
                elif frame_type == FRAME_ERROR:
                    raise RuntimeError(
                        "cerebrate-generate error: "
                        + frame_payload.decode("utf-8", "replace")
                    )
                else:
                    await self._drop_connection()
                    raise ValueError(f"unknown frame type {frame_type}")

    async def predict(self, payload: InferenceRequest) -> InferenceResponse:
        prompt = _decode_prompt(payload)
        t0 = time.perf_counter()
        chunks = [chunk async for chunk in self._stream_generate(prompt)]
        text = "".join(chunks)
        elapsed_us = int((time.perf_counter() - t0) * 1_000_000)

        outputs = [
            ResponseOutput(name="text", shape=[1], datatype="BYTES", data=[text]),
            ResponseOutput(
                name="elapsed_us", shape=[1], datatype="INT64", data=[elapsed_us]
            ),
        ]
        return InferenceResponse(
            model_name=self.name,
            model_version=self.version,
            outputs=outputs,
        )

    async def predict_stream(self, payloads):
        # REST server-streaming only ever yields one request.
        request = None
        async for p in payloads:
            request = p
            break
        prompt = _decode_prompt(request)

        async for chunk in self._stream_generate(prompt):
            yield InferenceResponse(
                model_name=self.name,
                model_version=self.version,
                outputs=[
                    ResponseOutput(
                        name="text", shape=[1], datatype="BYTES", data=[chunk]
                    )
                ],
            )
