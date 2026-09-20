# doclet-vlm-adapter

Doclet Service V3 Stage 3. A thin OpenAI-compatible shim between Docling
Serve's `picture_description_api` and MLServer's real V2 inference API —
built because Docling Serve speaks one HTTP shape
(`POST /v1/chat/completions`, OpenAI chat-completions) and MLServer
speaks another (`POST /v2/models/<name>/infer`, the KServe V2 inference
protocol), and nothing upstream bridges them.

## Not a new public service

**Important correction, made before this was built**: the design doc's
first draft called this adapter `inference.home.arpa`. That name is
already live production DNS
([`hosts/dns-rewrites.yaml`](../../../hosts/dns-rewrites.yaml),
[`services/caddy/Caddyfile`](../../caddy/Caddyfile)), reverse-proxying
straight to MLServer's own V2 protocol today — see
[`hosts/cerebrate-pixel6/mlserver/README.md`](../../../hosts/cerebrate-pixel6/mlserver/README.md)'s
Phase 4. Putting a new, differently-shaped adapter at that same hostname
would have collided with a route real clients already depend on. Caught
by checking the actual DNS/Caddy config before building anything, the
same way Stage 1 caught the `/mnt/doclet` deployment-shape mistake.

`doclet-vlm-adapter` therefore has **no new public hostname and no new
Caddy route**. It's meant to run alongside Docling Serve (same Docker
network, reachable by Docling Serve's own service name once
`services/doclet/compose.yaml` exists in Stage 4) and calls the
*existing* `inference.home.arpa` endpoint itself, as an ordinary HTTP
client — exactly what any other MLServer consumer does.

```text
Docling Serve
      │  POST /v1/chat/completions  (Docker-internal only)
      ▼
doclet-vlm-adapter
      │  POST http://inference.home.arpa/v2/models/cerebrate-gguf/infer
      ▼
MLServer  →  cerebrate-gguf runtime  →  cerebrate-supervisor  →  cerebrate-gguf  →  Granite-Docling GGUF
```

## Contract, not guesswork

Every field this adapter's response includes exists because
[experiments/doclet-service Stage 1](../../../experiments/doclet-service/stage1-picture-description-api/README.md)
found the real, silent failure mode: Docling validates the response
against a full `OpenAiApiResponse` (`id`, `created`, `choices` with
`message`/`finish_reason`) and discards anything that fails, with no
error surfaced anywhere except Docling Serve's own log. `id`/`created`
are synthesized here (`doclet-vlm-<uuid>`, current Unix time) since
MLServer's own V2 response has no equivalent fields to pass through.

Request parsing mirrors Docling's own `api_image_request()`
(`docling/utils/api_image_request.py`, read directly, not guessed):
exactly one user message, a `content` list with one `image_url` part (a
`data:` URI) and one `text` part.

## Deliberately stdlib-only

This is a translation shim, not an application — `http.server` +
`urllib.request`, no web framework, matching the "thin adapter, no
Docling-specific logic" principle carried through from the design doc's
V2 draft. It knows nothing about `DoclingDocument`, picture crops, or
formulas.

## Verified (2026-09-18)

- A hand-built request matching Docling's exact wire shape (real base64
  PNG test image, `Convert this page to docling.` prompt) round-tripped
  correctly through this adapter → `inference.home.arpa` → MLServer →
  `cerebrate-gguf` → the real Android worker, returning the
  byte-identical, already-proven DocTags result in **104.1s**, wrapped
  in a schema-valid `OpenAiApiResponse`.
- A real, genuine Docling Serve conversion job (not a hand-built mimic),
  `picture_description_api` pointed at this adapter's real
  `/v1/chat/completions` endpoint, was attempted against the same test
  PDF as [experiments/doclet-service Stage 1](../../../experiments/doclet-service/stage1-picture-description-api/README.md)
  and did **not** complete — see the finding immediately below. The
  adapter itself was never implicated: the job died before any of its
  5 pictures reached the enrichment step that would call this adapter.

## Real finding: genuine Docling Serve was OOM-killed on overmind-01 during this test (not an adapter/contract bug)

Confirmed via kernel log (`sudo dmesg`), not inferred:

```text
Out of memory: Killed process 802373 (docling-serve) total-vm:6235536kB, anon-rss:2314808kB, file-rss:40kB, shmem-rss:201852kB, UID:1000 pgtables:6872kB oom_score_adj:0
```

The `docling-serve` process itself grew to ~2.3GB RSS running the
standard pipeline (layout/OCR/table models) on this test PDF; the host
had ~5.5GB of its 7.6GB total already committed to other production
services (Jellyfin, Transmission, etc. — see
[services/compose.yaml](../../compose.yaml)) at the time, and **zero
swap is configured on overmind-01** — a risk already flagged in
[experiments/docling](../../../experiments/docling/README.md)'s
environmental findings but not previously observed to actually trigger
a kill. It did here, for the first time, confirmed by PID/timestamp
matching exactly when the job's log output stopped.

This is a real constraint on the *genuine, full Docling Serve process*
sharing this specific host with everything else already running on
it — not a defect in `doclet-vlm-adapter`, the MLServer runtime, or
anything on the Cerebrate/Android side, all of which were verified
correct independently above. Squarely a Stage 4 production-sizing
concern (this exact same memory profile applies to the real
`docling-serve-cpu` container Stage 4 deploys), not something to solve
inside this adapter. Options for Stage 4 to weigh: add swap to
overmind-01, set a container memory limit with graceful degradation
instead of a hard OOM kill, or reduce concurrent load on the host during
conversion jobs. Not decided or built here — recorded so Stage 4 doesn't
rediscover this by hitting the same kill blind.

## Response sanitation: trimming a degenerate decoder suffix (2026-09-18)

A real production run (5 pictures + 9 formulas, see
[experiments/doclet-service/production-run-2026-09-18-v2](../../../experiments/doclet-service/production-run-2026-09-18-v2))
succeeded end to end after the reconnect/timeout fixes documented in
[cerebrate-gguf's MLServer adapter README](../../../hosts/cerebrate-pixel6/mlserver/models/cerebrate-gguf/README.md) —
9/9 formulas and 3/3 real pictures got content — but one formula came back
with the correct LaTeX prefix followed by ~1900 repetitions of a trivial
2-character unit (`"\ "`) padding out to the token cap. Same class of
failure already documented for `cerebrate-generate`'s SmolLM2 (`temp=0`
deterministic decoding sometimes never emits its stop token) — a
generic generative-runtime pathology, not specific to formulas or to
this model.

Fixed here, not in Docling or `cerebrate-gguf.cc`, deliberately: this is
the layer that already owns "shape the model's raw output into the
response contract," and the pathology has now shown up on more than one
model path, so it belongs in one general place rather than duplicated
per-worker. `_detect_degenerate_suffix()` conservatively looks for an
exact-repeating short (1-8 char) unit recurring at least 8 times,
constituting at least 20% of the response, with at least 20 real
characters before it — tuned to catch `"\ \ \ \ ..."`, `"0.0 0.0 0.0 ..."`,
or `"......."` -style decoder failures without ever touching legitimately
repetitive real content (a table of a few repeated zeros, LaTeX with a
symbol repeated a few times). When it fires: trim to the recovered
prefix, log `degenerate_suffix_detected` with the trimmed length and
repeat count (so this is visible in aggregate — "how often does this
happen" — not silently absorbed), and report `finish_reason: "length"`
instead of `"stop"` (the closest existing OpenAI-standard signal for
"generation was cut off," rather than inventing a non-standard field
Docling's strict response validation might not tolerate).

Deliberately **not** done here: no retry, no decoding-parameter changes,
no touching `cerebrate-gguf` — a retry costs another ~100s+ and the real
example shows the correct answer was already produced before the model
wandered off, so recovering the existing prefix is strictly cheaper and
just as correct. See [test/test_degenerate_suffix.py](test/test_degenerate_suffix.py)
for the regression test, using the real (not synthetic) malformed output
as its fixture.

## Configuration

Environment variables, no config file:

- `MLSERVER_INFER_URL` (default `http://inference.home.arpa/v2/models/cerebrate-gguf/infer`)
- `DOCLET_VLM_ADAPTER_TIMEOUT_S` (default `630` — see the timeout-layering
  note in `cerebrate_gguf_runtime.py`'s module docstring; raised from an
  initial 240 after real formula-enrichment calls were found exceeding it)
- `PORT` (default `9100`)
