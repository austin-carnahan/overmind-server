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
import io
import os
import subprocess

from PIL import Image

from mlserver import MLModel
from mlserver.codecs.base64 import Base64Codec
from mlserver.types import InferenceRequest, InferenceResponse, ResponseOutput

DEFAULT_HOST = "10.70.217.78"
DEFAULT_PORT = 8765
CONNECT_TIMEOUT_S = 5.0
REQUEST_TIMEOUT_S = 10.0

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
    async def load(self) -> bool:
        extra = {}
        if self.settings.parameters is not None:
            extra = self.settings.parameters.extra or {}
        self._host = extra.get("cerebrate_infer_host") or _discover_avf_gateway()
        self._port = int(extra.get("cerebrate_infer_port", DEFAULT_PORT))
        self._lock = asyncio.Lock()
        self._reader = None
        self._writer = None
        self._labels = _load_labels()
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
