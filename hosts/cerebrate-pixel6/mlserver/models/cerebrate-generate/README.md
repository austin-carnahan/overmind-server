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

Speaks [`cerebrate-generate`'s wire protocol](../../../cerebrate-generate/README.md#wire-protocol)
(4-byte big-endian length prefix + UTF-8 text, both directions) over a
persistent, reused, auto-reconnecting connection — same pattern as
`cerebrate_infer_runtime.py`, including the identical (deliberately
duplicated, not shared) AVF-gateway auto-discovery helper.

## Request/response shape

```json
{
  "inputs": [
    {"name": "prompt", "shape": [1], "datatype": "BYTES", "data": ["What is the capital of Japan?"]}
  ]
}
```

Plain text, not base64 — unlike the image classifier's `BYTES` input,
a text prompt has no binary-encoding reason to go through
`Base64Codec`, so this uses `StringCodec` directly.

```json
{
  "outputs": [
    {"name": "text", "datatype": "BYTES", "data": ["The capital of Japan is Tokyo."]},
    {"name": "elapsed_us", "datatype": "INT64", "data": [2559391]}
  ]
}
```

`elapsed_us` is measured by the adapter itself (wall-clock around the
TCP round trip), since `cerebrate-generate`'s wire protocol — unlike
`cerebrate-infer`'s — doesn't report its own internal timing back to
the client yet.

## Verified (2026-09-17)

- Locally from inside the guest: `curl localhost:8080/v2/models/cerebrate-generate/infer`
  with `"What is the capital of Japan? Answer in one short sentence."`
  → **"The capital of Japan is Tokyo."** (2.56s), correct.
- Through the full external path (`inference.home.arpa` → Caddy →
  relay → tunnel → MLServer → this adapter → AVF → `cerebrate-generate`
  → LiteRT-LM): `"Name one primary color..."` → **"The primary color is
  blue."** (2.52s), correct.
- The existing `cerebrate-infer` classifier model, queried immediately
  before the generation test in the same session, is unaffected —
  identical `"military uniform"` / 88.6% confidence result as every
  prior test. Both models coexist correctly under one MLServer
  instance.

## Not yet done

- **Incremental/streaming output** — this is the one open item from
  the Multi-Runtime Execution Plan's own Success Criteria (#6) not yet
  satisfied. `cerebrate-generate` only implements synchronous
  `generate_content` today; MLServer 1.6's `generate_stream` and
  `cerebrate-generate`'s already-exported (but unused)
  `litert_lm_session_generate_content_stream` symbol are both available
  when this is picked up, but wiring them together is deliberately
  deferred rather than built speculatively.
- No `max_tokens`/`temperature`/sampling parameters exposed yet — the
  worker uses LiteRT-LM's defaults.
- No error-path testing (worker down, malformed prompt, oversized
  response) — only the success path has been verified so far.
