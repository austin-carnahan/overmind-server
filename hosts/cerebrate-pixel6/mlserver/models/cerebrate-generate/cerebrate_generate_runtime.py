"""Thin MLServer custom runtime: translates a V2 text-generation request
into cerebrate-generate's typed-frame TCP protocol and back.

The request handling is deliberately this adapter's own -- not a shared
base class with cerebrate_infer_runtime.py, and not a request-type branch
inside that adapter: Session Execution (this) and Graph Execution are
composed only at the MLServer layer, per the Multi-Runtime Execution Plane
design notes. The worker *lifecycle* is shared (2026-10-25): starting,
stopping, idle stops, making room and the lost-worker retry are
../cerebrate-graph/cerebrate_lifecycle.py's, the same for every Pixel model;
the worker runs on demand, not pinned.

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
import os
import struct
import sys
import time

from mlserver import MLModel
from mlserver.codecs.string import StringCodec
from mlserver.errors import MLServerError
from mlserver.types import InferenceRequest, InferenceResponse, ResponseOutput

# The shared lifecycle lives with the shared adapter, beside this folder.
_SHARED = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "cerebrate-graph")
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)
import cerebrate_lifecycle as lifecycle  # noqa: E402

DEFAULT_PORT = 8766
CONNECT_TIMEOUT_S = 5.0
# Generation can take much longer than a graph-inference call -- give it room.
REQUEST_TIMEOUT_S = 120.0
MAX_FRAME_BYTES = 1024 * 1024

FRAME_DATA = 0
FRAME_DONE = 1
FRAME_ERROR = 2


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
        self._host = extra.get("cerebrate_generate_host") or lifecycle.discover_gateway()
        self._port = int(extra.get("cerebrate_generate_port", DEFAULT_PORT))
        self._model_path = extra.get("cerebrate_generate_model_path")
        self._backend = extra.get("cerebrate_generate_backend", "cpu")
        if not self._model_path:
            print("cerebrate-generate: model-settings.json extra needs cerebrate_generate_model_path")
            self.ready = False
            return self.ready
        self._lock = asyncio.Lock()
        self._reader = None
        self._writer = None
        self._worker = lifecycle.Worker(
            self.name, {"worker": "generate", "model": self._model_path, "backend": self._backend},
            host=self._host, drop=self._drop_connection,
        )
        self._worker.activate()
        self.ready = True
        return self.ready

    async def unload(self) -> bool:
        stopped = await self._worker.deactivate() if getattr(self, "_worker", None) else True
        if stopped:
            self.ready = False
        return stopped

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
                # Both attempts exhausted: the worker is gone (the shared
                # lifecycle restarts it and, for /infer, retries once).
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

        async def generate_all():
            return "".join([chunk async for chunk in self._stream_generate(prompt)])

        try:
            text = await self._worker.run(generate_all)
        except lifecycle.WorkerUnavailable as exc:
            raise MLServerError(f"cerebrate-generate: could not start the worker: {exc}") from exc
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

        # Streaming holds the worker for the whole stream; no retry once
        # chunks have gone out.
        try:
            async with self._worker.use():
                async for chunk in self._stream_generate(prompt):
                    yield self._chunk_response(chunk)
        except lifecycle.WorkerUnavailable as exc:
            raise MLServerError(f"cerebrate-generate: could not start the worker: {exc}") from exc

    def _chunk_response(self, chunk: str) -> InferenceResponse:
        return InferenceResponse(
            model_name=self.name,
            model_version=self.version,
            outputs=[ResponseOutput(name="text", shape=[1], datatype="BYTES", data=[chunk])],
        )
