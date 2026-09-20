"""doclet-vlm-adapter: thin OpenAI-compatible shim in front of MLServer's
real V2 inference API, for Docling Serve's picture_description_api.

Doclet Service V3 Stage 3. Deliberately not a public service and not a
new Caddy/DNS route -- `inference.home.arpa` already exists as live
production DNS routing straight to MLServer's own V2 protocol (see
hosts/cerebrate-pixel6/mlserver/README.md's Phase 4); this adapter is an
ordinary HTTP client of that same existing endpoint, reachable from
Docling Serve only over Docker-internal networking. It contains no
Docling-specific logic and knows nothing about DoclingDocument, picture
crops, or formulas -- it only translates one HTTP shape into another.

Contract (found empirically in experiments/doclet-service Stage 1):
Docling validates the response as a full OpenAiApiResponse -- id,
created, choices (index/message/finish_reason) -- and silently discards
anything that fails that validation, with the failure visible only in
Docling Serve's own log. Every field below exists because that failure
mode was reproduced and confirmed once already; skipping one is not a
hypothetical risk.

Stdlib only, deliberately -- this is a translation shim, not an
application; no reason to pull in a web framework for one POST route.

Response sanitation (Stage 4, 2026-09-18): a real production run found
one formula (out of 9) come back with the correct LaTeX prefix followed
by hundreds of repetitions of a trivial 2-character unit ("\\ ") padding
out to the generation cap -- the same deterministic-greedy-decoding
repetition-loop failure already documented for cerebrate-generate's
SmolLM2 (temp=0 sometimes never emits its stop token). This lives here,
not in Docling or in cerebrate-gguf: it's a generic generative-runtime
pathology this project has now seen on more than one model path, not a
formula- or Docling-specific problem, and this is the layer that already
owns "shape the model's raw output into the response contract the
caller gets." Deliberately narrow and conservative -- detect a long,
exact-repeating short suffix with a substantial non-repeating prefix
before it, trim it, and say so via `finish_reason` and a log line;
nothing here touches decoding parameters, retries, or cerebrate-gguf
itself. See _detect_degenerate_suffix's docstring for the exact
thresholds and test/degenerate_suffix_fixtures.py for the regression
fixture taken directly from that real output.
"""
import base64
import itertools
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_request_ids = itertools.count(1)


def _log(request_id: int, event: str, **fields) -> None:
    extra = " ".join(f"{k}={v}" for k, v in fields.items())
    print(f"doclet-vlm-adapter: request_id={request_id} {event} {extra}".rstrip(), flush=True)

MLSERVER_INFER_URL = os.environ.get(
    "MLSERVER_INFER_URL", "http://inference.home.arpa/v2/models/cerebrate-gguf/infer"
)
# Timeout layering, outer wraps inner with margin so the innermost timeout
# always fires first and produces a clean, attributable error instead of
# an outer layer giving up mid-request:
#   cerebrate_gguf_runtime.py REQUEST_TIMEOUT_S = 600s (innermost)
#   this adapter's own outbound call                = 630s
#   Docling's own per-job picture_description_api.timeout /
#     code_formula_custom_config.engine_options.timeout (caller-supplied,
#     not controlled here) should be set to >= 660s
# Raised from an initial 240s (Stage 3) after a real 14-item production
# run (Stage 4, 2026-09-18) found real formula-enrichment calls
# genuinely exceeding it -- not a hang, just less margin than assumed.
REQUEST_TIMEOUT_S = float(os.environ.get("DOCLET_VLM_ADAPTER_TIMEOUT_S", "630"))
LISTEN_PORT = int(os.environ.get("PORT", "9100"))


def _extract_image_and_prompt(body: dict) -> tuple:
    """Docling's api_image_request() (docling/utils/api_image_request.py)
    always sends exactly one user message with an image_url part (a
    data: URI) and a text part -- verified directly against that source
    in experiments/doclet-service Stage 1, not assumed."""
    prompt_text = None
    image_b64 = None
    for message in body.get("messages", []):
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            part_type = part.get("type")
            if part_type == "image_url":
                url = part.get("image_url", {}).get("url", "")
                image_b64 = url.split(",", 1)[1] if "," in url else url
            elif part_type == "text":
                prompt_text = part.get("text")
    if prompt_text is None:
        raise ValueError("no text part found in request messages")
    return image_b64, prompt_text


def _call_mlserver(request_id: int, image_b64, prompt: str) -> str:
    inputs = [{"name": "prompt", "shape": [1], "datatype": "BYTES", "data": [prompt]}]
    if image_b64:
        inputs.insert(
            0,
            {
                "name": "image",
                "shape": [1],
                "datatype": "BYTES",
                "data": [image_b64],
                "parameters": {"content_type": "base64"},
            },
        )
    payload = {"inputs": inputs}
    request = urllib.request.Request(
        MLSERVER_INFER_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.perf_counter()
    _log(request_id, "mlserver_call_start", has_image=bool(image_b64), prompt_bytes=len(prompt))
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:
            result = json.loads(response.read())
    except Exception as exc:
        _log(request_id, "mlserver_call_failed", elapsed_s=f"{time.perf_counter()-t0:.1f}", error=repr(exc))
        raise
    for output in result.get("outputs", []):
        if output.get("name") == "text":
            _log(request_id, "mlserver_call_success", elapsed_s=f"{time.perf_counter()-t0:.1f}")
            return output["data"][0]
    _log(request_id, "mlserver_call_bad_response", elapsed_s=f"{time.perf_counter()-t0:.1f}")
    raise RuntimeError(f"MLServer response missing a 'text' output: {result!r}")


# Detection thresholds -- deliberately conservative, tuned to fire only on
# an unambiguous decoder failure, never on legitimately repetitive real
# content (e.g. a table of zeros, or LaTeX with genuinely repeated
# symbols a few times over).
_MIN_PERIOD = 1
_MAX_PERIOD = 8
_MIN_REPEATS = 8          # the repeating unit must recur at least this many times
_MIN_SUFFIX_FRACTION = 0.2  # the repeated run must be a substantial tail
_MIN_PREFIX_CHARS = 20      # there must be real content before the repetition


def _detect_degenerate_suffix(text: str):
    """Finds an exact-repeating short suffix (a decoder stuck emitting the
    same 1-8 character unit, e.g. "\\ \\ \\ \\ ..." or "0.0 0.0 0.0 ..."
    or "......."), conservative by design: only reports the longest
    qualifying suffix, and only if it's a substantial fraction of the
    whole response with real content before it. Returns
    (trim_index, period, repeats) or None if nothing qualifies.

    Deliberately exact-match only (no fuzzy/whitespace-normalized
    comparison) -- a real degenerate run from greedy decoding repeats the
    identical token sequence, so exact match is precise and a missed
    detection just means the (safe) fallback of returning the untrimmed
    text, never a false trim of real content."""
    n = len(text)
    best = None  # (suffix_len, trim_index, period, repeats)
    for period in range(_MIN_PERIOD, _MAX_PERIOD + 1):
        if period > n:
            break
        unit = text[n - period:n]
        repeats = 0
        pos = n
        while pos - period >= 0 and text[pos - period:pos] == unit:
            repeats += 1
            pos -= period
        if repeats < _MIN_REPEATS:
            continue
        suffix_len = repeats * period
        if suffix_len / n < _MIN_SUFFIX_FRACTION:
            continue
        prefix_len = n - suffix_len
        if prefix_len < _MIN_PREFIX_CHARS:
            continue
        if best is None or suffix_len > best[0]:
            best = (suffix_len, pos, period, repeats)
    if best is None:
        return None
    _, trim_index, period, repeats = best
    return trim_index, period, repeats


def _sanitize_output(request_id: int, text: str) -> tuple:
    """Returns (text, finish_reason). Trims a detected degenerate suffix
    and reports it -- both via a log line (so this is distinguishable
    from ordinary success in aggregate, not silently absorbed) and via
    `finish_reason: "length"` (the closest existing OpenAI-standard
    semantic: generation was cut off rather than stopping cleanly),
    rather than inventing a non-standard field Docling's strict
    OpenAiApiResponse validation might not tolerate."""
    hit = _detect_degenerate_suffix(text)
    if hit is None:
        return text, "stop"
    trim_index, period, repeats = hit
    trimmed = text[:trim_index].rstrip()
    _log(
        request_id, "degenerate_suffix_detected",
        original_chars=len(text), trimmed_chars=len(text) - len(trimmed),
        period=period, repeats=repeats,
    )
    return trimmed, "length"


def _openai_response(model: str, text: str, finish_reason: str) -> dict:
    return {
        "id": f"doclet-vlm-{uuid.uuid4()}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": finish_reason,
            }
        ],
    }


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self._send_json(404, {"error": {"message": "not found"}})
            return

        request_id = next(_request_ids)
        t0 = time.perf_counter()
        length = int(self.headers.get("Content-Length", 0))
        _log(request_id, "received", content_length=length)
        try:
            body = json.loads(self.rfile.read(length))
            image_b64, prompt = _extract_image_and_prompt(body)
            text = _call_mlserver(request_id, image_b64, prompt)
        except (ValueError, KeyError) as exc:
            _log(request_id, "bad_request", elapsed_s=f"{time.perf_counter()-t0:.1f}", error=repr(exc))
            self._send_json(400, {"error": {"message": str(exc)}})
            return
        except (urllib.error.URLError, TimeoutError, RuntimeError, OSError) as exc:
            _log(request_id, "upstream_error", elapsed_s=f"{time.perf_counter()-t0:.1f}", error=repr(exc))
            self._send_json(502, {"error": {"message": f"upstream error: {exc}"}})
            return

        text, finish_reason = _sanitize_output(request_id, text)
        _log(request_id, "done", elapsed_s=f"{time.perf_counter()-t0:.1f}", finish_reason=finish_reason)
        self._send_json(200, _openai_response(body.get("model", "cerebrate-gguf"), text, finish_reason))

    def _send_json(self, code: int, obj: dict) -> None:
        payload = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} - {fmt % args}", flush=True)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", LISTEN_PORT), Handler)
    print(
        f"doclet-vlm-adapter listening on :{LISTEN_PORT}, "
        f"forwarding to {MLSERVER_INFER_URL}",
        flush=True,
    )
    server.serve_forever()
