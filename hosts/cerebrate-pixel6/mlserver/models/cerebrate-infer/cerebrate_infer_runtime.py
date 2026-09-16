"""Thin MLServer custom runtime: translates a V2 inference request into
cerebrate-infer's line-based TCP protocol and back.

This is deliberately a protocol/data-shape adapter only. It does not
reimplement TensorFlow Lite, NNAPI, or accelerator selection -- all of
that stays inside cerebrate-infer on the Android host. Phase 2 scope:
prove the MLServer -> adapter -> cerebrate-infer -> NNAPI -> EdgeTPU
chain works end to end. Real image input/output (Phase 3) is not wired
up yet -- cerebrate-infer today always runs on its fixed internal dummy
tensor and returns the resulting classification/timing fields regardless
of what's sent as the trigger.
"""
import asyncio

from mlserver import MLModel
from mlserver.types import InferenceRequest, InferenceResponse, ResponseOutput

DEFAULT_HOST = "10.70.217.78"
DEFAULT_PORT = 8765
CONNECT_TIMEOUT_S = 5.0
REQUEST_TIMEOUT_S = 10.0

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


class CerebrateInferRuntime(MLModel):
    async def load(self) -> bool:
        extra = {}
        if self.settings.parameters is not None:
            extra = self.settings.parameters.extra or {}
        self._host = extra.get("cerebrate_infer_host", DEFAULT_HOST)
        self._port = int(extra.get("cerebrate_infer_port", DEFAULT_PORT))
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

    async def _trigger_once(self) -> dict:
        async with self._lock:
            last_error: Exception = RuntimeError("unreachable")
            for attempt in range(2):
                try:
                    await self._ensure_connected()
                    self._writer.write(b"\n")
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
            raise ConnectionError(
                f"cerebrate-infer at {self._host}:{self._port} unreachable"
            ) from last_error

    async def predict(self, payload: InferenceRequest) -> InferenceResponse:
        result = await self._trigger_once()
        outputs = [
            ResponseOutput(
                name=name,
                shape=[1],
                datatype="INT64",
                data=[result[name]],
            )
            for name in ("request_id", "top_class", "top_score", "inference_us", "handle_us")
        ]
        return InferenceResponse(
            model_name=self.name,
            model_version=self.version,
            outputs=outputs,
        )
