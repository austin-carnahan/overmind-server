# Cerebrate Pixel 6 — Multi-Runtime Execution Plane

## Objective

Evolve `cerebrate-infer` from a single-purpose classification worker into a **general Android execution plane** supporting two distinct runtime contracts:

1. **Graph Execution** — bounded model-graph invocation, primarily using `.tflite` deployment artifacts.
2. **Session Execution** — stateful model sessions, primarily using `.litertlm` deployment artifacts and LiteRT-LM.

Preserve the already-proven TensorFlow Lite + NNAPI → `google-edgetpu` implementation as the Pixel 6's optimized **graph compatibility backend**.

The goal is not to create separate engines for classification, segmentation, OCR, speech, VLMs, etc. Instead, let the underlying deployment/runtime model determine the execution path.

---

# Guiding Architecture

```text
Overmind / clients
        │
        ▼
     MLServer
   Debian control plane
        │
        │ semantic inference requests
        ▼
     AVF boundary
        │
        ▼
cerebrate-infer
 Android execution plane
        │
        ├─────────────────────────────┐
        │                             │
        ▼                             ▼
 Graph Execution                Session Execution
        │                             │
        ├─ NNAPI compatibility        └─ LiteRT-LM
        │  backend                       Engine / Session
        │                               / Conversation
        │
        └─ future LiteRT
           CompiledModel backend
```

MLServer remains the stable northbound serving layer.

Android owns accelerator-facing runtime execution.

Debian should not need to understand NNAPI, LiteRT kernels, tokenizer internals, KV-cache layout, or model-specific accelerator behavior.

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

Keep the Android host as a black-box execution plane.

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

MLServer should hide the internal runtime split from Overmind.

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

Internally:

```text
model configuration
       │
       ├── Graph Execution
       │      ├── NNAPI/TFLite
       │      └── LiteRT CompiledModel
       │
       └── Session Execution
              └── LiteRT-LM
```

Do not expose Android runtime names as part of the public service contract.

For Session Execution, evaluate the cleanest way to propagate LiteRT-LM's asynchronous output chunks through the MLServer-facing service without buffering the complete response unnecessarily.

---

# Next Implementation Pass

## Phase 1 — Refactor the internal architecture

Introduce the Graph Execution / Session Execution distinction without changing existing classification behavior.

Move the existing NNAPI implementation conceptually beneath Graph Execution.

The existing MobileNet service must continue to pass unchanged.

## Phase 2 — Establish LiteRT-LM natively on Android

Build and run the native LiteRT-LM C++ stack on the Pixel host.

Prefer an official/prepackaged LiteRT-LM-compatible model suitable for the Pixel rather than converting a model ourselves initially.

Start small.

The purpose is to validate the runtime, not maximize model size.

## Phase 3 — Implement `LiteRtLmBackend`

Add a Session Execution backend that:

- loads the model once;
- creates an Engine;
- accepts semantic text-generation requests;
- manages the LiteRT-LM session internally;
- performs generation;
- streams chunks back across the existing Android↔Debian transport;
- reports runtime errors cleanly.

Use LiteRT-LM's own session/conversation machinery rather than recreating tokenization, prompt templates, KV-cache logic, or autoregressive decoding.

## Phase 4 — Extend the Debian adapter

Teach the Debian serving layer to distinguish graph requests from session/generation requests.

Keep the adapter thin.

For generative inference it should primarily:

```text
receive request
      ↓
forward semantic generation request
      ↓
relay streamed chunks
```

Do not move model-runtime internals into Debian.

## Phase 5 — Expose one text-generation service

Expose a small LiteRT-LM model through the same overall `inference.home.arpa` serving architecture used by the existing classifier.

Verify end-to-end:

```text
Overmind
   ↓
MLServer
   ↓
Debian adapter
   ↓
AVF
   ↓
cerebrate-infer
   ↓
LiteRT-LM
   ↓
Pixel execution backend
   ↓
streamed generated text
```

---

# Success Criteria

This implementation pass is complete when:

1. Existing MobileNet classification continues working through the Graph Execution compatibility backend.
2. The internal architecture clearly represents Graph Execution and Session Execution as separate runtime contracts.
3. An official/supported `.litertlm` model loads successfully in a native Android-host process.
4. Debian can submit a semantic prompt without handling tokenizer, tensor, or KV-cache internals.
5. Android performs the full LiteRT-LM generation lifecycle.
6. Output is returned incrementally rather than only after full completion.
7. The text-generation service is accessible through the same MLServer/Overmind serving architecture as graph inference.
8. The actual Pixel 6 execution backend used by LiteRT-LM is measured and documented rather than assumed.
9. Existing NNAPI classification performance and behavior are not sacrificed merely to unify implementation details.

---

# Implementation Philosophy

- Organize execution around **runtime contracts**, not task names.
- Treat `.tflite` and `.litertlm` as deployment artifacts for different execution semantics.
- Preserve the proven NNAPI path as a compatibility backend where it is objectively better on Tensor G1.
- Let LiteRT/LiteRT-LM own model-runtime complexity instead of recreating it.
- Keep Debian as the control/service plane and Android as the execution plane.
- Let MLServer hide backend heterogeneity from callers.
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