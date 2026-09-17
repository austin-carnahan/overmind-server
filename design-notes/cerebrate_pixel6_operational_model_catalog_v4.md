# Cerebrate Pixel 6 — Operational Model Catalog and Runtime Management

**Status:** Proposed next phase
**Date:** 2026-09-17
**System:** Overmind / Cerebrate Pixel 6
**Supersedes:** `cerebrate_pixel6_operational_model_catalog_v3.md`
**Revision from v3:** Four changes made after a review surfaced places where v3 assumed capability the implementation doesn't have. (1) Replaced MLflow Model Registry with a Git-tracked YAML catalog + JSON Schema — disproportionate operational weight (a database-backed service, migrations, backup story) for six-ish models; MLflow becomes a later promotion path if research experiments, multi-node lineage, or many model-producing workflows ever justify it. (2) Defined session-model (and, generalized, any dynamically-loadable) lifecycle as **process** lifecycle, not in-process model swapping — `cerebrate-generate` was never built to unload one model and load another; load/unload means start/stop the worker process. (3) Demoted "ORT reaches Android hardware acceleration" from an assumption to an explicitly high-risk, separately-gated hypothesis — real ONNX Runtime GitHub reports show NNAPI failing to reach `google-edgetpu` on multiple Pixel devices, and NNAPI itself is a deprecated API with an unsettled successor story. (4) Named ADB push as the explicit, boring staging transport instead of an unspecified "bridge," and simplified residency management to: stage every approved model persistently (flash is cheap relative to model sizes here), manage only RAM residency dynamically. Normal operation exercises only `STAGED ↔ LOADED ↔ READY`, not repeated cache-to-Pixel transfers.

## 1. Purpose

The Multi-Runtime Execution Plane is complete: Cerebrate can serve bounded graph inference through the existing TensorFlow Lite + NNAPI worker and stateful/streaming generation through LiteRT-LM. The next phase turns that proven execution substrate into a useful, operational inference appliance — without quietly turning "finish the Pixel inference appliance" into "build a model-management platform."

This phase has five goals:

1. Define and validate a small initial capability catalog: general language, coding/admin assistance, document vision/OCR enrichment, speech-to-text, text-guided segmentation, and robust image classification.
2. Treat **ONNX Runtime (ORT)** as the preferred candidate execution substrate for new bounded graph workloads because it provides a portable model format plus pluggable execution providers such as CPU, XNNPACK, and NNAPI on Android — while treating whether ORT actually reaches Android hardware acceleration on this device as a **separate, unproven hypothesis**, not something the portability argument implies.
3. Preserve specialized paths where they are empirically justified: the existing TFLite + NNAPI path remains the proven Pixel 6 TPU path; LiteRT-LM remains the proven stateful/streaming session runtime; LiteRT `CompiledModel` remains a future graph backend until its GPU correctness defect is resolved.
4. Deploy **Docling** on Overmind as the first operational ingestion component designed according to Substrate conventions — dogfooding the canonical-source/derived-artifact pattern on one real project, without requiring a larger "Substrate" system to already exist.
5. Introduce a deliberately small, mostly off-the-shelf model catalog and residency-management approach — a Git-tracked catalog, the standard Hugging Face cache, ADB-based staging, and process-level load/unload — so Cerebrate can keep several approved models staged without pretending it needs a fleet-scale model platform yet.

The guiding rules remain:

- **Compose established tools; write only the missing glue.**
- **Model identity is separate from deployment artifact and execution backend.**
- **Prefer the most portable/default execution path first, then retain specialized paths only where measured behavior justifies them.**
- **Don't build for a scale this system doesn't have yet.**

## 2. Current baseline

### 2.1 Production execution paths today

```text
inference.home.arpa
        |
      Caddy
        |
     MLServer
        |
   +----+-----------------------+
   |                            |
Graph execution             Session execution
   |                            |
cerebrate-infer            cerebrate-generate
   |                            |
TFLite + NNAPI               LiteRT-LM
   |                            |
google-edgetpu             streamed generation
   |
Tensor G1 TPU
```

The production graph backend is currently the Pixel-6-specific TFLite + NNAPI path because it is correct and reaches `google-edgetpu` on Tensor G1.

The production session backend is LiteRT-LM because it already provides working stateful generation and genuine incremental streaming through the complete Cerebrate service path.

LiteRT `CompiledModel` remains **unimplemented as a production backend**. CPU execution is correct. GPU delegation genuinely engages, but both the C++ and plain-C integrations return an all-zero output buffer on the tested Pixel 6 stack — the readback path, not the delegate itself, is broken. The GPU path is therefore treated as incorrect until a future LiteRT release passes the existing correctness harness (`hosts/cerebrate-pixel6/spikes/litert-compiled-correctness/`).

Both `cerebrate-infer` and `cerebrate-generate` today are **fixed at process startup**: one binary, one model, one backend, chosen by command-line argument when the process is launched. Neither supports loading a different model into an already-running process. This matters directly for Section 8 below.

### 2.2 The direction of travel

The system should no longer think of these runtimes as peers that every model must understand. The durable hierarchy is:

```text
                 CAPABILITY LAYER
      classify / segment / transcribe /
      generate / embed / document-vision
                         |
                         v
                  MODEL CATALOG
       identity / versions / artifacts /
       validation / backend preferences
                         |
                         v
                   SERVING LAYER
                      MLServer
                         |
                         v
                EXECUTION CONTRACT
              +----------+----------+
              |                     |
            Graph                 Session
              |                     |
      +-------+---------+       +---+----------------+
      |                 |       |                    |
 ONNX Runtime      TFLite+NNAPI LiteRT-LM       ORT GenAI
 preferred new       proven      production       future /
 graph candidate   Pixel 6 TPU   today            experimental
      |
      +-- CPU
      +-- XNNPACK
      +-- NNAPI (unproven on this hardware -- see Section 3.1)
            |
            +-- device accelerator(s), if reachable

Future graph candidate:
LiteRT CompiledModel
  -> enable only when a tested device/release is correct and useful
```

The important architectural rule is that **ONNX Runtime is not a layer above LiteRT, TFLite, or LiteRT-LM**. It is another execution engine. The layer above all of them is the runtime-neutral capability/catalog/serving layer.

## 3. Preferred execution policy

### 3.1 ONNX Runtime: two separate hypotheses, not one

For new bounded graph models, the first path to evaluate should generally be:

```text
source framework
(PyTorch / TensorFlow / other)
        |
        v
      ONNX
        |
        v
  ONNX Runtime
        |
   +----+----------+
   |               |
 CPU/XNNPACK     NNAPI (unproven here)
                    |
             Android accelerator(s)?
```

This is compelling because ONNX Runtime provides:

- a common exported graph format for models originating in multiple training frameworks;
- a stable inference-session abstraction;
- prebuilt Android support;
- CPU and XNNPACK execution providers;
- an Android NNAPI execution provider, in principle;
- heterogeneous graph partitioning when one execution provider cannot run an entire graph;
- increasing execution-provider modularity through plugin EP libraries;
- overlap with the proposed Gather mobile runtime, improving the chance that one exported model can be reused across Gather, Cerebrate, and future Linux/edge nodes.

**But that value case is entirely about portability and a dependable CPU/XNNPACK baseline. It is not evidence that ORT reaches hardware acceleration on this specific device.** Treat these as two separate, independently-gated claims:

1. **ORT is a good portable graph-runtime candidate, with CPU/XNNPACK as a dependable baseline.** High confidence — this is well-established, widely-used functionality. **Measured (Phase C Stage 1, `hosts/cerebrate-pixel6/spikes/onnxruntime-characterization/`):** CPU passes cleanly on this device against the exact MobileNet v1 1.0 224 quantized canary used everywhere else in this project (converted to ONNX via `tf2onnx`, not a different model). XNNPACK crashes — a real, reproducible defect inside ONNX Runtime's own code (ORT 1.30.0), not a usage bug; CPU alone still satisfies this claim.
2. **ORT's NNAPI execution provider reaches `google-edgetpu` (or any real accelerator) on this Pixel 6.** Low confidence going in. Real, verified ONNX Runtime GitHub reports show NNAPI failing to reach `google-edgetpu` on Pixel 6a and Pixel 8 Pro (microsoft/onnxruntime#20782, "NNAPI doesn't work on google-edgetpu [Mobile]"), and NNAPI itself is a deprecated Android API with no settled generic successor for hardware acceleration (see e.g. microsoft/onnxruntime#23565, where a user explicitly asks how to future-proof away from NNAPI). These reports predate this exact release and don't prove today's behavior, but there's no found evidence the underlying gap has been fixed either. Go into Section 6's characterization expecting NNAPI→TPU may simply fail here, the same way LiteRT `CompiledModel`'s GPU path turned out to have a real defect. **Measured (Phase C Stage 2): the low-confidence expectation did not hold for this device.** With `NNAPI_FLAG_CPU_DISABLED` set (so a silent CPU fallback cannot masquerade as acceleration), NNAPI genuinely reached `google-edgetpu` — confirmed via real `adb logcat` delegation evidence (TPU device discovery, 146/149 graph nodes partitioned to NNAPI, Darwinn compiler invocations completing successfully on `google-edgetpu`), not just a passing `Run()` call — with bit-exact correct output against the CPU reference. This doesn't invalidate the cited GitHub reports; it means their failure mode doesn't reproduce here, now, for this exact device/model/ORT version. Recorded as what was measured, not generalized to every future model or device.

This is a **preference policy for portability, not a claim that ORT already accelerates well on this Pixel** — that claim is now independently measured and confirmed for this specific characterization workload (Section 6.3 records the resulting promotion decision). Every *other* backend/model combination remains correctness- and measurement-gated on its own; "ORT is the default candidate" and "ORT reaches Tensor G1 acceleration for MobileNet v1" must still not be conflated with "ORT accelerates every future model" when reporting results.

### 3.2 Specialized graph path: TFLite + NNAPI

The current TFLite + NNAPI path remains first-class because it is the only graph backend already proven to reach Tensor G1's `google-edgetpu` correctly and efficiently.

For the Pixel 6, it should remain available when:

- an ONNX export cannot be executed correctly through ORT;
- ORT/NNAPI fails to reach useful hardware acceleration (the default expectation per 3.1, not an edge case);
- ORT partitions the graph in a way that materially hurts performance;
- the TFLite/NNAPI path is measurably faster or more power-efficient;
- a model is distributed only or most naturally as `.tflite`.

The goal is not to retire this path for conceptual cleanliness. The goal is to stop making it the default assumption for every future graph workload, without pretending its replacement is already proven.

### 3.3 Future graph path: LiteRT `CompiledModel`

LiteRT `CompiledModel` is retained as a **future backend candidate**, not an operational lane on this Pixel 6 today.

Current evidence:

```text
LiteRT CompiledModel
CPU       -> correct
GPU       -> 31/31 nodes genuinely delegated, output readback is all zeros (confirmed
             identically on both the C++ SDK and plain-C API integrations)
NPU       -> unavailable on Tensor G1 through the tested modern path
```

The existing correctness harness (`hosts/cerebrate-pixel6/spikes/litert-compiled-correctness/`) should be rerun whenever a materially newer LiteRT release or new Android/Tensor device is evaluated. Reading its `checksum`/`gpu_output_all_zero` output is enough to answer whether anything changed — only then should `LiteRtCompiledBackend` be implemented or promoted.

### 3.4 Session execution remains separate

Stateful/autoregressive generation is a different execution contract from bounded graph inference. Today:

```text
.litertlm
   |
LiteRT-LM
   |
stateful session / tokenizer / prefill / decode / KV state / streaming
```

is the proven production path.

ONNX Runtime also has a higher-level **Generate API / ONNX Runtime GenAI** layer that adds tokenization, generation loops, sampling, logits processing, chat templates, structured output, and KV-cache management. It is strategically interesting because it could eventually provide an ONNX-native session path, but the API is currently documented as preview. It should therefore be tracked as a future candidate rather than used to replace the working LiteRT-LM path for architectural symmetry.

## 4. Model identity, artifacts, and backend choice

A model should not be defined by one deployment format.

The catalog should represent a logical model/capability separately from one or more executable artifacts:

```yaml
model: mobile-sam
capabilities:
  - segmentation

artifacts:
  onnx:
    source: <pinned artifact>
    validated:
      gather-android: true
      pixel6-ort-nnapi: pending

  tflite:
    source: <pinned artifact>
    validated:
      pixel6-tflite-nnapi: false

execution_preferences:
  pixel6:
    - onnxruntime_nnapi
    - onnxruntime_xnnpack
    - tflite_nnapi

  gather:
    - onnxruntime_nnapi
    - onnxruntime_xnnpack
```

Likewise, a generative model may have multiple deployment forms:

```yaml
model: qwen3-0.6b
capabilities:
  - generate
  - chat

artifacts:
  litertlm:
    validated:
      pixel6-litertlm: true

  onnx:
    validated:
      ort-genai: experimental
```

This lets the service contract stay stable even as the preferred runtime changes by device generation, model export, or software release. This YAML shape is deliberately close to what Section 7.2 proposes as the actual catalog file format — not a separate conceptual model that needs translating later.

## 5. Initial capability catalog

The catalog should identify **capabilities first, model implementations second**. Callers should eventually request a stable capability such as `document-vision`, `transcribe`, or `segment-text`, while the catalog maps that capability to a validated model/version/runtime for this node.

| Capability | Initial candidates | Preferred candidate runtime | Specialized / fallback path |
| --- | --- | --- | --- |
| General language | Qwen3-0.6B INT4; Qwen2.5-1.5B-Instruct comparison | LiteRT-LM today; track ORT GenAI | — |
| Coding / server administration | Qwen2.5-Coder-1.5B-Instruct INT4 | LiteRT-LM today; track ORT GenAI | — |
| Document vision / OCR enrichment | PaddleOCR-VL-1.6; SmolVLM2-500M | LiteRT-LM today | future ONNX/VLM artifacts where useful |
| Speech-to-text | Whisper tiny.en; Whisper base; SenseVoice; streaming Zipformer | **ONNX Runtime / sherpa-onnx**, CPU/XNNPACK baseline; NNAPI unproven | CPU/XNNPACK is the expected steady state, not just a fallback |
| Text-guided segmentation | EdgeSAM + grounder; MobileSAM + grounder; FastSAM + CLIP | **ONNX Runtime**, CPU/XNNPACK baseline; NNAPI unproven | alternate model-specific runtime if required |
| Point / box segmentation | EdgeSAM; MobileSAM; MagicTouch | **ONNX Runtime** where ONNX artifact exists | MediaPipe / model-specific runtime |
| Generic image classification | Existing MobileNetV1; ONNX MobileNet control | **ONNX Runtime for new work** (CPU/XNNPACK baseline) | TFLite + NNAPI remains the proven Pixel 6 TPU path |
| Embeddings / feature extraction | candidate TBD | **ONNX Runtime** | model-specific exception if measured better |
| Detection / pose / depth | candidates TBD | **ONNX Runtime** | model-specific exception if needed |

### 5.1 General language

**Qwen3-0.6B** is the first general-purpose candidate because ready-to-run LiteRT-LM artifacts exist at phone-class sizes, including INT4 variants. It should be tested for latency, memory, tool-format behavior, and practical usefulness rather than treated as a replacement for frontier hosted models. Initial residency is **ON_DEMAND**, not PINNED — see Section 9 — precisely because memory cost hasn't been measured yet, which also means Cerebrate does not need to support Qwen3 and Qwen2.5-Coder resident simultaneously in this phase (see Section 8).

**Qwen2.5-1.5B-Instruct** is a useful larger comparison if the Pixel has enough practical memory headroom and decode performance remains acceptable.

These remain LiteRT-LM workloads today because that path is already operational. ORT GenAI should be watched as a possible future session backend, not forced into this phase.

### 5.2 Coding / administration

**Qwen2.5-Coder-1.5B-Instruct INT4** is the first coding candidate. The target is not autonomous infrastructure administration. The target is bounded local assistance: inspect configuration, propose a patch, explain a service failure, draft shell/systemd changes, or prepare a change for Kerrigan or a stronger external agent to review.

### 5.3 Document ingestion, normalization, and model-backed enrichment

**Docling** is the preferred document-ingestion layer for this project's Substrate-aligned work. It is not a Pixel model and should not be folded into the Android execution plane. It runs on Overmind, standalone, as the first ingestion component built according to Substrate conventions — not as evidence that a larger "Substrate" system is already online (see Section 7 of the Purpose and Phase C below).

Docling accepts a broad set of inputs including PDF, modern and legacy Office files, OpenDocument, EPUB, Apple Pages, Markdown, AsciiDoc, LaTeX, HTML/MHTML, CSV, images, audio, video, email, WebVTT, JATS XML, XBRL XML, USPTO XML, AFP, EBCDIC, and Docling-native formats. These inputs are normalized into the unified **`DoclingDocument`** representation.

`DoclingDocument` preserves structure that Markdown alone cannot faithfully encode: document hierarchy, tables, pictures, headers/footers, layout bounding boxes, provenance, and table span information. It can then be projected into Markdown for human/agent reading, serialized losslessly to JSON, emitted as HTML/DocLang/LaTeX/text, or chunked for downstream RAG/indexing workflows.

This aligns directly with the canonical-source/derived-artifact principle underlying Substrate — the original artifact remains canonical while derived representations are rebuildable — demonstrated here on one real project rather than requiring the full Substrate system to exist first:

```text
canonical input
(PDF / DOCX / PPTX / JATS / LaTeX / image / audio / ...)
        |
        v
      Docling
        |
        v
  DoclingDocument
        |
   +----+---------+-----------+------------+
   |              |           |            |
Markdown        JSON       figures/      chunks /
projection   lossless      tables       metadata
             structure
```

Cerebrate participates **below this layer** when a model-backed operation adds value. Likely uses include OCR on difficult/scanned content, figure and diagram understanding, visual question answering, or specialist document parsing.

**PaddleOCR-VL-1.6** remains the first specialist model candidate for document-oriented enrichment. **SmolVLM2-500M** remains the lighter fallback and a useful general visual-understanding service if the specialist model is too slow or memory-heavy.

The preferred relationship is:

```text
Docling on Overmind
     |
     +-- native parsing / OCR / structure where sufficient
     |
     +-- Cerebrate vision capability when model enrichment is useful
             |
             +-- PaddleOCR-VL
             +-- SmolVLM / future VLM
```

MarkItDown remains a useful lightweight/general converter and compatibility tool where its Markdown-first interface is independently useful, but it is not the proposed normalization layer.

### 5.4 Speech-to-text

Speech is a candidate initial production workload for the ONNX lane, with the same caveat as everywhere else in this document: CPU/XNNPACK is the expected steady state, and NNAPI acceleration is a bonus to validate, not assume.

`sherpa-onnx` sits above ONNX Runtime and provides speech-specific machinery such as offline/streaming ASR, model loading, decoding, VAD-related workflows, and Android support. Candidate models include Whisper, SenseVoice, and streaming Zipformer variants.

The preferred sequence is:

```text
speech model artifact
      |
    ONNX
      |
 sherpa-onnx
      |
ONNX Runtime
  +---+---------+
  |             |
XNNPACK        NNAPI (unproven)
```

The runtime decision should be made after the ORT characterization gate in Section 6, not assumed in advance.

### 5.5 Text-guided segmentation

The initial service should prioritize **text input** rather than point-only segmentation:

```text
image + "the red backpack" -> mask
```

Mobile SAM variants are attractive because they are edge-oriented and several have ONNX export paths, but MobileSAM, EdgeSAM, and similar SAM-family models are fundamentally point/box-prompted. Text guidance therefore requires an additional semantic grounding stage.

Three candidate compositions are worth testing:

- **EdgeSAM + grounder** — strong on-device SAM candidate with separate ONNX encoder/decoder artifacts.
- **MobileSAM + grounder** — mature lightweight SAM variant and useful comparison.
- **FastSAM + CLIP** — text prompting provided compositionally by generating/selecting masks using CLIP-style text/image matching.

MagicTouch remains a useful fallback for point/stroke interaction, but it is not the first service because it does not solve the desired language-grounded segmentation contract.

## 6. ONNX Runtime characterization and promotion gate

### 6.1 Why characterize before standardizing

ONNX Runtime's Android mobile guidance explicitly treats CPU/XNNPACK as the simplest consistent starting points and NNAPI as a device- and model-specific accelerator path. That matches Cerebrate's empirical engineering style: start from correctness, then promote the accelerator only after measurement — and per Section 3.1, go in expecting the accelerator path may simply not work on this device, the same way LiteRT `CompiledModel`'s GPU path did not.

### 6.2 Initial characterization workload

Do **not** begin with Whisper or segmentation. First use a known classification model so correctness and performance are easy to compare, and so a negative NNAPI result is cheap to diagnose against the already-known-good MobileNet baseline from every other backend in this project.

```text
MobileNet ONNX
   |
   +-- ORT CPU / XNNPACK -> correctness + timing
   |
   +-- ORT NNAPI        -> correctness + timing + delegation evidence
```

Acceptance criteria:

- Known deterministic input produces the expected output (class 795, matching every other backend in this project).
- NNAPI is explicitly enabled.
- CPU fallback through NNAPI (`NNAPI_FLAG_CPU_DISABLED` or equivalent) is disabled for the characterization run, so an "accelerated" result cannot simply be NNAPI's own reference CPU execution.
- Logs/profiling show what was delegated versus retained by ORT, and to which accelerator (matching the discipline that caught LiteRT `CompiledModel`'s GPU readback bug — verify actual placement and actual output, don't just trust that creation/`Run()` succeeded).
- Latency, resident memory, and thermal behavior are recorded.
- No backend is promoted merely because it initializes successfully; correctness is mandatory, and a garbage-but-non-crashing result is exactly the failure mode to watch for.

### 6.3 Promotion rule

If ORT passes correctness and reaches useful acceleration on this Pixel, it becomes the **first backend attempted for new graph models**.

If ORT is correct on CPU/XNNPACK but NNAPI does not reach real acceleration (the expected-going-in outcome per Section 3.1), ORT is still promoted as the **default portable candidate at the CPU/XNNPACK tier** — the portability and format-unification value doesn't depend on hardware acceleration succeeding. It simply means TFLite+NNAPI stays the only accelerated Pixel 6 graph path, and that gap gets recorded honestly rather than glossed over.

**Measured outcome (Phase C, MobileNet v1 1.0 224 quantized characterization workload):** the first branch applies. NNAPI genuinely reached `google-edgetpu`, correctness passed, and delegation was independently confirmed via real logcat evidence, not just a passing `Run()`. ORT is promoted as the first backend attempted for new graph models on this Pixel 6 — the stronger outcome, not just the CPU/XNNPACK-tier fallback. This is recorded for *this* characterization workload; it is not automatically extended to every future model without its own correctness/delegation check (Section 6.2's discipline applies per model, not just once).

Neither outcome automatically makes ORT the fastest backend for every model. TFLite+NNAPI is not retired: it remains the only *already-in-production* accelerated Pixel 6 graph path (served by `cerebrate-infer`, per the Multi-Runtime Execution Plane), and Section 3.2's conditions for preferring it still apply case-by-case — no ORT-based worker exists yet, so this promotion is a policy decision for future graph models, not a retroactive change to `mobilenetv1`'s live `cerebrate-infer` configuration.

Backend preference should be recorded per model and device, for example:

```text
Pixel 6 / MobileNetV1
1. TFLite + NNAPI / google-edgetpu    # already in production, materially faster to load (no NNAPI/Darwinn compile step)
2. ORT + NNAPI / google-edgetpu       # measured correct and accelerated (Phase C) -- viable once an ORT-based worker exists
3. ORT + XNNPACK                      # measured broken for this model (Phase C): crashes inside ORT 1.30.0 itself

Pixel 6 / EdgeSAM
1. ORT + NNAPI                        # if validated
2. ORT + XNNPACK
3. model-specific fallback

Future Android device
1. ORT + NNAPI / other EP
2. LiteRT CompiledModel               # only if validated
3. model-specific compatibility path
```

The catalog, not hard-coded worker logic, should own this preference information.

## 7. Catalog, storage, staging, and residency

The system should distinguish four different questions:

1. **What logical models/capabilities are approved and why?**
2. **Which executable artifacts exist for each model?**
3. **Where are the immutable model bytes stored and which artifacts are staged on this Pixel?**
4. **Which models/backends are currently resident and ready for inference?**

No single new custom service should own all four — and, per the revision at the top of this document, none of these four needs a new database-backed service at all at today's scale.

### 7.1 Proposed tool composition

```text
                Git-tracked catalog.yaml
       logical identity / versions / artifacts /
       validation status / per-device preferences
                          |
                          v
              Hugging Face cache on Overmind
              immutable / revision-pinned bytes
                          |
                     adb push (explicit,
                     operator/deployment action)
                          |
                          v
                 Pixel local model storage
              all approved artifacts staged persistently
                          |
                          v
            MLServer Model Repository API
           load = start worker process with this model
           unload = stop that worker process
                          |
              +-----------+-----------+
              |                       |
      Android graph workers     Android session workers
   ORT / TFLite / future LiteRT      LiteRT-LM / future ORT GenAI
   (one process = one model)      (one process = one model)
```

### 7.2 Git/YAML: approved catalog and provenance

Use a **Git-tracked YAML catalog**, not a new service, as the human/agent-facing source of truth:

```text
models/
├── catalog.yaml
└── schema.json
```

`catalog.yaml` represents everything Section 4 described directly, with no translation layer:

```yaml
models:
  qwen3-0.6b:
    capability: chat
    artifacts:
      litertlm:
        source: <repo>
        revision: <pinned commit/tag>
    validation:
      pixel6:
        litert_lm: passed
    residency: on_demand
    requirements:
      disk_mb: <measured>
      ram_mb: <measured>
```

`schema.json` gives this real validation (a malformed catalog entry fails CI/a pre-commit check, the same way this repo already treats other config as code). Git gives provenance, diffs, rollback, and review for free — the same properties `dns-rewrites.yaml` and this project's other declarative config already rely on, extended to models.

The registry should record **measured device/backend compatibility**, not merely theoretical framework compatibility — `pixel6-ort-nnapi: pending` stays `pending` until an actual characterization run sets it to `passed` or `failed`, never assumed.

**MLflow remains a real future option**, not a rejected one: if this system later has genuine research experiments, trained model versions with real metrics/lineage, multiple model-producing workflows, or multiple compute nodes needing a shared registry, promoting from this YAML vocabulary to MLflow should be straightforward, since the fields above map directly onto MLflow's own model/version/tag/alias concepts. Don't build that promotion path now; do keep the YAML vocabulary compatible with it.

### 7.3 Hugging Face cache: local artifact warehouse

Use the standard Hugging Face cache on an Overmind SSD as the canonical re-downloadable model cache. It already maintains content-addressed blobs, immutable revision snapshots, and human-readable refs while avoiding duplicate storage for unchanged files.

Production models should be pinned to a commit/revision rather than implicitly tracking `main`.

This is a cache, not irreplaceable canonical data; backup policy can therefore treat it differently from project state or catalog metadata (the catalog itself, being Git-tracked, is already covered by normal repo backup/replication).

### 7.4 Pixel staging: ADB push, explicit and boring

The only actual transport available today is ADB — say so directly rather than describing an abstract "staging bridge." A small script takes a catalog entry, verifies the pinned revision/checksum against the Hugging Face cache, `adb push`es the artifact to a fixed path (e.g. `/data/local/tmp/cerebrate/models/...`), verifies the remote checksum, and atomically promotes it into the expected path.

This is explicitly **not** framed as an unattended production transport. The legacy TCP ADB listener does not survive an Android reboot (established during the Ethernet migration investigation) — model staging is an operator/deployment action, performed when a model is approved, not something required during every inference request.

Given that, and given this project has a handful of approved models whose aggregate size is small relative to available flash, the simplification is: **stage every approved model persistently on the Pixel, and manage only RAM residency dynamically.**

```text
HF cache            Pixel storage          RAM/runtime
   CACHED ──adb push──>  STAGED ──start──>      LOADED
                                              ↓
                                             READY
```

Normal operation exercises only:

```text
STAGED ↔ LOADED ↔ READY
```

not repeated cache-to-Pixel transfers. `CACHED → STAGED` (and the reverse) happens rarely, as an explicit operator action when a model is newly approved or deliberately retired from the device.

If genuinely dynamic remote staging becomes useful later (e.g. an Android-side supervisor pulling an authenticated, checksummed artifact from Overmind on demand, replacing ADB), that is a **separate future feature**, not something to build into this phase.

### 7.5 MLServer: residency control plane, backed by process lifecycle

MLServer already supports a Triton-compatible **Model Repository API** for dynamically listing, loading, and unloading models. Use this for service residency rather than inventing a Cerebrate-specific model lifecycle API.

Per Section 8 below, our custom runtimes' `load()`/`unload()` hooks orchestrate an **external Android worker process's** lifecycle, not in-process model state: `load()` starts a worker (`cerebrate-infer`, `cerebrate-generate`, or a future ORT worker) with the requested model and waits for it to report ready; `unload()` stops that process. MLServer explicitly leaves custom runtimes responsible for actually acquiring and freeing their underlying resources — this is exactly that responsibility, discharged by process start/stop rather than by teaching any worker to swap models internally.

MLServer remains the serving seam even when different models are implemented by ORT, TFLite/NNAPI, LiteRT-LM, or a future backend.

## 8. Model lifecycle states

Use explicit states instead of a single "installed" flag:

```text
REMOTE
  known in catalog; bytes not cached locally

CACHED
  pinned artifact available on Overmind storage

STAGED
  selected execution artifact copied to Pixel local storage
  (in normal operation, every approved model sits here persistently)

LOADED
  the corresponding Android worker process is running with this model
  (one worker process = one loaded model; see Section 7.5)

READY
  health/correctness probe passed and model can serve requests
```

Typical transitions:

```text
REMOTE -> CACHED -> STAGED -> LOADED -> READY

READY -> STAGED      # stop the worker process; Pixel artifact remains staged
STAGED -> CACHED     # rare: operator explicitly retires the artifact from the Pixel
CACHED -> REMOTE     # optional cache cleanup; artifact remains reproducible upstream
```

**`LOADED` means a worker process is running for this specific model — not that some shared runtime process swapped internal state.** If two models of the same runtime/lifecycle class (e.g. two LiteRT-LM session models) genuinely need to be resident at the same time, that means two separate worker processes on two separate ports, not one process managing two models. This phase does not require that: Qwen3-0.6B's residency is ON_DEMAND specifically so Cerebrate never needs Qwen3 and Qwen2.5-Coder resident simultaneously yet (see Section 9).

The `STAGED` and `LOADED` states should identify the chosen artifact/backend pair, not just the logical model name.

## 9. Residency policies

Start with only three policies, applied at the **worker-process** level (per Section 8, not in-process):

- **PINNED** — start the worker process at service startup and keep it resident.
- **ON_DEMAND** — start the worker process when explicitly requested or when a request requires it; stop it after an idle period.
- **MANUAL** — start/stop the worker process only by explicit operator action.

Do not build predictive loading, LRU scoring, popularity prediction, or a fleet scheduler in this phase.

Initial policy candidates:

| Model/capability | Initial policy |
| --- | --- |
| MobileNetV1 classifier | PINNED |
| Qwen3-0.6B | ON_DEMAND initially; consider PINNED only after measuring memory/idle cost |
| PaddleOCR-VL-1.6 | ON_DEMAND |
| SmolVLM2-500M | ON_DEMAND |
| Qwen2.5-Coder-1.5B | ON_DEMAND |
| Speech model | ON_DEMAND; revisit for always-listening use cases |
| Text-guided segmentation stack | ON_DEMAND |

Note that Qwen3-0.6B and Qwen2.5-Coder-1.5B are both ON_DEMAND, not PINNED — this phase does not need to support both resident at once, which is exactly what keeps the "one worker process per loaded model" design in Section 8 sufficient without needing multi-process orchestration for session models yet.

## 10. Public service contracts

Keep public APIs capability-oriented even if MLServer still exposes concrete model names underneath.

Target **Cerebrate inference capabilities**:

```text
classify-image
chat / generate
code-assist
document-vision
transcribe
segment-text
embed
```

Document ingestion itself is an **Overmind-side service**, not an Android model contract:

```text
ingest-document
  -> Docling
  -> DoclingDocument
  -> Markdown / JSON / figures / tables / chunks
  -> optional Cerebrate document-vision enrichment
```

MLServer V2 remains the node-level serving protocol. Thin Overmind adapters may expose protocol-specific compatibility surfaces when useful—for example, an OpenAI-compatible vision endpoint—but those adapters should terminate at Overmind and translate into stable Cerebrate capabilities.

The execution workers should not become coupled to Docling, MarkItDown, OpenAI API conventions, Kerrigan, or other callers.

## 11. Implementation sequence

### Phase A — Git/YAML catalog + HF cache + ADB staging

1. Create `models/catalog.yaml` and `models/schema.json` in this repo; define the logical-model, artifact, backend-validation, and per-device preference schema from Sections 4 and 7.2.
2. Establish the Hugging Face cache on Overmind storage and pin artifacts by revision.
3. Write the small ADB-push staging script (Section 7.4): verify pinned checksum, push, verify remote checksum, atomically promote.
4. Stage the existing MobileNet and SmolLM2 artifacts through this script as the first real exercise, even though they're already present on the device from earlier phases — prove the script reproduces the current state before trusting it for anything new.

### Phase B — Android worker process lifecycle through MLServer

1. Define the process-lifecycle contract every worker (existing and future) must support: a clean start-up-then-ready signal, a clean shutdown path, and a way for MLServer's `load()`/`unload()` to drive both.
2. Update `cerebrate-infer`'s and `cerebrate-generate`'s MLServer adapters so `load()` starts the worker process (if not already running for that model) and `unload()` stops it, rather than assuming a worker is always externally pre-started as it is today.
3. Exercise MLServer's model repository list/load/unload against the existing classifier and generator using this real process-lifecycle mechanism, before adding any new model.
4. Document recovery behavior explicitly: what happens on Android worker crash, on Debian/MLServer restart, and on an explicit unload/reload cycle.

### Phase C — ONNX Runtime characterization

1. Install/use the official Android ONNX Runtime package with XNNPACK and NNAPI support.
2. Run the MobileNet CPU/XNNPACK correctness baseline.
3. Run the NNAPI path with correctness checks and delegation evidence, going in expecting it may not reach real hardware acceleration (Section 3.1).
4. Record performance, memory, thermals, graph partitioning, and actual hardware behavior — whichever way it comes out.
5. Record the result in the catalog's validation fields rather than baking the decision into code. If NNAPI fails to accelerate, ORT is still promoted as the default CPU/XNNPACK-tier portable candidate (Section 6.3) — that's a real, useful outcome, not a failed gate.

### Phase D — Docling as the first Substrate-aligned ingestion component

1. Deploy **Docling** on Overmind, standalone — not framed as "Substrate is now online," just as one real ingestion pipeline built the way Substrate is meant to work.
2. Establish a derived artifact layout on one real project that retains the canonical source while storing `DoclingDocument` JSON, Markdown projection, extracted figures/tables, and optional chunks/metadata (`source.pdf` / `derived/document.json` / `derived/document.md` / `derived/figures/` / `derived/tables/`).
3. Validate representative non-PDF inputs as well as PDFs so the pipeline is treated as general ingestion infrastructure rather than a paper-specific converter.
4. Define the narrow call-out boundary for optional Cerebrate document-vision enrichment; keep Docling usable without a VLM.
5. Keep MarkItDown available only where its lightweight converter/plugin surface is independently useful.

### Phase E — First useful model set

Bring up models incrementally rather than in parallel, now that Phase B has given every worker a real start/stop lifecycle:

1. **Qwen3-0.6B** — general local generation through the proven LiteRT-LM path, ON_DEMAND.
2. **PaddleOCR-VL-1.6**, with **SmolVLM2-500M** as fallback/comparison, exposed as document-vision enrichment for Docling and other callers.
3. **Qwen2.5-Coder-1.5B** — bounded code/admin assistance, ON_DEMAND (never resident alongside Qwen3 in this phase).
4. **Speech** — choose Whisper/SenseVoice/Zipformer through the validated ORT/sherpa-onnx lane, whichever execution provider Phase C actually validated.
5. **Text-guided segmentation** — compare EdgeSAM + grounder, MobileSAM + grounder, and FastSAM + CLIP, preferring ONNX artifacts where practical.
6. Keep **MobileNetV1** as the known-good classifier and regression/control workload; add an ONNX export as the cross-runtime characterization model.
7. For each: record load time, resident memory, latency, thermal behavior, correctness, artifact format, and selected backend in the catalog.

## 12. Non-goals

This phase does **not** include:

- a distributed fleet scheduler;
- MLflow or any other database-backed model registry service (explicitly deferred, not rejected — see Section 7.2);
- in-process model swapping inside a single worker (explicitly deferred — Section 8's process-per-model design is the initial scope);
- a dynamic/unattended remote model-staging mechanism beyond ADB push as an operator action (a future pull-based mechanism is a separate feature);
- inventing a custom canonical document schema when `DoclingDocument` already provides the required normalized representation;
- predictive model preloading;
- raw KV-cache persistence/offload;
- replacing MLServer with Triton, BentoML, or another serving stack;
- forcing every workload into ONNX merely for uniformity;
- forcing every workload into one runtime;
- assuming ORT reaches Android hardware acceleration before it's measured (Section 3.1);
- fixing the current LiteRT `CompiledModel` GPU readback defect;
- replacing the proven LiteRT-LM path with ORT GenAI while the latter remains experimental for this use case;
- standing up the full "Substrate" system — Docling here is one component built to Substrate conventions, not evidence Substrate itself is operational;
- making local models responsible for unsupervised production server changes.

Future NVIDIA, mini-PC, or newer Android nodes may use different execution providers or engines while sharing the same logical catalog, artifact-management, capability, and serving concepts.

## 13. Definition of "Cerebrate online"

This phase is complete when the Pixel 6 can truthfully be treated as a reusable inference appliance rather than a collection of demos.

Minimum acceptance criteria:

- A Git-tracked model catalog (`catalog.yaml` + schema) exists with revision-pinned provenance, multiple artifact support, and per-device/per-backend validation status.
- Model artifacts can move through `REMOTE -> CACHED -> STAGED` via the ADB staging script without manual file archaeology, and every approved model is staged persistently on the device.
- Every worker (graph and session) has a real start/stop lifecycle, and MLServer's `load()`/`unload()` actually drives that process lifecycle rather than assuming a pre-started worker.
- The existing MobileNet classifier remains healthy and pinned.
- ONNX Runtime has been characterized on this exact Pixel 6 with correctness-first CPU/XNNPACK and NNAPI tests, and the result (including a negative NNAPI result) is recorded honestly in the catalog.
- ORT is used in production for at least one non-control workload at whatever tier (CPU/XNNPACK or NNAPI) it actually validated at.
- The catalog can express that a specialized backend is preferred over ORT for a specific model/device when measurements justify it.
- At least one general LLM is usable through the production service path.
- Docling is operational on Overmind as a real, working ingestion component built to Substrate conventions, and can emit at least lossless `DoclingDocument` JSON plus a Markdown projection from representative inputs, for at least one real project.
- A local document-vision/OCR model is usable as optional enrichment behind the Docling workflow without becoming the owner of document structure.
- At least one speech-to-text model is exposed if ORT/sherpa-onnx proves practical at whatever tier it validated at.
- At least one text-guided segmentation composition is exposed, or the attempted candidates are documented with a clear measured blocker.
- Every model has recorded artifact size, load time, resident memory, representative latency, correctness test, deployment artifact, selected backend, and residency policy.
- All capabilities remain reachable through `inference.home.arpa` and survive worker start/stop without changing the caller-facing contract.

At that point, Cerebrate Pixel 6 is **operational as a managed, runtime-neutral, multi-model edge inference node** — sized to what this system actually needs today, with clearly-marked, deliberately deferred paths (MLflow, in-process model swapping, dynamic remote staging, full Substrate) to grow into later if real usage justifies them.

## 14. References

### Docling

- Docling project: https://github.com/docling-project/docling
- Docling architecture: https://docling-project.github.io/docling/concepts/architecture/
- `DoclingDocument` unified representation: https://docling-project.github.io/docling/concepts/docling_document/
- Docling supported input/output formats: https://docling-project.github.io/docling/usage/supported_formats/
- Docling serialization and lossless structure: https://docling-project.github.io/docling/concepts/serialization/
- Docling CLI / conversion and chunking surfaces: https://docling-project.github.io/docling/reference/cli/
- Microsoft MarkItDown OCR plugin (optional compatibility/lightweight converter path): https://github.com/microsoft/markitdown/blob/main/packages/markitdown-ocr/README.md

### ONNX Runtime

- ONNX Runtime mobile deployment: https://onnxruntime.ai/docs/tutorials/mobile/
- ONNX Runtime architecture: https://onnxruntime.ai/docs/reference/high-level-design.html
- ONNX Runtime Execution Providers overview: https://onnxruntime.ai/docs/execution-providers/
- ONNX Runtime NNAPI Execution Provider: https://onnxruntime.ai/docs/execution-providers/NNAPI-ExecutionProvider.html
- ONNX Runtime XNNPACK Execution Provider: https://onnxruntime.ai/docs/execution-providers/Xnnpack-ExecutionProvider.html
- ONNX Runtime Android build/package guidance: https://onnxruntime.ai/docs/build/android.html
- ONNX Runtime plugin Execution Provider libraries: https://onnxruntime.ai/docs/execution-providers/plugin-ep-libraries/
- ONNX Runtime guidance for adding Execution Providers / plugin EP direction: https://onnxruntime.ai/docs/execution-providers/add-execution-provider.html
- ONNX Runtime Generate API / GenAI (preview): https://onnxruntime.ai/docs/genai/
- ONNX Runtime GenAI Android/source-build guidance: https://onnxruntime.ai/docs/genai/howto/build-from-source.html
- **NNAPI failing to reach `google-edgetpu`, confirmed via the issue body directly (Pixel 6a, Pixel 8 Pro)**: microsoft/onnxruntime#20782, "NNAPI doesn't work on google-edgetpu [Mobile]" — https://github.com/microsoft/onnxruntime/issues/20782
- **NNAPI deprecation prompting a search for an Android acceleration successor** (real, on-topic, but dated Feb 2025 — not the June 2026 discussion referenced in review; add the more recent thread here directly if you have the link): microsoft/onnxruntime#23565 — https://github.com/microsoft/onnxruntime/issues/23565
- *Not independently verified, add directly if available*: a July 2026 feature request proposing LiteRT as a future ONNX Runtime execution provider.

### Serving, model catalog, and artifact management

- sherpa-onnx Android documentation: https://github.com/k2-fsa/sherpa/blob/master/docs/source/onnx/android/index.rst
- MLServer model repository / multi-model examples: https://mlserver.readthedocs.io/en/stable/examples/index.html
- Hugging Face cache architecture: https://huggingface.co/docs/huggingface_hub/guides/manage-cache
- MLflow Model Registry (deferred future option, not used in this phase): https://mlflow.org/docs/latest/ml/model-registry

### Initial model candidates

- Qwen3-0.6B LiteRT-LM: https://huggingface.co/litert-community/Qwen3-0.6B
- Qwen2.5-Coder-1.5B-Instruct LiteRT-LM: https://huggingface.co/litert-community/Qwen2.5-Coder-1.5B-Instruct
- PaddleOCR-VL-1.6 LiteRT-LM: https://huggingface.co/litert-community/PaddleOCR-VL-1.6
- SmolVLM2-500M LiteRT-LM: https://huggingface.co/litert-community/SmolVLM2-500M
- EdgeSAM: https://github.com/chongzhou96/EdgeSAM
- MobileSAM: https://github.com/ChaoningZhang/MobileSAM
- FastSAM: https://github.com/CASIA-IVA-Lab/FastSAM
