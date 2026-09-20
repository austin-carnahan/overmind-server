# Doclet Service — Implementation Design V3

## Goal

Deploy a production document → Markdown service on Overmind using:

- **Docling Serve** for the public API, async jobs, conversion orchestration, and results;
- **Docling standard parsing** for text/layout/tables/figures;
- **Cerebrate Pixel 6** for selective VLM enrichment;
- **MLServer** for model lifecycle and serving;
- **llama.cpp / libmtmd** as a reusable GGUF execution backend.

Guiding separation:

```text
Docling Serve = document service
MLServer      = model service
Android       = inference execution
```

## What changed from V2

V2 assumed a custom Docling enrichment plugin and a separate formula/code
enrichment path (`do_formula_enrichment` / `CodeFormulaVlmOptions`) pointed
at a remote API engine. Verifying both claims against the real, current
(2026-09-17) upstream source changed the design:

- **No custom Docling plugin is needed.** Docling Serve already exposes
  `do_picture_description` / `PictureDescriptionApiOptions` as a first-class,
  fully-wired OpenAI-compatible remote-API config
  (`DOCLING_SERVE_ENABLE_REMOTE_SERVICES=true`). This does everything V2's
  plugin would have done, using infrastructure that already exists and is
  already tested upstream.
- **`do_picture_description` structurally cannot reach formulas, confirmed
  with a real document (2026-09-18).** Regardless of the point below,
  `FormulaItem` is a `TextItem` subclass, not a `PictureItem` — verified
  directly against `docling_core`'s class hierarchy and empirically: a
  real conversion of this project's own test paper (9 real formulas) put
  every one of them in `document.texts`, none in `document.pictures`.
  Picture and formula enrichment are two genuinely separate paths, not
  one surface — the "unify under `do_picture_description`" idea below was
  wrong on structural grounds alone, independent of the runtime question.
- **Formula/code enrichment via a remote API engine — corrected finding,
  2026-09-18: it works, using the current pipeline, not the one
  originally investigated.** The 2026-09-17 investigation (below,
  preserved for the record) found the *legacy* `CodeFormulaModel`
  (`docling/models/stages/code_formula/code_formula_model.py`) hardcodes
  `transformers` with no API branch. That class turned out to be dead
  code: the actual standard pipeline
  (`docling/pipeline/standard_pdf_pipeline.py`) only ever instantiates
  `CodeFormulaVlmModel` (`code_formula_vlm_model.py`), a newer,
  runtime-agnostic stage built on the exact same `create_vlm_engine`/
  `ApiVlmEngine`/`api_image_request()` machinery `do_picture_description`
  already uses — confirmed by reading that file directly, not inferred.
  My original PR search (`CodeFormulaV2` in title/body) missed the
  generalization because the new file doesn't mention that string.
  **Verified working end to end**, not just structurally: a real
  `do_formula_enrichment=True` job with a `code_formula_custom_config`
  (`engine_type: api`, pointed at `doclet-vlm-adapter`) produced correct
  LaTeX for 9/9 real formulas in this project's test paper (one came out
  visibly lower quality — not every transcription was clean, a real
  finding worth watching, not a failure). One additional gate needed and
  found empirically: `DOCLING_SERVE_ALLOW_CUSTOM_CODE_FORMULA_CONFIG=true`
  (the server-side allowlist from issues #526/#527) — `do_picture_description`
  never needed this because this project uses its older, ungated
  `picture_description_api` field, not `picture_description_custom_config`.
- **Original 2026-09-17 finding, preserved for the record (superseded
  above, not deleted — this is what an incomplete-but-real investigation
  looked like before a sharper one corrected it):** `code_formula_custom_config`'s
  request schema exists (`engine_type: api/api_openai/api_ollama/api_lmstudio`),
  and the wiring bug that once blocked it (`allow_custom_code_formula_config`
  never reaching `DoclingConverterManagerConfig`) was fixed in Docling
  Serve v1.14.1 (2026-03-03, issues #526/#527). At the time, the only
  code path found actually executing `CodeFormulaV2` was transformers-only,
  and IBM maintainer dolfim-ibm's 2026-01-21 comment (upstream discussion
  #2903) that generalizing it was "just about to" happen appeared not yet
  shipped, based on a PR search that (it turns out) didn't find the file
  where it actually landed.

Net effect: figures/charts (`do_picture_description`) and formulas
(`do_formula_enrichment`) are two separate, parallel enrichment paths,
both pointed at the same `doclet-vlm-adapter`/Cerebrate backend, both
using Docling Serve's own already-tested remote-API machinery. Simpler
than V2's custom plugin, but not the single unified surface the
2026-09-17 draft of this section originally concluded.

## Architecture

```text
client
  ↓
doclet.home.arpa
  ↓
Caddy
  ↓
Docling Serve — Overmind
  │
  ├── standard Docling pipeline
  │     ├── native text
  │     ├── layout
  │     ├── tables
  │     ├── figures
  │     └── formulas
  │
  ├── do_picture_description (PictureDescriptionApiOptions)
  │   -- figures, diagrams, charts (PictureItem)
  │
  └── do_formula_enrichment (CodeFormulaVlmOptions, engine=api)
      -- formulas (FormulaItem) -- a separate path, NOT unified with
      -- picture description; structurally cannot be (see "What changed
      -- from V2" for why an earlier draft of this doc was wrong about that)
          ↓          ↓
      (both routes converge here)
          ↓
    doclet-vlm-adapter  (thin OpenAI-compatible adapter, Docker-internal only)
          ↓
    inference.home.arpa  (existing production MLServer route)
          ↓
       MLServer
          ↓
   llama_cpp runtime
          ↓
 cerebrate-supervisor  (new `gguf` worker type, port 8768)
          ↓
   cerebrate-gguf
          ↓
 Granite-Docling GGUF  (libmtmd / llama-mtmd-cli path)
```

Do not use `llama-server` for Granite-Docling; its multimodal serving path
was experimentally confirmed incorrect (upstream `llama.cpp#16601`). Build
the Android worker around the proven `libmtmd` / `llama-mtmd-cli` inference
path.

**Corrected from the original draft of this doc**: `inference.home.arpa`
is not a free name to reuse for a new adapter — it's already live
production DNS ([`hosts/dns-rewrites.yaml`](../hosts/dns-rewrites.yaml),
[`services/caddy/Caddyfile`](../services/caddy/Caddyfile)) reverse-proxying
straight to MLServer's own native V2 protocol
(`POST /v2/models/<name>/infer`), serving `cerebrate-infer` today and
`cerebrate-generate`/`cerebrate-gguf` the same way — see
[`hosts/cerebrate-pixel6/mlserver/README.md`](../hosts/cerebrate-pixel6/mlserver/README.md)'s
Phase 4. Putting a *new* OpenAI-compatible adapter at that same hostname
would collide with a route real clients already depend on. Caught before
building anything, the same way the `/mnt/doclet` deployment-shape mistake
was caught in Stage 1.

The corrected shape: `doclet-vlm-adapter` is a small internal-only service
(no new public hostname, no new Caddy route) that runs alongside Docling
Serve — reachable from it over Docker-internal networking only — and
itself calls the *existing* `inference.home.arpa` endpoint as an ordinary
HTTP client, exactly like any other MLServer consumer would. It translates
an OpenAI-compatible `picture_description_api` request (image + prompt)
into a real MLServer V2 `POST /v2/models/cerebrate-gguf/infer` call, and
translates the V2 response back into the `OpenAiApiResponse` shape Stage
1 found Docling Serve requires (`id`, `created`, `choices[].message`,
`finish_reason`). It contains no Docling workflow logic, matching the "no
Docling-specific logic outside Docling Serve itself" principle from V2.

## Overmind Deployment

Follow the same pattern every other Overmind service uses
([services/](../services/), e.g. [paperclip](../services/paperclip/README.md)):
a `services/doclet/compose.yaml` checked into this repo and deployed from
`/opt/overmind` on overmind-01, not a bare venv installed directly on the
SSD. `/mnt/<name>` bind mounts (`/mnt/substrate`, `/mnt/library`,
`/mnt/models`, ...) are for shared, cross-service, non-Docker-owned
storage — not the right place for one service's own container state. An
earlier draft of this stage installed Docling Serve into a bare `uv` venv
under a new `/mnt/doclet` bind mount; that was corrected once compared
against how every real service in this repo is actually deployed (see
[experiments/doclet-service/stage1-picture-description-api](../experiments/doclet-service/stage1-picture-description-api/README.md)
for the full note and cleanup).

Docling Serve publishes an official multi-arch (`linux/amd64` +
`linux/arm64`) CPU-only image,
[`ghcr.io/docling-project/docling-serve-cpu`](https://github.com/docling-project/docling-serve/pkgs/container/docling-serve-cpu) —
use it directly rather than building or installing from source, matching
`paperclip`'s "pinned upstream image over from-source build" precedent.
Pin by tag and digest together:

```text
ghcr.io/docling-project/docling-serve-cpu:v1.34.0@sha256:0525640504db7ed8a53e0e443882727888f6a3746948b1b7a8820efe95567bd3
```

(Manifest-list digest, covering both platforms — resolve a fresh one
before actually deploying, same caveat as `paperclip`'s pinned image.)

State lives at `/var/lib/overmind/doclet/` (already SSD-backed via the
existing `/mnt/disks/ssd1/var-lib-overmind` bind mount — no new mount
needed), mapped to the container's `DOCLING_SERVE_SCRATCH_PATH`. The
existing shared model cache mounts in separately, read/write, unchanged:

```text
/mnt/models/huggingface/   ->  HF_HOME (container env)
```

```yaml
# services/doclet/compose.yaml (sketch)
services:
  doclet:
    image: ghcr.io/docling-project/docling-serve-cpu:v1.34.0@sha256:...
    container_name: doclet
    environment:
      DOCLING_SERVE_ENABLE_REMOTE_SERVICES: "true"
      DOCLING_SERVE_SCRATCH_PATH: /scratch
      HF_HOME: /hf-cache
    volumes:
      - /var/lib/overmind/doclet/scratch:/scratch
      - /mnt/models/huggingface:/hf-cache
    ports:
      - "127.0.0.1:5001:5001"
    restart: unless-stopped
```

Front it with Caddy at `https://doclet.home.arpa`, same as the other
Caddy-fronted services, bound to loopback like `paperclip` rather than
publishing the container port broadly.

Use Docling Serve's existing async job, status, result, retention, and API
machinery rather than creating a parallel Doclet REST API.

## Document Processing Policy

Normal Docling remains authoritative for document parsing.

Do **not** use full-page VLM conversion by default.

`do_picture_description` should target:

- figures and diagrams;
- charts/graphs;
- other explicitly difficult visual elements.

`do_formula_enrichment` (`code_formula_custom_config`, `engine_type: api`,
`extract_code: false`) handles formulas/equations separately — confirmed
working end to end (2026-09-18), see "What changed from V2." Not routed
through `do_picture_description`, which structurally cannot reach
`FormulaItem` regardless of configuration.

Ordinary embedded PDF text should remain on Docling's deterministic path.

Initial enrichment behavior should be:

```text
best_effort
```

If Cerebrate is unavailable, conversion should still succeed with the
normal Docling result plus a warning.

## llama.cpp Backend

Establish `llama.cpp` as a generic Cerebrate execution backend.

Create:

```text
cerebrate-gguf
```

Responsibilities:

- load a configured GGUF model;
- load an optional multimodal projector;
- accept bounded text/image requests;
- execute through `libllama` / `libmtmd`;
- return generated output;
- contain no Docling-specific workflow logic.

`cerebrate-gguf` is a persistent-transport wrapper that runs
`llama-mtmd-cli` once per request rather than a long-lived server process
— `llama-server`'s multimodal serving path is the confirmed-broken one, and
the CLI path is the only one with proven-correct output. The wrapper owns
process lifecycle (spawn, feed request, capture output, tear down) and
presents a stable request/response interface to the supervisor and to
the MLServer `llama_cpp` runtime, so a future move to a real persistent server (if
upstream fixes `llama-server`) doesn't change anything above this layer.

Granite-Docling is the first model using this backend:

```yaml
backend: llama_cpp
capability: document-vision

artifacts:
  model: granite-docling-258M-bf16.gguf
  mmproj: mmproj-model-f16.gguf

modality:
  - text
  - image

residency: on_demand
```

Future compatible GGUF language or multimodal models should reuse the
same worker.

## MLServer Integration

Add a generic `llama_cpp` MLServer runtime, following the existing
`cerebrate_infer_runtime.py` / `cerebrate_generate_runtime.py` pattern
(`_supervisor_request()` helper, file-backed PID-tagged refcount,
`self.ready = False` on confirmed-dead connection).

Lifecycle:

```text
MLServer load
  ↓
supervisor START llama
  ↓
cerebrate-gguf
  ↓
load GGUF/mmproj
  ↓
health/readiness probe
  ↓
READY
```

Unload:

```text
MLServer unload
  ↓
supervisor STOP llama
```

Docling therefore interacts with the same Cerebrate serving/lifecycle
layer as other models.

The AVF Debian guest should contain only lightweight control-plane
components:

```text
MLServer
llama_cpp adapter
existing model adapters
configuration
```

PDFs, caches, and GGUF model storage should not live in the guest.

## cerebrate-supervisor Extension

`cerebrate-supervisor` is otherwise frozen (per the Phase B milestone);
this is a deliberate, bounded, explicit exception, not casual iteration.

Add one new `WorkerSlot` entry to the existing hardcoded table:

```text
llama  →  port 8768
```

Same START/STOP/STATUS/LIST protocol, same model-path validation
(flat `/data/local/tmp/` only), same idempotent START/STOP and crash
detection via `waitpid(WNOHANG)`, same pre-flight orphan-port check. No
protocol changes — this is additive within the existing design.

## Android Layout

Use the existing staged-artifact convention:

```text
/data/local/tmp/cerebrate/
├── bin/
│   └── cerebrate-gguf
└── models/
    └── granite-docling/
        ├── model.gguf
        └── mmproj.gguf
```

Images cross the AVF boundary only for inference and do not become
durable Android state.

## Acceptance Test: Granite Correctness

Before this service is considered functional, `cerebrate-gguf` must
reproduce the already-proven `llama-mtmd-cli` output exactly (or
equivalently) for the known-good DocTags case from
`experiments/docling`. This is a hard acceptance gate, not a smoke test:
if the wrapper regresses the CLI's correct behavior (wrong marker
placement, wrong tiling, wrong output), nothing downstream can be trusted
regardless of what Docling Serve or MLServer report.

## Implementation Sequence (4 stages)

### Stage 1 — Prove the enrichment path end-to-end with a dummy backend (done)

See [experiments/doclet-service/stage1-picture-description-api](../experiments/doclet-service/stage1-picture-description-api/README.md)
for the full result. Proven end to end against a real, pinned Docling
Serve v1.34.0 install on overmind-01: a real conversion job sent 3 actual
image crops to a dummy OpenAI-compatible endpoint, and the dummy's
response landed in both the document's structured metadata
(`pictures[i].meta.description.text`) and the final markdown output.

One concrete contract requirement for Stage 3's `doclet-vlm-adapter`
came out of this: Docling validates the remote response as a full
`OpenAiApiResponse` (`id`, `created`, `choices` with `message`/
`finish_reason`) and silently no-ops with an empty description — no error
surfaced to the job status — if that shape isn't met exactly. Confirmed by
reproducing the failure (a response missing `created`) and then fixing it.

The proof was run against a bare `uv`-venv install at a new `/mnt/doclet`
bind mount, which is **not** the deployment shape this design actually
uses — corrected to a `services/doclet/compose.yaml` container against the
official `docling-serve-cpu` image, matching how every other Overmind
service is deployed (see "Overmind Deployment" above). The proof itself
(the round trip and the `OpenAiApiResponse` contract requirement) is a
property of Docling Serve's own code, not of how it happens to be
packaged, so nothing about the finding needed to be redone — only the
deployment target changed.

### Stage 2 — `cerebrate-gguf` + supervisor extension + acceptance test (done)

See [`cerebrate-gguf`](../hosts/cerebrate-pixel6/cerebrate-gguf/README.md)
and [`cerebrate-supervisor`'s Stage 2 section](../hosts/cerebrate-pixel6/cerebrate-supervisor/README.md#doclet-service-v3-stage-2-gguf-worker--mmproj-field)
for the full writeup. All four steps done:

1. Added the `gguf` `WorkerSlot` (port 8768) and one new wire-protocol
   key, `mmproj` — needed because this worker takes two GGUF paths, not
   one, discovered while implementing rather than assumed in advance.
2. Built `cerebrate-gguf`: binds/listens immediately like the other
   workers, but forks a fresh `llama-mtmd-cli` process per request
   instead of holding a model loaded in-process.
3. Acceptance test passed **through the supervisor**: byte-identical
   DocTags output to the original CLI result
   (`<doctag><picture>...<line_chart></picture></doctag>`), ~103s,
   matching the original experiment's timing.
4. Failure/recovery characterized live: missing/invalid `mmproj`,
   config-conflict-while-running, idempotent START, and crash detection
   all behave correctly by reusing existing supervisor mechanisms
   unchanged. One real gap found and recorded, not fixed: killing
   `cerebrate-gguf` mid-request orphans its `llama-mtmd-cli` child
   (harmless — it finishes and exits on its own) but leaks the temp
   request image file, since the cleanup code never runs. Deferred, same
   category as the supervisor's existing documented "no automatic
   respawn-on-crash" gap.

Naming note carried over from `cerebrate-gguf`'s own README: it names the
artifact format/runtime lane, breaking `cerebrate-infer`/
`cerebrate-generate`'s what-it-does naming convention. Kept as-is to avoid
mid-implementation churn; revisit (`cerebrate-multimodal`/`cerebrate-vlm`
fit the convention better) if this worker's scope grows beyond one
Granite-Docling GGUF model.

Also recorded: a real Granite-Docling request takes ~100 seconds
(matching the original experiment, almost entirely vision encoding) —
Stage 3's `doclet-vlm-adapter` and Docling Serve's own
`picture_description_api.timeout` must both be configured well above
that.

### Stage 3 — MLServer `llama_cpp` runtime + `doclet-vlm-adapter` (done)

See [`cerebrate-gguf`'s MLServer adapter README](../hosts/cerebrate-pixel6/mlserver/models/cerebrate-gguf/README.md)
and [`doclet-vlm-adapter`'s README](../services/doclet/vlm-adapter/README.md)
for the full writeup.

1. Added the generic `llama_cpp` MLServer runtime (`cerebrate-gguf`
   model) following the existing adapter pattern — verified it genuinely
   drives `cerebrate-supervisor`'s `START`/`STOP` (real new Android
   process, not just an MLServer-side success report) and returns the
   same byte-identical DocTags result proven at every earlier layer,
   ~102.5s.
2. Built `doclet-vlm-adapter` — but first caught a real design conflict
   before building it: the original plan named this adapter
   `inference.home.arpa`, which is already live production DNS
   (`hosts/dns-rewrites.yaml`, `services/caddy/Caddyfile`) routing
   straight to MLServer's own V2 protocol. Corrected to
   `doclet-vlm-adapter`, an internal-only service with no new public
   hostname or Caddy route, calling the *existing* `inference.home.arpa`
   endpoint as an ordinary HTTP client instead.
3. A hand-built request matching Docling's exact wire shape (verified
   against `docling/utils/api_image_request.py`'s real source) round-
   tripped correctly through the full stack via this adapter, 104.1s,
   schema-valid `OpenAiApiResponse`.
4. A genuine Docling Serve conversion job (not a hand-built mimic),
   `picture_description_api` pointed at the real adapter, was attempted
   and did **not** complete — see below. The adapter/MLServer/Android
   chain was never implicated; a hand-built request proved that chain
   correct independently (step 3).

Also found along the way: a long-lived MLServer↔`cerebrate-gguf`
connection dropped once mid-sequence (confirmed not a stale-address
problem), correctly reflected as `ready=False` per this project's
existing Phase B Stage 3 pattern, recovered by an explicit MLServer
reload. Not a new bug — the adapter behaved exactly as designed.

**Real finding, confirmed via kernel log, not inferred:** the genuine
Docling Serve process was OOM-killed by the Linux kernel on overmind-01
partway through the real conversion job:

```text
Out of memory: Killed process 802373 (docling-serve) total-vm:6235536kB, anon-rss:2314808kB, ...
```

`docling-serve` itself grew to ~2.3GB RSS running the standard pipeline;
the host had ~5.5GB of its 7.6GB total already committed to other
production services (Jellyfin, Transmission, etc.), and overmind-01 has
**zero swap configured** — a risk flagged as far back as
[experiments/docling](../experiments/docling/README.md)'s environmental
findings but never previously observed to actually trigger a kill. It
did here, for the first time. This is a real constraint on the genuine
process sharing this specific host, not a defect in anything built in
Stage 3 — carried forward into Stage 4 below rather than solved here.

### Stage 4 — Full deployment and end-to-end validation (memory work + real container deployment done)

1. **Deployed and publicly exposed.** `services/doclet/compose.yaml` runs
   on overmind-01 as real Docker containers (`doclet`, `doclet-vlm-adapter`),
   added to [services/compose.yaml](../services/compose.yaml)'s include
   list (sharing Caddy's network, not a standalone project), a Caddy
   route added (`http://doclet.home.arpa -> doclet:5001`), and a real
   `doclet.home.arpa` DNS rewrite applied via
   `scripts/sync-dns-rewrites --apply` — verified resolving and serving
   from a genuine external LAN client, not just from the host itself.
   See [services/doclet/README.md](../services/doclet/README.md). The
   optional Gradio UI (`DOCLING_SERVE_ENABLE_UI`) was tried and turned
   back off: it only exposes plain checkboxes, no field for a custom
   engine URL, so checking `do_picture_description` there would silently
   fall back to a local transformers VLM instead of Cerebrate — not
   useful for this project's actual pipeline.
2. **Stage 3's OOM finding addressed and verified, not just planned.**
   Before this could even run, found and fixed a real, separate hardware
   bug: the official image SIGILLs on this Pi 4's Cortex-A72
   (`LD_PRELOAD`-injected `mimalloc`, built for a newer ARM baseline —
   see `services/doclet/README.md` for the full root-cause trace, found
   via reading the image's own Containerfile, not guessed). Then,
   profiled real per-service memory on overmind-01 at the user's request
   before assuming a fix (no single pathological consumer found — see
   `services/doclet/vlm-adapter/README.md`), added a 4GB SSD-backed
   swapfile regardless (sound practice for an always-on, zero-swap box
   either way), and containerized `doclet` with `mem_limit: 4g` (raised
   from an initial 3g after a real run peaked at ~2.96GB). Verified
   together against a genuine, real conversion job with real Pixel
   enrichment: succeeded (correct DocTags output, 542s), `doclet` never
   `OOMKilled`, swap genuinely engaged (379MB), other production services
   stayed responsive throughout.
3. **Best-effort fallback verified.** With the Cerebrate backend
   unavailable (worker unloaded on purpose), a real conversion job with
   `do_picture_description=True` still completed successfully
   (`task_status: success`, `errors: []`, full normal Docling content
   present) in the same time as the no-enrichment baseline — confirming
   `abort_on_error`'s default (`false`) already gives the desired
   behavior with zero extra config. One nuance worth flagging: there is
   no user-facing warning in the API response itself when this happens —
   the failure is visible only in Docling Serve's own internal log, not
   surfaced to the caller.
4. The genuine end-to-end run against the real research PDF is now
   done (item 2 above) — same PDF, real `do_picture_description`, real
   Pixel hardware. Direct runtime/output comparison against the
   `experiments/docling` baseline specifically — deliberately not pursued
   further: the goal is a usable production endpoint, not a benchmark
   against the earlier one-off experiment.
5. **Formula routing confirmed and working (2026-09-18)** — corrected
   from the earlier, wrong "unify under `do_picture_description`" plan.
   Real end-to-end test: `do_formula_enrichment=True` with
   `code_formula_custom_config` (`engine_type: api`, pointed at
   `doclet-vlm-adapter`) produced correct LaTeX for 9/9 real formulas in
   this project's test paper. Required one additional env var found
   empirically: `DOCLING_SERVE_ALLOW_CUSTOM_CODE_FORMULA_CONFIG=true`
   (now set in `services/doclet/compose.yaml`). See "What changed from
   V2" for the full corrected finding.
6. **A real 29-minute, 14-item production run surfaced and fixed three
   more real bugs** (see
   [experiments/doclet-service/production-run-2026-09-18](../experiments/doclet-service/production-run-2026-09-18/)
   for the actual output, and
   [cerebrate-gguf's](../hosts/cerebrate-pixel6/cerebrate-gguf/README.md)
   and
   [its MLServer adapter's](../hosts/cerebrate-pixel6/mlserver/models/cerebrate-gguf/README.md)
   READMEs for the full writeups):
   - Most enrichment came back empty in that run: 5/9 formulas and 0/5
     pictures. Root cause: a transient connection timeout early in the
     job latched `self.ready = False`, and MLServer's own REST layer
     refused every request after that point with "Model not ready" —
     one blip killed everything downstream of it. **Fixed** by
     separating LOADED (supervisor-managed, only touched by real
     load/unload) from CONNECTED (transient, per-request) — a timeout or
     dropped socket now invalidates only that one connection/item, never
     the model's readiness, and the next request reconnects lazily with
     no `/load` call needed. Verified with two real scenarios: an
     organically-occurring idle-timeout disconnect, and a deliberate
     `kill -9` on the worker mid-request.
   - `REQUEST_TIMEOUT_S` raised 240s → 600s (real formula calls
     genuinely exceeded 240s) — see the MLServer adapter README's
     timeout-layering note for how this propagates through
     `doclet-vlm-adapter` (630s) and the recommended Docling-side job
     timeout (660s).
   - Two smaller, real bugs found and fixed along the way in
     `cerebrate-gguf.cc` itself: (a) the classic fork/exec fd-leak
     (`cerebrate-supervisor.cc`'s own documented pitfall, reintroduced in
     a second fork/exec path) — every spawned `llama-mtmd-cli` held a
     duplicate of the listening socket, so a killed worker's orphaned
     CLI child kept the port bound and blocked a fresh `START`; (b) the
     text-only request path (claimed supported since Stage 2, never
     actually exercised until this run) never passed `--mmproj`, which
     `llama-mtmd-cli` requires unconditionally.
   - Separately, the garbled one-character-per-line sections visible in
     the production run's markdown output are a **Docling base-pipeline
     limitation**, not a bug in anything built here: inline math mixed
     into body prose gets fragmented by the layout/reading-order model
     before any enrichment ever runs, and a couple of picture crops in
     that output are literally small mis-classified slices of that same
     inline math (confirmed via their tiny bounding boxes and the
     absence of any enrichment annotation — they were below the area
     threshold and correctly skipped, not mangled by us). No fix
     available at this layer.
7. **Re-ran the same real job after the fixes, with the Docling-level
   job timeout raised to 660s to match — full success.** 9/9 formulas
   and 3/3 real pictures got content this time (versus 5/9 and 0/5
   before the fix), 1343s total. Found one more real issue in the
   process: one formula's output had the correct LaTeX prefix followed
   by ~1900 repetitions of a trivial 2-character unit padding out to the
   token cap — the same deterministic-greedy-decoding repetition-loop
   failure already documented for `cerebrate-generate`'s SmolLM2. Fixed
   with a conservative degenerate-suffix detector/trimmer in
   `doclet-vlm-adapter` (not Docling, not `cerebrate-gguf` — this is a
   generic generative-runtime pathology now seen on more than one model
   path, so it belongs in the one layer that already owns response
   shaping): detects a long exact-repeating short suffix with a
   substantial real prefix before it, trims it, logs the occurrence, and
   reports `finish_reason: "length"` instead of silently claiming
   ordinary success. See
   [services/doclet/vlm-adapter/README.md](../services/doclet/vlm-adapter/README.md)
   and its `test/test_degenerate_suffix.py` (using the real malformed
   output as its regression fixture) for the full writeup. Deliberately
   not pursued yet: a single retry on detection, or decoding-parameter
   changes — the recovered prefix was already correct, so retrying would
   only add latency for no clear benefit; worth revisiting only if this
   turns out to recur often in practice.

## Non-Goals

For this implementation:

- no custom Docling enrichment plugin (superseded — `do_picture_description`
  and `do_formula_enrichment` cover this between them);
- no custom Doclet REST API;
- no full-page VLM conversion by default;
- no Granite ONNX/NNAPI work;
- no LiteRT-LM multimodal workaround;
- no Vulkan work;
- no `docling.rs` migration;
- no debugging the upstream Granite `llama-server` defect;
- no larger Substrate ingestion/indexing pipeline yet.

## Success Criteria

`doclet.home.arpa` provides a reliable Docling Serve API that converts
real documents to useful Markdown/JSON and can selectively enrich
difficult visual elements — including figures, charts, and
formulas/equations — through a managed Pixel-hosted Granite model, using
`do_picture_description` as the single enrichment surface.

The implementation also establishes `llama.cpp` as a reusable Cerebrate
backend for future GGUF-compatible models without creating a parallel
model-serving architecture.
