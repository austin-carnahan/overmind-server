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


def _decode_prompt(payload: InferenceRequest) -> str:
    if not payload.inputs:
        raise ValueError("no inputs provided")
    prompts = StringCodec.decode_input(payload.inputs[0])
    if not prompts:
        raise ValueError("prompt input was empty")
    return prompts[0]


class CerebrateGenerateRuntime(MLModel):
    async def load(self) -> bool:
        extra = {}
        if self.settings.parameters is not None:
            extra = self.settings.parameters.extra or {}
        self._host = extra.get("cerebrate_generate_host") or _discover_avf_gateway()
        self._port = int(extra.get("cerebrate_generate_port", DEFAULT_PORT))
        self._lock = asyncio.Lock()
        self._reader = None
        self._writer = None
        self.ready = True
        return self.ready

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
