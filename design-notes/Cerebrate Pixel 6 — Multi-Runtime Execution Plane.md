# Cerebrate Pixel 6 — Multi-Runtime Execution Plane

## Objective

Evolve the Pixel 6's Android host from running a single-purpose classification worker into a **general Android execution plane** supporting two distinct runtime contracts:

1. **Graph Execution** — bounded model-graph invocation, primarily using `.tflite` deployment artifacts.
2. **Session Execution** — stateful model sessions, primarily using `.litertlm` deployment artifacts and LiteRT-LM.

Preserve the already-proven TensorFlow Lite + NNAPI → `google-edgetpu` implementation, unchanged, as the Pixel 6's optimized **graph compatibility backend**.

The goal is not to create separate engines for classification, segmentation, OCR, speech, VLMs, etc. Instead, let the underlying deployment/runtime model determine the execution path.

**Revised 2026-09-17**: Graph Execution and Session Execution are implemented as **two separate Android-host processes**, not as an internal dispatcher inside one binary. See "Process Architecture" below — this replaces the single-process dispatcher shown in earlier drafts of this document and changes the shape of the phases further down.

---

# Process Architecture

Graph Execution and Session Execution are not just two implementations of one runtime contract — they have materially different operating characteristics:

```text
cerebrate-infer                 cerebrate-generate
─────────────────               ───────────────────
Graph execution                 Session execution
.tflite                         .litertlm
NNAPI / LiteRT graph            LiteRT-LM
request → result                session → stream
~millisecond lifetime           seconds/minutes
tiny resident state             large model + KV/session state
easy restart                    stateful restart
high request concurrency        probably limited session concurrency
```

Putting both into one binary would require a backend-dispatch abstraction before there's any evidence that sharing a process buys anything. Two separate processes instead give several properties essentially for free:

- **Failure isolation** — a LiteRT-LM crash, OOM, bad model, or wedged generation session doesn't take down the already-stable MobileNet service.
- **Memory lifecycle isolation** — if a generative model consumes a couple of gigabytes, the whole `cerebrate-generate` process can be terminated and Android reclaims the entire address space, rather than hoping a shared runtime fully releases every allocator/cache/backend resource after unloading one model.
- **Independent supervision** — eventually, `cerebrate-infer` and `cerebrate-generate` can each have their own restart policy, resource expectations, health checks, ports, and startup behavior.
- **Independent evolution** — the graph worker keeps its NNAPI/TFLite compatibility stack; the generation worker follows LiteRT-LM releases on its own schedule. Neither inherits the other's build dependencies.

MLServer is the composition seam, not a dispatcher inside Android:

```text
MLServer
│
├── models/
│   ├── cerebrate-infer/    (existing)
│   │    └── adapter → cerebrate-infer:<port>       (Graph Execution)
│   │
│   └── gemma/              (future)
│        └── adapter → cerebrate-generate:<port>    (Session Execution)
│
└── stable external serving interface
```

## Naming

`cerebrate-infer` isn't wrong on its own, but once a second process exists, "infer" becomes ambiguous — generation is also inference. Internally:

- `cerebrate-infer` — **existing** graph worker. Not renamed — it's stable and already threaded through docs/services, and there's little value in touching something that already works.
- `cerebrate-generate` — **new** LiteRT-LM session worker.

`graph` describes the runtime contract; `generate` says immediately what the heavier process is doing.

## This does not mean "one process per model"

The pattern is: **one small Android worker per materially different execution runtime/lifecycle; MLServer composes them into one inference appliance.** Multiple *models* do not imply multiple Android *processes* — multiple runtime/lifecycle classes might.

```text
Android host                          Debian
├── cerebrate-infer      (graph)      └── MLServer
├── cerebrate-generate   (session)         ├── mobilenet      → cerebrate-infer
└── maybe something else                  ├── segmentation   → cerebrate-infer
    (only if a genuinely distinct              ├── embeddings     → cerebrate-infer
     runtime earns it)                         ├── gemma          → cerebrate-generate
                                                └── future VLM     → cerebrate-generate
```

Keeping that distinction is what stops this from degenerating into a daemon per model.

---

# Execution Contract 1 — Graph Execution

Graph Execution covers workloads fundamentally expressed as one or more bounded model invocations:

```text
input tensors
     ↓
model graph execution
     ↓
finite structured outputs
```

Typical workloads include:

- image classification;
- object detection;
- semantic segmentation;
- prompted segmentation such as SAM-style pipelines;
- image/text embeddings;
- pose or depth estimation;
- conventional OCR detector/recognizer pipelines;
- conventional speech recognition;
- other bounded `.tflite` inference graphs.

A workload being prompted, multimodal, or producing structured output does **not** by itself make it Session Execution.

## Android backends

Conceptually:

```text
GraphExecution
│
├── NnapiTfliteBackend
│     └── current Pixel 6 compatibility backend
│
└── LiteRtCompiledBackend
      └── modern LiteRT direction
```

### `NnapiTfliteBackend`

Retain the existing implementation that has already demonstrated:

```text
.tflite
   ↓
TensorFlow Lite interpreter
   ↓
NNAPI delegate
   ↓
google-edgetpu
   ↓
Tensor G1 TPU
```

This remains the preferred Pixel 6 path for compatible workloads where it demonstrably outperforms the newer alternatives.

Do not remove or replace it merely for API uniformity.

### `LiteRtCompiledBackend`

Treat LiteRT `CompiledModel` as the modern graph-execution backend to evaluate for future models and hardware.

Its natural deployment artifact is `.tflite`.

Do not assume that its NPU path works on Tensor G1 simply because the API supports NPU execution in general. Backend availability must remain empirical.

---

# Execution Contract 2 — Session Execution

Session Execution covers models whose runtime naturally owns persistent execution state and iterative generation:

```text
semantic input
     ↓
runtime session
     ↓
prefill / state update
     ↓
iterative decode
     ↓
streamed output
```

Initial target workloads include:

- LLM text generation;
- conversational models;
- generative VLMs;
- VLM-based OCR;
- autoregressive multimodal models;
- other LiteRT-LM-compatible generative workloads.

The initial implementation should use **LiteRT-LM** rather than manually reconstructing tokenization, KV caching, generation loops, or model-specific preprocessing.

LiteRT-LM already distinguishes heavyweight model `Engine` state from lighter stateful conversations/sessions and supports asynchronous chunked generation.

Conceptually:

```text
SessionExecution
└── LiteRtLmBackend
      ├── Engine
      ├── Session / Conversation
      ├── tokenization
      ├── prompt/model processing
      ├── prefill
      ├── decode
      ├── runtime state
      └── streamed response chunks
```

---

# Artifact Boundary

Prefer deployment-native artifacts rather than defining execution paths around source-framework formats.

```text
source / distribution model
PyTorch / Hugging Face / safetensors / etc.
                │
                │ deployment preparation
                ▼
        ┌───────────────┐
        │               │
     .tflite         .litertlm
        │               │
        ▼               ▼
 Graph Execution   Session Execution
```

`.tflite` should generally imply graph execution.

`.litertlm` should generally imply LiteRT-LM session execution.

Do not treat generic weight formats such as safetensors or PyTorch checkpoints as a third execution contract. They are upstream artifacts that may later be converted or packaged for an appropriate device runtime.

Future runtimes such as GGUF/llama.cpp may justify another backend, but do not design that path now.

---

# Workload Categorization

Use runtime behavior rather than task names.

| Workload | Preferred contract |
|---|---|
| Image classification | Graph |
| Detection | Graph |
| Semantic segmentation | Graph |
| Prompted segmentation / SAM | Graph |
| Embeddings | Graph |
| Pose / depth | Graph |
| Traditional OCR | Graph |
| Traditional ASR | Graph |
| LLM generation | Session |
| Generative VLM | Session |
| VLM-based OCR | Session |
| Autoregressive multimodal ASR | Session |

A capability may have implementations on either side.

For example:

```text
OCR
├── detector + recognizer .tflite models
│      → Graph Execution
│
└── VLM asked to transcribe a page
       → Session Execution
```

Likewise:

```text
speech-to-text
├── bounded ASR model
│      → Graph Execution
│
└── autoregressive multimodal model
       → Session Execution
```

The user-facing capability should therefore remain independent of the execution backend.

---

# Android Execution Boundary

Keep the Android host as a black-box execution plane. As of the Process
Architecture revision above, "the Android host" means two independent
processes (`cerebrate-infer`, `cerebrate-generate`), each a black box on
its own — Debian never needs to know there are two, only that MLServer's
adapters point at different ports for different models.

## Graph request

Conceptually:

```text
model
input tensor(s)
execution options
      ↓
GraphExecution
      ↓
output tensor(s)
```

## Session request

Conceptually:

```json
{
  "operation": "generate",
  "model": "gemma-...",
  "prompt": "Explain DNS recursion.",
  "max_tokens": 256,
  "temperature": 0.7
}
```

Android owns the runtime session and returns incremental output:

```text
CHUNK "DNS"
CHUNK " recursion"
CHUNK " is"
...
DONE
```

The exact wire protocol may evolve, but preserve the semantic distinction:

```text
Graph:
request → result

Session:
session/input → streamed output
```

---

# MLServer Integration

MLServer should hide which Android process (and which runtime contract) backs each model from Overmind.

Externally:

```text
inference.home.arpa
        │
        ▼
     MLServer
        │
        ├── mobilenet
        ├── segmentation-model
        ├── speech-model
        ├── gemma
        └── future VLM
```

Internally, each MLServer model directory's adapter points at exactly one Android-host process — the split is which port an adapter dials, not an in-process dispatch:

```text
model configuration
       │
       ├── Graph Execution adapters   → cerebrate-infer:<port>
       │      (NNAPI/TFLite today; LiteRT CompiledModel is a
       │       possible future backend inside that same process)
       │
       └── Session Execution adapters → cerebrate-generate:<port>
              (LiteRT-LM)
```

Do not expose Android process or runtime names as part of the public service contract.

For Session Execution, evaluate the cleanest way to propagate LiteRT-LM's asynchronous output chunks through the MLServer-facing service without buffering the complete response unnecessarily.

---

# Next Implementation Pass

## Phase 1 — Name and reserve the architecture, touch nothing that works

No dispatcher refactor of `cerebrate-infer` — that was the pre-revision
plan and is now dropped. `cerebrate-infer` already **is** the Graph
Execution worker under the new terminology; its behavior doesn't need
to change to satisfy that.

- Document `cerebrate-infer` explicitly as the Graph Execution
  (NNAPI/TFLite) worker in its own README, and record the
  `cerebrate-generate` sibling-process architecture as the intended
  shape for Session Execution.
- Reserve the directory/naming/port convention for `cerebrate-generate`
  now, even though nothing occupies it yet, so Phase 2 has an obvious
  home instead of a naming decision made under pressure later.
- Acceptance: existing MobileNet classification through
  `inference.home.arpa` continues to pass, unchanged — this is
  trivially true if no code changes, but is still the actual bar to
  clear before calling Phase 1 done.

## Phase 2 — Establish LiteRT-LM natively on Android

Build and run the native LiteRT-LM C++ stack on the Pixel host, as its
own `cerebrate-generate` process — not inside `cerebrate-infer`.

Prefer an official/prepackaged LiteRT-LM-compatible model suitable for the Pixel rather than converting a model ourselves initially.

Start small.

The purpose is to validate the runtime, not maximize model size.

(The feasibility spike recorded in the Progress Notes below already
cleared the riskiest part of this phase — the native C API prebuilt
links and runs without Bazel, and SmolLM2-135M-Instruct generates
coherent output on both CPU and GPU backends. Phase 2 turns that
throwaway harness into a real, persistent, TCP-serving worker, the same
step `cerebrate-infer` itself went through after its own first working
spike.)

## Phase 3 — Turn the spike into `cerebrate-generate`

Build the real `cerebrate-generate` worker — a persistent process,
analogous to `cerebrate-infer`'s own design, that:

- loads the model once;
- creates an Engine;
- accepts semantic text-generation requests over its own TCP port;
- manages the LiteRT-LM session internally;
- performs generation;
- streams chunks back across the AVF boundary to Debian;
- reports runtime errors cleanly;
- can be restarted/killed independently of `cerebrate-infer` without
  affecting it.

Use LiteRT-LM's own session/conversation machinery rather than recreating tokenization, prompt templates, KV-cache logic, or autoregressive decoding.

## Phase 4 — Add a second, sibling Debian adapter

Do **not** teach one adapter to distinguish graph vs. session requests.
Add a second MLServer model directory/adapter, alongside the existing
`cerebrate-infer` adapter, that dials `cerebrate-generate` instead. Each
adapter stays thin and single-purpose, matching the existing
`cerebrate_infer_runtime.py` pattern:

```text
receive request
      ↓
forward semantic generation request to cerebrate-generate
      ↓
relay streamed chunks
```

Do not move model-runtime internals into Debian, and do not merge this
into the existing adapter's code path.

## Phase 5 — Expose one text-generation service

Expose a small LiteRT-LM model through the same overall `inference.home.arpa` serving architecture used by the existing classifier, as a second model alongside it, not a replacement.

Verify end-to-end:

```text
Overmind
   ↓
MLServer (gemma model / cerebrate-generate adapter)
   ↓
Debian adapter
   ↓
AVF
   ↓
cerebrate-generate
   ↓
LiteRT-LM
   ↓
Pixel execution backend
   ↓
streamed generated text
```

...alongside the still-unmodified, still-working:

```text
Overmind
   ↓
MLServer (mobilenet model / cerebrate-infer adapter)
   ↓
Debian adapter
   ↓
AVF
   ↓
cerebrate-infer
   ↓
NNAPI
   ↓
google-edgetpu
```

---

# Success Criteria

This implementation pass is complete when:

1. Existing MobileNet classification continues working through `cerebrate-infer`, unmodified.
2. Graph Execution and Session Execution are represented as separate runtime contracts by construction — two independent Android-host processes (`cerebrate-infer`, `cerebrate-generate`), not an internal dispatcher.
3. An official/supported `.litertlm` model loads successfully in `cerebrate-generate`, a native Android-host process independent of `cerebrate-infer`.
4. Debian can submit a semantic prompt without handling tokenizer, tensor, or KV-cache internals.
5. Android performs the full LiteRT-LM generation lifecycle.
6. Output is returned incrementally rather than only after full completion.
7. The text-generation service is accessible through the same MLServer/Overmind serving architecture as graph inference.
8. The actual Pixel 6 execution backend used by LiteRT-LM is measured and documented rather than assumed.
9. Existing NNAPI classification performance and behavior are not sacrificed merely to unify implementation details.

---

# Implementation Philosophy

- Organize execution around **runtime contracts**, not task names.
- One small Android worker per materially different execution runtime/lifecycle; multiple *models* do not imply multiple Android *processes*, but multiple runtime/lifecycle classes might. MLServer composes them into one inference appliance.
- Treat `.tflite` and `.litertlm` as deployment artifacts for different execution semantics.
- Preserve the proven NNAPI path as a compatibility backend where it is objectively better on Tensor G1 — don't touch a stable worker to satisfy an architecture diagram.
- Let LiteRT/LiteRT-LM own model-runtime complexity instead of recreating it.
- Keep Debian as the control/service plane and Android as the execution plane.
- Let MLServer hide backend/process heterogeneity from callers — this is a composition seam MLServer already provides (one model directory per adapter), not something to build.
- Establish functionality first; defer memory offloading, SSD strategies, KV-cache relocation, fleet routing, and performance optimization until real workloads justify them.

The desired result is a Cerebrate node that no longer means “Pixel image classifier.”

It means:

> **A standardized inference appliance whose Android execution plane can run both bounded model graphs and stateful generative sessions, while the rest of Overmind interacts with one stable serving interface.**

---

# Progress Notes

## Feasibility spike: all three pre-project gates passed (2026-09-17)

Before committing to the five-phase plan above, ran a deliberately
throwaway spike per the redefined pre-project gates — no `cerebrate-infer`
changes, no MLServer changes, no AVF protocol design. Pure native
Android-host process, built and run outside the repo.

**Artifacts used:**

- **Native runtime**: `litert_lm_c_api-0.1.0.zip` from the
  [LiteRT-LM v0.16.0 release](https://github.com/google-ai-edge/LiteRT-LM/releases/tag/v0.16.0)
  (google-ai-edge/LiteRT-LM) — the first versioned C API shared-library
  prebuilt release. Contains `lib/android_arm64/liblitert-lm.so` (39MB)
  plus plain-C headers (`engine.h`, `conversation.h`).
- **Model (canary)**: [`litert-community/SmolLM2-135M-Instruct`](https://huggingface.co/litert-community/SmolLM2-135M-Instruct)
  on Hugging Face — `SmolLM2_135M_Instruct.litertlm`, 142MB (matches the
  ~143MB estimate).

### Gate 1 — Native runtime: passed

Verified exported symbols with `llvm-nm -D` before writing any code
(same discipline as the original `cerebrate-infer` NNAPI work) —
`litert_lm_engine_create`, `litert_lm_engine_settings_create`,
`litert_lm_session_generate_content`, and others all present. Wrote a
~70-line C harness (`canary.c`, not committed — throwaway) against
`engine.h`, compiled with a single plain
`aarch64-linux-android24-clang` invocation, **no Bazel**, no build
system beyond one compiler command. `liblitert-lm.so`'s only `NEEDED`
entries are stock Android system libraries (`libandroid`, `libz`,
`libGLESv2/v3`, `libEGL`, `libdl`, `liblog`, `libm`, `libc`) — nothing
extra to push to the device, unlike the legacy TFLite C API which
needed `libc++_shared.so`.

### Gate 2 — Model: passed

Pushed the harness, the `.so`, and the model to `/data/local/tmp/` on
the Android host (same deployment pattern as `cerebrate-infer`) and ran
it directly via `adb shell`. Prompted with "Reply with the word hello."
and got genuinely coherent, on-topic generated text back — not a crash,
not garbage tokens, not a `<pad>` loop:

> "Hello! I'm so glad you're here. I'm a language model, and I'm happy
> to help you with your language learning. What language are you
> learning? Do you want to learn French, Spanish, or perhaps Mandarin
> Chinese?"

### Gate 3 — Backend: passed, measured not assumed

Ran the identical prompt against both `backend="cpu"` and
`backend="gpu"`, reading the actual runtime logs rather than assuming:

- **NPU**: unavailable — `NPU accelerator could not be loaded and
  registered: kLiteRtStatusErrorInvalidArgument`. Expected and
  consistent with Tensor G1's known NPU exposure being NNAPI-only (see
  the LiteRT v2 `CompiledModel` spike in the Stage 5 backend-decision
  section of the main Pixel 6 design notes).
- **CPU**: works — log confirms `Created TensorFlow Lite XNNPACK
  delegate for CPU`, coherent output.
- **GPU**: works — "Statically linked GPU accelerator registered",
  coherent output, no sign of the known Gemma-3-270M `<pad>`-loop bug.
  One non-fatal gap: `libLiteRtTopKOpenClSampler.so` (an optional
  OpenCL-accelerated sampler) wasn't pushed, so it fell back to a
  statically-linked CPU sampler implementation automatically —
  generation still succeeded, just not using every GPU-side
  optimization available. Worth pushing that library too in a real
  integration if GPU ends up being the chosen path.

### Conclusion

All three gates passed on the first attempt, with no Bazel build, no
model-conversion step, and no crashes. The single biggest identified
risk — native LiteRT-LM integration without a full Bazel build —
evaporated cleanly. The five-phase plan above is justified to proceed.
Nothing from this spike was integrated into `cerebrate-infer` or
committed to the repo; it was intentionally disposable, per the gate
design.

## Phase 1 done: named, reserved, nothing touched (2026-09-17)

Zero code changes, as designed — `cerebrate-infer` already satisfied
"Graph Execution" under the new terminology before this phase started.

- `cerebrate-infer`'s own README now documents it explicitly as the
  Graph Execution worker and records `cerebrate-generate` as the
  planned Session Execution sibling process.
- Reserved, in documentation only (no directories/files created yet):
  port `8766` on the Android host for `cerebrate-generate`, and
  `hosts/cerebrate-pixel6/cerebrate-generate/` as its future source
  location. Real content arrives in Phase 2.
- Acceptance check re-verified: MobileNet classification through
  `inference.home.arpa` still returns `"military uniform"` at 88.6%
  confidence — identical to every prior test, since nothing changed.

Phase 2 (native LiteRT-LM stack on Android, as its own persistent
`cerebrate-generate` process) is next.

## Phase 2/3 done: `cerebrate-generate` is real, not a spike (2026-09-17)

Reported as one combined pass rather than two separate announcements —
the feasibility spike (above) already did what Phase 2 originally set
out to validate (does the native stack even work on this hardware), so
the actual new work this pass was entirely Phase 3's: turning that
throwaway harness into a real, persistent, TCP-serving worker.

Built [`cerebrate-generate`](../hosts/cerebrate-pixel6/cerebrate-generate/README.md),
modeled directly on `cerebrate-infer.cc`'s own structure: loads the
`.litertlm` model and creates the LiteRT-LM `Engine` **once** at
startup (not per-request, unlike the spike, which created one engine
and exited), then serves an `accept()`/serial-request loop — one
`Session` created and destroyed per request, `generate_content` run
synchronously, `SO_RCVTIMEO` applied to every accepted client socket
from the start this time (the lesson from `cerebrate-infer`'s Stage 5
Phase 4 wedged-worker bug, applied proactively rather than discovered
the hard way again).

Wire protocol is a 4-byte big-endian length prefix + UTF-8 text, in
both directions — a length prefix rather than `cerebrate-infer`'s
fixed-byte-count framing, since prompt/response text is variable-length
and may contain arbitrary bytes (including newlines) that would break
line-delimited framing. Explicitly a native-worker validation protocol,
not the final Debian-facing wire format (that's a later phase).

Build note: LiteRT-LM ships an actual **versioned C API shared-library
release asset** (`litert_lm_c_api-0.1.0.zip` on the v0.16.0 GitHub
release) — no AAR-unzip trick needed this time, unlike the legacy
TFLite C API. Compiled with one plain `clang++` invocation, no Bazel,
same as the spike.

Verified from the real Debian guest, over the real production AVF
path (not a loopback/ADB shortcut): two requests over one reused
connection (`"Reply with the word hello."` → coherent greeting; `"What
is the capital of France?"` → **"The capital of France is Paris."**,
correct, not just coherent), plus a third request on a fresh new
connection to confirm the outer `accept()` loop also works across
multiple connections. `request_id` incremented correctly throughout;
worker PID never changed (no crash, no restart needed); server-side
logged timing matched client-observed elapsed time closely.

Not yet done, deliberately deferred: GPU backend re-validation against
the persistent worker specifically (already proven functional for this
model in the spike — re-testing wouldn't teach anything new about the
worker's own design); streaming (`generate_content_stream`); process
supervision/health checks; the actual MLServer adapter. Those are
Phase 4/5's job.

## Phase 4/5 done, with one honest gap: no streaming yet (2026-09-17)

Reported together, not as two separate passes — building Phase 4's
adapter and testing it immediately satisfied Phase 5's own stated bar
("expose through the same overall `inference.home.arpa` serving
architecture... verify end-to-end"), so there was no separate step left
to report.

Added a standalone
[`cerebrate-generate` MLServer adapter](../hosts/cerebrate-pixel6/mlserver/models/cerebrate-generate/README.md)
— a second MLServer model directory, dialing `cerebrate-generate`'s
length-prefixed TCP protocol, with zero shared code with the existing
`cerebrate-infer` adapter (the AVF-gateway auto-discovery helper is
duplicated on purpose, not extracted into a shared module — these two
adapters are meant to stay fully independent, per the whole point of
the process-architecture revision above).

Verified: correct generation both locally inside the guest and through
the full external path
(`inference.home.arpa` → Caddy → relay → tunnel → MLServer → this
adapter → AVF → `cerebrate-generate` → LiteRT-LM), and — critically —
the existing classifier queried immediately alongside it in the same
session, confirming both models genuinely coexist under one MLServer
instance without interfering with each other.

**Checking this pass against all nine of this document's own Success
Criteria, honestly:**

1. Existing MobileNet classification unmodified — ✅
2. Graph/Session as two independent processes by construction — ✅
3. Official `.litertlm` model loads in `cerebrate-generate`, independent of `cerebrate-infer` — ✅
4. Debian submits a semantic prompt with no tokenizer/tensor/KV-cache handling — ✅
5. Android performs the full LiteRT-LM generation lifecycle — ✅
6. **Output returned incrementally rather than only after full completion — ❌ not yet done.** `cerebrate-generate` only implements synchronous `generate_content`; `generate_content_stream` is exported but unused. This is deliberately deferred, not forgotten — it's genuinely the one remaining piece of the original plan.
7. Text-generation service accessible through the same MLServer/Overmind architecture as graph inference — ✅
8. Actual Pixel 6 execution backend measured, not assumed (done in the spike: NPU unavailable, CPU/XNNPACK and GPU both confirmed via logs) — ✅
9. Existing NNAPI classification performance/behavior not sacrificed — ✅ (`cerebrate-infer` untouched throughout)

So: 8 of 9 criteria met. The plan isn't being declared fully complete —
streaming is the honest, explicitly-tracked remainder, not a detail
being quietly dropped.

## Streaming done: 9/9 success criteria met (2026-09-17)

### Correction: MLServer 1.3.5 was an environment constraint, not a real absence of streaming support

The Phase 4/5 entry above stated MLServer lacked streaming support,
full stop. That was wrong in an important way, caught before writing
any streaming code: PyPI's actual latest stable MLServer release is
**1.7.1**, not 1.3.5. `pip install mlserver` on the guest silently
resolved to 1.3.5 back in Phase 1 because 1.7.1 (and everything from
1.4.0 onward) declares `requires_python: <3.13,>=3.9`, and the guest's
system Python is 3.13 — `pip` quietly picked the newest
*compatible* version with no obvious warning that a newer release
existed. Confirmed directly against PyPI's raw JSON release metadata
(not `pip index versions`, which filters by the running interpreter
and would hide this the same way) before concluding anything, then
confirmed the *installed* 1.3.5 package genuinely has no
`infer_stream`/`generate_stream` code by grepping its source, versus
finding real streaming code throughout 1.7.1's `dataplane.py`,
`rest/app.py`, and `rest/endpoints.py`.

This meant the "install from GitHub master" vs. "build a bespoke SSE
layer" fork from the earlier planning conversation was a false choice
— a fourth path existed: get a real Python 3.12 (Debian 13 doesn't
package one; obtained via [`uv`](https://github.com/astral-sh/uv), a
static binary that fetches a pinned prebuilt CPython build, no
compiling from source), install pinned `mlserver==1.7.1` in a
disposable venv there, and prove it works before touching anything
that matters.

### The four-gate migration

**Gate A** — disposable Python 3.12 + `mlserver==1.7.1`, both existing
models unchanged. Ran a second MLServer instance (alternate ports,
production untouched) against the exact same model directories:
classifier → `"military uniform"` 88.6% (identical); buffered
generation → `"The capital of Italy is Rome."` (correct). Passed
cleanly — the only snag was Pillow not being installed in the fresh
venv (a separate venv from production, caught immediately by the
classifier failing to load, fixed with one `uv pip install`).

**Gate B** — a trivial fake `predict_stream()` model (six hardcoded
chunks, `asyncio.sleep(0.5)` between each), hit via
`/v2/models/fake-stream/generate_stream`. Chunks arrived at 0.72s,
1.23s, 1.73s, 2.23s, 2.74s, 3.25s — each ~0.5s apart, matching the
injected delay exactly. Confirmed: real SSE (`Content-Type:
text/event-stream`), genuine incremental delivery (not a buffered
dump), MLServer automatically attaching CloudEvents-style headers.
Zero LiteRT-LM code touched yet — this gate is entirely about proving
the *mechanism*.

**Gate C** — rewrote `cerebrate-generate.cc` to use
`litert_lm_session_generate_content_stream` as the only native
generation path (removing the earlier synchronous-only
`generate_content` call entirely, not keeping both side by side). That
API is non-blocking and invokes its callback from a **LiteRT-LM-owned
background thread**, once per chunk — the first real multi-threading
in either Android worker. Added a `pthread` mutex/condvar so the
accept-loop thread can block until a chunk reports `is_final()` or an
error, while the callback thread does the actual chunk delivery
directly to the socket. Replaced the wire protocol with typed frames
(`[1-byte type][4-byte length][payload]`, `DATA`/`DONE`/`ERROR`) —
a breaking change to a protocol shipped only hours earlier, judged
cheap deliberately: `cerebrate-generate` has exactly one known
consumer, and MLServer is the real public seam, so this is exactly the
moment an internal protocol is safe to redesign.

Tested directly over raw TCP, before touching the Python adapter at
all: a real prompt produced real token-by-token output at genuine
per-token decode latency (~20-30ms between `DATA` frames, not
artificial delays like Gate B's), terminated cleanly with `DONE`,
worker PID unchanged throughout (no crash, no deadlock from the new
threading).

**Gate D** — rewrote `cerebrate_generate_runtime.py`'s wire-level code
for the new typed-frame protocol, with `predict()` (buffers all `DATA`
frames, backs `/infer`) and a new `predict_stream()` (yields one
`InferenceResponse` per frame, backs `/generate_stream`) sharing one
internal `_stream_generate()` generator. Promoted MLServer 1.7.1 to
the actual production systemd unit (`MLSERVER_GZIP_ENABLED=false`
added — MLServer's own source comments "GZip middleware does not work
with streaming"; `MLSERVER_PARALLEL_WORKERS=0` carried forward, already
required for an unrelated uvloop crash and, it turns out, also required
for streaming).

Verified through the complete real path —
`inference.home.arpa` → Caddy → relay → tunnel → MLServer 1.7.1 → this
adapter → AVF → `cerebrate-generate` → LiteRT-LM — with a **regression
check run immediately alongside**, not after: the classifier (unchanged
`"military uniform"` 88.6%) and the buffered generation path (`"The
capital of Spain is Madrid."`) both still correct under the new
MLServer version and adapter, and then real incremental streaming
tokens (`"The"`, `" capital"`, `" of"`, `" Germany"`, `" is"`,
`" Berlin"`, `"."`, arriving over ~170ms) with genuinely correct
content.

### Final scorecard: 9/9

1. Existing MobileNet classification unmodified — ✅
2. Graph/Session as two independent processes by construction — ✅
3. Official `.litertlm` model loads in `cerebrate-generate`, independent of `cerebrate-infer` — ✅
4. Debian submits a semantic prompt with no tokenizer/tensor/KV-cache handling — ✅
5. Android performs the full LiteRT-LM generation lifecycle — ✅
6. **Output returned incrementally — ✅ (was the one gap; now closed).** Real SSE streaming, real per-token latency, verified end to end.
7. Text-generation service accessible through the same MLServer/Overmind architecture as graph inference — ✅
8. Actual Pixel 6 execution backend measured, not assumed — ✅
9. Existing NNAPI classification performance/behavior not sacrificed — ✅ (`cerebrate-infer` untouched throughout; reverified working after every subsequent change to its sibling process)

All nine of this document's own success criteria are met. The original
five-phase Multi-Runtime Execution Plane, plus the streaming follow-on,
is complete.

### Left for later, not blocking anything

- `max_tokens`/`temperature`/sampling parameters not yet exposed.
- No error-path testing for `cerebrate-generate` (worker down,
  malformed prompt, mid-stream disconnect).
- No watchdog timeout if the LiteRT-LM callback thread never reports
  done — same unbounded-block posture the synchronous design already
  had, not a new regression, but worth hardening if ever observed in
  practice.
- The old `~/mlserver-venv` (1.3.5, Python 3.13) on the guest is now
  unused dead weight, left in place rather than deleted without being
  asked.
- gRPC streaming (broader than REST's server-only streaming) not
  explored — unnecessary for the current prompt-in/tokens-out shape.

## Original design-doc quote, superseded by the process-architecture revision

(Retained for history — no longer the current design.) The initial
draft of this plan proposed one Android process with an internal
`GraphExecution`/`SessionExecution` dispatcher, on the reasoning that
"MLServer should hide the internal runtime split from Overmind." That
was revised the same day, before any implementation started, once the
operating-characteristics mismatch between the two contracts (see
"Process Architecture" above) was worked through — the dispatcher was
never built and this document's main body now reflects the two-process
design.