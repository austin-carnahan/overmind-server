"""Thin MLServer custom runtime: translates a V2 text-generation request
into cerebrate-generate's length-prefixed TCP protocol and back.

Deliberately a separate, standalone adapter -- not a shared base class
with cerebrate_infer_runtime.py, and not a request-type branch inside
that adapter. Session Execution (this) and Graph Execution
(cerebrate-infer) are composed together only at the MLServer layer, per
the Multi-Runtime Execution Plane design notes; the two Android-host
processes never share code or a config file, and neither should their
adapters.

No streaming yet -- cerebrate-generate itself only supports synchronous
generate_content today, so this adapter returns the full response in
one shot. Streaming (MLServer's generate_stream, backed by
cerebrate-generate's generate_content_stream) is deferred until the
whole pipeline actually needs it.
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
MAX_RESPONSE_BYTES = 1024 * 1024


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

    async def _generate(self, prompt: str) -> str:
        data = prompt.encode("utf-8")
        async with self._lock:
            last_error: Exception = RuntimeError("unreachable")
            for attempt in range(2):
                try:
                    await self._ensure_connected()
                    self._writer.write(struct.pack(">I", len(data)) + data)
                    await self._writer.drain()

                    header = await asyncio.wait_for(
                        self._reader.readexactly(4), timeout=REQUEST_TIMEOUT_S
                    )
                    (response_len,) = struct.unpack(">I", header)
                    if response_len > MAX_RESPONSE_BYTES:
                        raise ValueError(
                            "cerebrate-generate reported an implausible "
                            f"response size: {response_len}"
                        )
                    body = await asyncio.wait_for(
                        self._reader.readexactly(response_len),
                        timeout=REQUEST_TIMEOUT_S,
                    )
                    return body.decode("utf-8", "replace")
                except (
                    ConnectionError,
                    OSError,
                    asyncio.TimeoutError,
                    asyncio.IncompleteReadError,
                ) as exc:
                    last_error = exc
                    await self._drop_connection()
            raise ConnectionError(
                f"cerebrate-generate at {self._host}:{self._port} unreachable"
            ) from last_error

    async def predict(self, payload: InferenceRequest) -> InferenceResponse:
        prompt = _decode_prompt(payload)
        t0 = time.perf_counter()
        text = await self._generate(prompt)
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
