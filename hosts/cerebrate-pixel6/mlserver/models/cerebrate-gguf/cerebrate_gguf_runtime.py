"""Thin MLServer custom runtime: translates a V2 inference request into
cerebrate-gguf's typed-frame TCP protocol and back.

Doclet Service V3 Stage 3. The request handling is this adapter's own (see
cerebrate_generate_runtime.py's docstring); the worker lifecycle -- on-demand
start, idle stop, making room, the lost-worker retry -- is the shared
../cerebrate-graph/cerebrate_lifecycle.py (2026-10-25). cerebrate-gguf differs
from the other workers in two ways it forces:

- START needs a second GGUF path (mmproj), not just model.
- A request carries an image AND a prompt, not one or the other, so this
  adapter reads two named V2 inputs instead of one.

Also carries the real, measured constraint from Stage 2: a real request
takes ~100 seconds on this device, almost entirely vision encoding.
REQUEST_TIMEOUT_S is set well above that with margin, not left at
cerebrate-infer's/cerebrate-generate's own (far shorter) defaults.

Stage 4 production-run fix (2026-09-18): a real 29-minute, 14-item job
found that a single transient transport failure (a dropped connection,
or one request exceeding the timeout) permanently latched `self.ready =
False`, which made MLServer's own REST layer refuse every *subsequent*
request with "Model not ready" before this adapter's own reconnect logic
ever got a chance to run -- one blip early in a long job silently killed
every enrichment call after it. Fixed by separating three concepts that
were conflated into one flag:

  LOADED    -- the supervisor-managed worker exists and the model config
               is valid. Set once in load()/unload(); never touched by a
               single request's transport outcome.
  CONNECTED -- this adapter currently holds a usable socket to
               cerebrate-gguf. Transient; `_writer is not None and not
               is_closing()`.
  READY     -- a connection can be (re-)established when needed. Not a
               stored flag at all -- `_ensure_connected()` already
               reconnects lazily on the next request if `_writer` was
               dropped, so this falls out for free once LOADED stops
               being conflated with CONNECTED.

`self.ready` (the MLServer-visible flag) now tracks LOADED only (since
2026-10-25: the model settings are valid; the worker itself runs on demand). A
broken socket, EOF, or timeout mid-request invalidates *that
connection*, not the model: drop it, fail that one item, let the next
request attempt a fresh connect. Deliberately NOT restarting the
supervisor-managed worker on a timeout -- a 600s caller-side timeout
means "the caller stopped waiting," not "the worker died" (the
llama-mtmd-cli subprocess may still genuinely be running); the
supervisor already knows how to detect and report a truly dead worker
via its own crash detection, and that's the only thing that should ever
invalidate LOADED.
"""
import asyncio
import itertools
import os
import struct
import sys
import time

from mlserver import MLModel
from mlserver.codecs.base64 import Base64Codec
from mlserver.codecs.string import StringCodec
from mlserver.errors import MLServerError
from mlserver.types import InferenceRequest, InferenceResponse, ResponseOutput

# The shared lifecycle lives with the shared adapter, beside this folder.
_SHARED = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "cerebrate-graph")
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)
import cerebrate_lifecycle as lifecycle  # noqa: E402

DEFAULT_PORT = 8768
CONNECT_TIMEOUT_S = 5.0
# Measured (Stage 2): a real Granite-Docling request takes ~100s on this
# device, ~99% vision encoding. Raised from an initial 240s (Stage 3) to
# 600s after a real 14-item production run (Stage 4, 2026-09-18) showed
# real formula-enrichment calls exceeding 240s -- not a hang, just less
# margin than assumed. Correctness-first value; revisit downward once
# tail latency is actually instrumented (see _log_request below) rather
# than guessed again.
REQUEST_TIMEOUT_S = 600.0
MAX_FRAME_BYTES = 4 * 1024 * 1024

FRAME_DATA = 0
FRAME_DONE = 1
FRAME_ERROR = 2


def _log(request_id: int, event: str, **fields) -> None:
    """Structured, greppable logging for the reconnect/timeout path --
    added specifically because Stage 4's production-run bug was only
    diagnosable at all by reading raw log lines after the fact. request
    id, event name, and whatever timing/outcome fields are relevant."""
    extra = " ".join(f"{k}={v}" for k, v in fields.items())
    print(f"cerebrate-gguf: request_id={request_id} {event} {extra}".rstrip())


def _find_input(payload: InferenceRequest, name: str):
    for inp in payload.inputs or []:
        if inp.name == name:
            return inp
    return None


def _decode_request(payload: InferenceRequest) -> tuple:
    """Returns (image_bytes_or_None, prompt_str). A request needs a
    prompt; an image is optional (cerebrate-gguf's own wire protocol
    supports a text-only request, image_len == 0, per its README's
    "future compatible GGUF models" note) even though every caller today
    -- Docling Serve's picture_description_api, via this adapter -- always
    sends one."""
    prompt_input = _find_input(payload, "prompt")
    if prompt_input is None:
        raise ValueError("no 'prompt' input provided")
    prompts = StringCodec.decode_input(prompt_input)
    if not prompts:
        raise ValueError("prompt input was empty")

    image_bytes = None
    image_input = _find_input(payload, "image")
    if image_input is not None:
        images = Base64Codec.decode_input(image_input)
        if images:
            image_bytes = images[0]

    return image_bytes, prompts[0]


class CerebrateGgufRuntime(MLModel):
    async def load(self) -> bool:
        extra = {}
        if self.settings.parameters is not None:
            extra = self.settings.parameters.extra or {}
        self._host = extra.get("cerebrate_gguf_host") or lifecycle.discover_gateway()
        self._port = int(extra.get("cerebrate_gguf_port", DEFAULT_PORT))
        self._model_path = extra.get("cerebrate_gguf_model_path")
        self._mmproj_path = extra.get("cerebrate_gguf_mmproj_path")
        # Overridable per-instance (not just the module default) so the
        # timeout/reconnect acceptance test can exercise a real timeout
        # in seconds, not 600 of them -- production deployments should
        # leave this unset and get REQUEST_TIMEOUT_S.
        self._request_timeout_s = float(
            extra.get("cerebrate_gguf_request_timeout_s", REQUEST_TIMEOUT_S)
        )
        if not (self._model_path and self._mmproj_path):
            print("cerebrate-gguf: model-settings.json extra needs cerebrate_gguf_model_path and cerebrate_gguf_mmproj_path")
            self.ready = False
            return self.ready
        self._lock = asyncio.Lock()
        self._reader = None
        self._writer = None
        self._request_ids = itertools.count(1)
        self._worker = lifecycle.Worker(
            self.name, {"worker": "gguf", "model": self._model_path, "mmproj": self._mmproj_path},
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
            self._reader.readexactly(5), timeout=self._request_timeout_s
        )
        frame_type = header[0]
        (length,) = struct.unpack(">I", header[1:5])
        if length > MAX_FRAME_BYTES:
            raise ValueError(
                f"cerebrate-gguf reported an implausible frame size: {length}"
            )
        payload = b""
        if length > 0:
            payload = await asyncio.wait_for(
                self._reader.readexactly(length), timeout=self._request_timeout_s
            )
        return frame_type, payload

    async def _generate(self, image_bytes, prompt: str) -> str:
        """One request, one response -- cerebrate-gguf sends exactly one
        FRAME_DATA (the whole llama-mtmd-cli output) then FRAME_DONE, not
        a stream of chunks like cerebrate-generate. Holds the shared
        connection lock for the whole request, same as the other two
        adapters -- cerebrate-gguf is single-threaded and serial, so only
        one request can be in flight against it regardless.

        Transport failures (broken socket, EOF, reset, timeout) here
        invalidate the *connection*, never `self.ready` -- see the
        LOADED/CONNECTED/READY note in the module docstring. A timeout in
        particular does not imply the worker died: the llama-mtmd-cli
        subprocess may still be genuinely running, so the connection is
        dropped (a late response arriving after we've moved on must not
        be misread as a future request's response) but nothing about the
        worker's lifecycle is touched -- no restart, no supervisor call.
        """
        request_id = next(self._request_ids)
        t0 = time.perf_counter()
        image_bytes = image_bytes or b""
        prompt_bytes = prompt.encode("utf-8")
        request = (
            struct.pack(">I", len(image_bytes)) + image_bytes
            + struct.pack(">I", len(prompt_bytes)) + prompt_bytes
        )
        _log(request_id, "start", image_bytes=len(image_bytes), prompt_bytes=len(prompt_bytes))

        async with self._lock:
            last_error: Exception = RuntimeError("unreachable")
            connected = False
            for attempt in range(2):
                reused = self._writer is not None and not self._writer.is_closing()
                try:
                    await self._ensure_connected()
                    _log(request_id, "connected", attempt=attempt, reused=reused)
                    self._writer.write(request)
                    await self._writer.drain()
                    connected = True
                    break
                except (ConnectionError, OSError, asyncio.TimeoutError) as exc:
                    last_error = exc
                    _log(request_id, "connect_failed", attempt=attempt, error=repr(exc))
                    await self._drop_connection()
            if not connected:
                # Both attempts failed to even send the request. Do NOT
                # touch self.ready: this may be a transient network blip,
                # not the worker dying -- the supervisor's own crash
                # detection is the source of truth for that, and the next
                # request gets a fresh, independent reconnect attempt.
                raise ConnectionError(
                    f"cerebrate-gguf at {self._host}:{self._port} unreachable"
                ) from last_error

            try:
                frame_type, frame_payload = await self._read_frame()
            except asyncio.TimeoutError as exc:
                # The caller stopped waiting; the worker's llama-mtmd-cli
                # subprocess may still be chewing on this request. Drop
                # the connection so a late response can't be misread as a
                # later request's response, but that's the full extent of
                # the consequence -- fail this one item, nothing else.
                await self._drop_connection()
                elapsed = time.perf_counter() - t0
                _log(request_id, "timeout", elapsed_s=f"{elapsed:.1f}", limit_s=self._request_timeout_s)
                raise TimeoutError(
                    f"cerebrate-gguf at {self._host}:{self._port} timed out after "
                    f"{elapsed:.1f}s (limit {self._request_timeout_s}s) -- worker may still "
                    "be processing; connection dropped, not restarted"
                ) from exc
            except (ConnectionError, OSError, asyncio.IncompleteReadError) as exc:
                await self._drop_connection()
                _log(request_id, "read_failed", error=repr(exc))
                raise ConnectionError(
                    f"cerebrate-gguf at {self._host}:{self._port} unreachable mid-request"
                ) from exc

            if frame_type == FRAME_ERROR:
                _log(request_id, "worker_error", error=frame_payload.decode("utf-8", "replace"))
                raise RuntimeError(
                    "cerebrate-gguf error: " + frame_payload.decode("utf-8", "replace")
                )
            if frame_type != FRAME_DATA:
                await self._drop_connection()
                raise ValueError(f"unexpected first frame type {frame_type}")
            text = frame_payload.decode("utf-8", "replace")

            done_type, _ = await self._read_frame()
            if done_type != FRAME_DONE:
                await self._drop_connection()
                raise ValueError(f"expected FRAME_DONE, got {done_type}")

            elapsed = time.perf_counter() - t0
            _log(request_id, "success", elapsed_s=f"{elapsed:.1f}", response_bytes=len(text))
            return text

    async def predict(self, payload: InferenceRequest) -> InferenceResponse:
        image_bytes, prompt = _decode_request(payload)
        t0 = time.perf_counter()
        try:
            # A lost worker (ConnectionError) restarts once; a timeout doesn't
            # (the caller stopped waiting; the worker may still be running).
            text = await self._worker.run(lambda: self._generate(image_bytes, prompt))
        except lifecycle.WorkerUnavailable as exc:
            raise MLServerError(f"cerebrate-gguf: could not start the worker: {exc}") from exc
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
