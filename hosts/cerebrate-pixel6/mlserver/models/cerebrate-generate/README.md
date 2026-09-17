# cerebrate-generate MLServer adapter

The Session Execution counterpart to
[`cerebrate-infer`'s adapter](../cerebrate-infer/cerebrate_infer_runtime.py),
per the
[Multi-Runtime Execution Plane](../../../../design-notes/Cerebrate%20Pixel%206%20%E2%80%94%20Multi-Runtime%20Execution%20Plane.md).
Deliberately a separate, standalone module — no shared base class, no
request-type branching inside the existing classifier adapter. The two
Android-host processes (`cerebrate-infer`, `cerebrate-generate`) are
composed together only at this layer, by existing as two separate
MLServer model directories, each with its own adapter dialing its own
port.

Speaks [`cerebrate-generate`'s typed-frame wire protocol](../../../cerebrate-generate/README.md#wire-protocol-typed-frames-changed-for-streaming)
(`DATA`/`DONE`/`ERROR` frames) over a persistent, reused,
auto-reconnecting connection — same pattern as
`cerebrate_infer_runtime.py`, including the identical (deliberately
duplicated, not shared) AVF-gateway auto-discovery helper.

**Requires MLServer ≥1.7.1** (real `infer_stream`/`generate_stream`
support). This project's production MLServer was upgraded from 1.3.5 to
1.7.1 specifically to get this — see the design notes' Progress Notes
for the full story of why 1.3.5 was installed in the first place (a
silent Python-3.13-compatibility resolution, not a real ceiling on
what's released).

## Two entry points, one shared generator underneath

- `predict()` — buffers all `DATA` frames into one response. Backs the
  ordinary `/infer` endpoint; this is what `cerebrate-infer`'s adapter
  also does, for callers that just want the full result.
- `predict_stream()` — yields one `InferenceResponse` per `DATA` frame
  as it arrives. Backs MLServer's `/generate_stream` (and
  `/infer_stream`) endpoints, which stream real Server-Sent Events back
  to the client.

Both call the same internal `_stream_generate()` async generator; only
how the caller consumes it differs. That sharing is fine — it's within
one adapter module. What's kept deliberately separate is this whole
module from `cerebrate-infer`'s.

## Request/response shape

Buffered (`/infer`):

```json
{"inputs": [{"name": "prompt", "shape": [1], "datatype": "BYTES", "data": ["What is the capital of Japan?"]}]}
```

```json
{"outputs": [
  {"name": "text", "datatype": "BYTES", "data": ["The capital of Japan is Tokyo."]},
  {"name": "elapsed_us", "datatype": "INT64", "data": [2559391]}
]}
```

Streaming (`/generate_stream`), same request shape, one SSE `data:`
event per output chunk instead:

```text
data: {"model_name":"cerebrate-generate", ..., "outputs":[{"name":"text","data":["The"]}]}

data: {"model_name":"cerebrate-generate", ..., "outputs":[{"name":"text","data":[" capital"]}]}

...
```

Plain text, not base64 — unlike the image classifier's `BYTES` input,
a text prompt has no binary-encoding reason to go through
`Base64Codec`, so this uses `StringCodec` directly. `elapsed_us` (on
the buffered path only) is measured by the adapter itself around the
whole request, since the wire protocol doesn't report the native
worker's own internal timing.

## Required MLServer settings for streaming (verified, not assumed)

- `MLSERVER_GZIP_ENABLED=false` — MLServer's own source comments this
  explicitly: "GZip middleware does not work with streaming." Default
  is `true`; must be turned off.
- `MLSERVER_PARALLEL_WORKERS=0` — already required in this project
  since Phase 1 for an unrelated uvloop/Python 3.13 crash; also happens
  to be required for streaming.

## Verified (2026-09-17)

Confirmed via a 4-gate sequence before touching production, per the
design notes' Progress Notes:

- **Gate A** — MLServer 1.7.1 under a disposable Python 3.12 venv
  (installed via `uv`, since Debian 13's default Python 3.13 is
  outside 1.7.1's `requires_python` range) reproduces both existing
  models' exact known-good output, unchanged.
- **Gate B** — a trivial fake `predict_stream()` model proved real SSE
  streaming works on a released MLServer version, with chunks arriving
  at their injected 0.5s intervals — before any LiteRT-LM code was
  touched.
- **Gate C** — `cerebrate-generate`'s native streaming (see its own
  README) verified directly over raw TCP.
- **Gate D** — this adapter, wired to real `cerebrate-generate`, tested
  through the full external path
  (`inference.home.arpa` → Caddy → relay → tunnel → MLServer 1.7.1 →
  this adapter → AVF → `cerebrate-generate` → LiteRT-LM): real
  incremental tokens (`"The"`, `" capital"`, `" of"`, `" Germany"`,
  `" is"`, `" Berlin"`, `"."`) arriving over ~170ms, correct content.
- Regression-checked immediately alongside: the classifier
  (`cerebrate-infer`) and the buffered generation path (`/infer` on
  this same model) both still produce identical, correct output under
  the new MLServer version and adapter.

This satisfies success criterion #6 (incremental output) from the
Multi-Runtime Execution Plane's own list — **all 9 of 9 criteria are
now met.**

## Not yet done

- No `max_tokens`/`temperature`/sampling parameters exposed yet — the
  worker uses LiteRT-LM's defaults.
- No error-path testing (worker down, malformed prompt, mid-stream
  disconnect) — only the success path has been verified so far.
- gRPC streaming (client + server, broader than REST's server-only
  streaming) not explored — REST server streaming is enough for the
  current prompt-in/tokens-out shape.
