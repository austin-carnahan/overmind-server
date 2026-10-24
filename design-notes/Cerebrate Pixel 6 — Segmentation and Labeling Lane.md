# Cerebrate Pixel 6 — Segmentation and Labeling Lane

**Status:** PARTIAL — Step 1 (general-purpose ONNX graph worker) done and deployed; Step 2 next.
**Date:** 2026-10-23
**System:** Overmind / Cerebrate Pixel 6
**Builds on:** [Operational Model Catalog v4](cerebrate_pixel6_operational_model_catalog_v4.md),
[Multi-Runtime Execution Plane](Cerebrate%20Pixel%206%20%E2%80%94%20Multi-Runtime%20Execution%20Plane.md),
[Pixel 6 inference node](2026-09-16-pixel6-inference-node.md)
**Consumer:** [Agentic Design Studio — Mac GIMP worker](agentic-design-studio-mac-worker-milestone-v0.1.md)

## 1. Purpose

The Design Agent (Buckminster) will eventually take instructions like "remove
the sconces", "move the sconces from this other photo into this one", or
"change this chair's color". Before any of that, it needs **good segmentations
in GIMP, as layers, with semantically accurate labels**.

This lane computes those segmentations on the Pixel 6. It does not attempt the
editing itself (inpainting, compositing, recoloring), which is a later problem.

The larger outcome is not the last millisecond on this phone. It is proving
that heterogeneous vision workloads can run across TPU, GPU, and CPU with
reliable correctness checks behind one consistent service interface
(Section 5.1) — a pattern that transfers to a more powerful Overmind worker
later.

> **Key lesson (Step 2A): a compiler/runtime incompatibility doesn't
> necessarily mean a model architecture is unsupported. Sometimes a relatively
> small, mathematically equivalent graph rewrite can unlock the entire model.**
> Folding DINOv2's LayerScale into adjacent weights turned a numerically wrong
> GPU result (cosine 0.026) into an exact one (cosine 1.000000) and unlocked
> the LiteRT GPU path. Section 4.6 proposes how to make such rewrites a
> standard, packaged step for every new model.

## 2. Placement decisions

- **The Pixel 6 is the compute node for this lane.** It runs the models behind
  the existing Cerebrate architecture: Android-host workers started by
  `cerebrate-supervisor`, MLServer in the Debian guest as the serving seam,
  `inference.home.arpa` as the address the rest of Overmind uses.
- **The Mac is for development, testing, and comparison only.** Model exports,
  quantization, reference outputs, and benchmark runs happen there. It is not
  part of any regular workflow from Overmind, apart from its separate role as
  the GIMP worker. Nothing in this lane may depend on the Mac being online.
- **`overmind-01` does no inference here.** It is a 4-core Pi with load
  constraints. It orchestrates, stores, and stages models, as it already does.
- **GIMP only sees an output contract** (Section 7), never a model. Models and
  accelerators can change without touching the GIMP side.

## 3. What we found

### 3.1 The device

Pixel 6 (`oriole`, Tensor G1), 8-core CPU (2× X1, 2× A76, 4× A55), 7.8 GB RAM.
The Debian guest has about 1 GB of that and no accelerator access; models run
as native Android-host processes, which hold the rest of the memory.

### 3.2 Accelerator status (measured, not assumed)

| Path | Status on this Pixel 6 | Evidence |
| --- | --- | --- |
| TFLite + NNAPI → `google-edgetpu` | **Proven, in production** (MobileNet, 777 µs) | [inference node notes](2026-09-16-pixel6-inference-node.md#backend-decision-litert-v2-spike-vs-legacy-nnapi-2026-09-16) |
| ORT + NNAPI → `google-edgetpu` | **Proven in a spike** (146/149 nodes, bit-exact) | [onnxruntime-characterization](../hosts/cerebrate-pixel6/spikes/onnxruntime-characterization/README.md) |
| ORT CPU | Proven correct; RF-DETR Seg Nano in 483 ms | same spike; [cerebrate-graph](../hosts/cerebrate-pixel6/cerebrate-graph/README.md#results-2026-10-23) |
| ORT XNNPACK | Crashes on the quantized MobileNet; **runs fp32 RF-DETR correctly**, but slower than CPU (1.3 s) | same spike; cerebrate-graph |
| ORT + NNAPI, fp32 graph | **TPU rejects all fp32 ops** (RF-DETR: driver reports 0 supported) | cerebrate-graph |
| ORT + NNAPI, fp16-relaxed graph | Driver accepts the ops, then **the vendor Darwinn compiler crashes** (RF-DETR) | cerebrate-graph |
| ORT + WebGPU (Dawn → Vulkan, Mali GPU) | **Blocked: its MatMul and Conv kernels crash the GPU** (`VK_ERROR_DEVICE_LOST`); element-wise, LayerNorm and Softmax kernels are correct. Every real model tested failed; all pass on the Mac's Metal | [webgpu-op-bisect](../hosts/cerebrate-pixel6/spikes/webgpu-op-bisect/README.md) |
| Classic TFLite GPU delegate (OpenCL) | **Correct** — the first verified-correct vision inference on this GPU. Float MobileNet: 11.6 ms fp32 (cosine 1.0), 7.8 ms fp16, vs 28.3 ms CPU | [tflite-gpu-delegate](../hosts/cerebrate-pixel6/spikes/tflite-gpu-delegate/README.md) |
| LiteRT-LM GPU (OpenCL) | **Correct generation** (SmolLM2-135M) — the GPU and its OpenCL stack do compute correctly on this device | [model catalog](../models/catalog.yaml) (`pixel6_litertlm_gpu: passed`) |
| LiteRT `CompiledModel` GPU (2.3.0) | **Correct for float models**: prepared DINOv2-small in 68.6 ms end to end at fp32 (cosine 1.0, task-level ranking identical) vs 344 ms CPU — about 5×; 37.8 ms at fp16, which loses accuracy. For the tested **uint8-I/O** quantized MobileNet it never writes the output (the earlier "all-zero" result). Computes `[N,C] × [C]` broadcast multiplies wrongly — worked around in model preparation (Section 4.5) | [litert-gpu-transformers](../hosts/cerebrate-pixel6/spikes/litert-gpu-transformers/README.md) |
| LiteRT NPU | Does not load on Tensor G1 | inference node notes |
| GPU via NNAPI | Not available: NNAPI lists only `google-edgetpu` and `nnapi-reference` | inference node notes |

The only model accelerated so far is **one small int8-quantized CNN**. Step 1
measured that the TPU takes no fp32 work at all, so for the TPU, int8
quantization is a requirement, not an optimization. Whether int8
attention-style graphs fare better is still a per-model question (catalog v4
Section 6.2).

On the GPU, Step 2A established a working transformer path. The OpenCL stack
is sound (LiteRT-LM generates correctly; the classic TFLite GPU delegate runs
float MobileNet correctly). **LiteRT 2.3.0's `CompiledModel` GPU path runs a
prepared DINOv2-small correctly, about 5× faster than CPU end to end at fp32**, after model preparation
removes two things it gets wrong or can't take (Section 4.5). Its old
"all-zero output" failure turned out to be the GPU accelerator never writing
the uint8 I/O tensors of the tested quantized MobileNet (other uint8 models
are untested); float models — which converted
transformers are — work. The classic delegate rejects transformer graphs (it
expects 4-D image tensors) but remains useful for CNNs, and ORT WebGPU stays
blocked (MatMul/Conv kernels crash the Mali). The cost of the GPU path:
models must be converted to `.tflite` and prepared, and serving them needs a
LiteRT engine in a worker (Step 2A item 5).

### 3.3 The browser-perception models

[browser-perception](https://github.com/imagingforgood/browser-perception) runs these models
in ONNX Runtime Web. The same `.onnx` files load in native ORT on Android.
Operator counts below come from inspecting the local files.

| Model | Size | Input | Notable operators | Gives you |
| --- | --- | --- | --- | --- |
| RF-DETR Seg Nano | 123 MB | static `1×3×312×312` | 56 LayerNorm, 17 Erf (GELU), 4 GridSample | Instance masks + labels, 80 COCO classes only; masks at 312×312 |
| SAM 2.1 Hiera Tiny encoder | 134 MB fp32 | `batch×3×1024×1024` (dynamic batch) | 24 LayerNorm, 12 Erf | Image embeddings, once per image |
| SAM 2.1 decoder | 21 MB fp32 | many dynamic dims | ScatterND, OneHot, Range | One precise mask per click/box, no labels |
| RAM++ (not in the repo; deferred, Section 4.4) | ~873 MB int8 | `1×3×384×384` | Swin-Large | Image-level tags from 4,585 classes, no locations |

All of these are transformer-based. **Measured for RF-DETR:** ORT's NNAPI
provider would take 879 of 1,021 nodes in 77 partitions, but the TPU accepts
none of them in fp32 (Section 3.2). Transformers' operators (LayerNorm, GELU,
attention, GridSample) are outside what the TPU handles at any precision, so
**their acceleration candidate is the GPU**, with CPU as the fallback — which
is less of a penalty than assumed: RF-DETR runs in 483 ms on the Pixel's CPU.
Box prompts were SAM 2.1's best mode in
browser-perception's object-selection benchmark (86.9% mean IoU versus 71.3%
for a single click), which is why this plan feeds SAM boxes.

### 3.4 Other candidate models: grounders, open vocabulary, edge SAM

| Model | Notes |
| --- | --- |
| **YOLOE** (Ultralytics) | YOLO-family detector with open-vocabulary detection *and* instance segmentation. 10–45M parameters by variant. A prompt-free variant has 4,585 built-in classes (no class list to maintain); text-prompted variants bake their classes into static exports. Exports to ONNX and LiteRT with int8. **The model most likely to reach the TPU**, with a caveat: the YOLOE-v8 variants are pure CNNs, but YOLO11 adds an attention block (C2PSA) the TPU may refuse, and YOLOE-26's architecture is unverified. AGPL-3.0. |
| **EdgeSAM** | SAM distilled into a purely CNN-based image encoder for phones (real-time on an iPhone 14). Point/box-prompted like SAM; separate ONNX encoder and decoder. The SAM-family model most likely to reach the TPU. |
| **OWLv2** | CLIP-style: separate image and text towers, so the vocabulary is data (precomputed text embeddings), not part of the graph. Also supports image-exemplar queries ("find things like this crop") and has a class-agnostic objectness score. Large ViT at 960×960 (3,600 patches); expect slow CPU-only execution. |
| Grounding DINO Tiny | The standard text→box grounder. Community ONNX builds: 719 MB fp32, 204 MB int8. Transformer with deformable attention; CPU only, likely slow. |
| Grounding DINO 1.5 Edge | Appears to be hosted-API only; no public weights found. |
| Florence-2 base | Grounding via autoregressive text generation — the shape of workload this hardware handles worst. |
| SAM 3 | Text phrase → masks for every match. Licence-gated weights; Qualcomm lists it as unsupported on mobile chipsets. |

**Vocabulary positions, for the long term:** fixed-class models (RF-DETR,
YOLOE exports, RAM++) name things from a list; SAM is class-agnostic; open-text
models (Grounding DINO, OWLv2, SAM 3) take any phrase at run time. The eventual
goal is open text, with the agent's instruction supplying the words. Version 1
accepts a very large built-in vocabulary (YOLOE prompt-free) as a step toward
that.

### 3.5 GIMP itself

GIMP 3 has no ML segmentation. Its classic tools (Fuzzy Select, Select by
Color, Intelligent Scissors, Foreground Select) are useful for **refining**
model masks, not producing labeled ones.

Third-party plugins were checked and rejected for this purpose:

- **Intel OpenVINO AI plugins** (GIMP 3, maintained): segmentation is
  DeepLabV3 (21 Pascal VOC classes) or a road-scene model. Output is one
  color-coded semantic layer — no instances, no per-object layers, no labels.
  Windows and Linux only. Its Stable Diffusion inpainting may matter later for
  the editing step.
- **GIMP-ML**: older versions had DeepLabV3 for GIMP 2.10; the current
  development branch has pivoted to OpenAI image APIs.

## 4. Acceleration: matching models to the TPU, GPU, or CPU

CPU is an acceptable fallback for every model in this lane. Acceleration is
pursued per model, by measurement, and is about more than latency: heavier
models (SAM 2.1's 1024×1024 encoder, OWLv2) would take seconds on CPU, CPU
inference competes with the other workers for cores, and an always-on node
benefits from the accelerators' efficiency.

### 4.1 The matching rule

The TPU and GPU are different chips that suit different models:

| | Edge TPU | GPU (Mali-G78) |
| --- | --- | --- |
| What it is | Fixed-function int8 matrix engine | General-purpose parallel float hardware |
| Precision | int8 only (measured) | fp32 / fp16 |
| Operators | A limited set — convolutions and the like; no LayerNorm, GELU, attention, or GridSample | Nearly anything, including transformer operators |
| Strength | Very fast and efficient on what it supports | Runs models the TPU can't |
| Weakness | Picky; unsupported partitions bounce to CPU | Less efficient per op; software paths here buggy so far |

So **each model is matched by architecture and size**: CNNs try the TPU first
(as int8); transformers try the GPU first (as fp16/fp32); small graphs with
dynamic shapes stay on CPU. Not every precision on every path — one first
choice, one second choice, and the CPU fallback.

### 4.2 Paths, by accelerator

**TPU** (int8 required):

1. **ORT + NNAPI** with `NNAPI_FLAG_CPU_DISABLED` (NNAPI's reference CPU
   device off; ORT's own CPU provider still runs unsupported nodes) on an int8
   static-quantized (QDQ) model. Proven on MobileNet through `cerebrate-graph`.
2. **TFLite + NNAPI** on an int8 LiteRT export — the longest-running proven
   path, if ORT's QDQ handling partitions badly.
3. **ORT + NNAPI with `NNAPI_FLAG_USE_FP16`** on a float model — on RF-DETR
   the driver accepted the ops and its compiler crashed. One retry per new
   CNN only; it shares the NNAPI service production uses, so don't hammer it.

Never use Ultralytics' `format="edgetpu"`: it targets the separate Coral
accelerator, and its compiled custom op cannot run through the Pixel's NNAPI.

**GPU** (fp16 / fp32):

1. **LiteRT 2.3.0 `CompiledModel` GPU** (OpenCL) — **the transformer GPU
   path.** Correct for float models; prepared DINOv2-small in 68.6 ms end to
   end at fp32 vs 344 ms CPU. Needs float I/O and the Section 4.5
   preparation. Its run call returns before the GPU finishes, so latency is
   only meaningful measured through a synchronizing output lock. Google's supported successor
   runtime. Recheck its known defects (uint8 I/O never written; per-channel
   broadcast multiply wrong; GPU-only compilation fails if any op must fall
   back) on each new release.
2. **Classic TFLite GPU delegate** (OpenCL, TFLite 2.16.1) — correct for CNNs
   (MobileNet, fp32 and fp16); rejects transformer graphs (expects 4-D
   tensors). On a frozen artifact: 2.16.1 is the last TFLite release published
   as an Android AAR.
3. **ORT + WebGPU** (Dawn on Vulkan) — **frozen**: its MatMul and Conv kernels
   crash the Mali GPU. The five-model comparison and 13 single-op reproductions
   justify not investing further until a concrete driver or ORT runtime change
   gives something new to test.

NNAPI is not a GPU path on this phone: it exposes only `google-edgetpu` and
`nnapi-reference`.

**CPU** (always available):

1. **ORT CPU** — correct and the measured baseline (RF-DETR 483 ms).
2. **ORT XNNPACK** — correct on fp32 RF-DETR but slower (1.3 s) with the
   current threading; tune before dismissing.

Every acceleration claim needs the catalog v4 evidence standard: correct
output compared element-wise against a CPU reference, and logcat partition
evidence showing what actually ran on the accelerator.

### 4.3 Per-model testing grid

| Model | Role | Architecture | Size | Ideal home | Try first | Then | Fallback |
| --- | --- | --- | --- | --- | --- | --- | --- |
| YOLOE-v8 seg prompt-free | Detect + label | Pure CNN | ~12–45M params, by variant | **TPU** | int8, ORT NNAPI | int8, TFLite NNAPI | CPU fp32 |
| YOLOE-11 seg prompt-free | Detect + label | CNN + one attention block (C2PSA) | ~10–35M params | TPU, if C2PSA is accepted | int8, ORT NNAPI | GPU, float `.tflite` | CPU fp32 |
| EdgeSAM encoder | Mask refinement | Pure CNN | Small (size to confirm) | **TPU** | int8, ORT NNAPI | GPU, float `.tflite` | CPU |
| SAM 2.1 Tiny encoder | Mask refinement | Transformer (Hiera) | 134 MB fp32 / 67 MB fp16 | **GPU** | LiteRT GPU, prepared | CPU fp32 | — |
| SAM 2.1 / EdgeSAM decoders | Box → mask | Mixed; dynamic shapes | ~21 MB fp32 | **CPU** | CPU | LiteRT GPU, if converted | — |
| RF-DETR Seg Nano | Fixed-class detector; GPU test case | Transformer | 123 MB fp32 | GPU | LiteRT GPU, prepared | CPU (483 ms, measured) | — |
| OWLv2 image tower | Open-vocabulary detection | ViT-B/16 at 960×960 | ~155M params | **GPU** | LiteRT GPU, prepared | CPU (slow) | — |
| DINOv2-small (test model, not in the pipeline) | GPU path proof | Transformer (ViT-S/14) | 22M params, 87 MB fp32 | **GPU** | **LiteRT GPU, prepared: 68.6 ms end to end at fp32, cosine 1.0 (measured)** | CPU (344 ms, measured) | — |
| OWLv2 text tower | Phrase → embedding | Small text transformer | Small | CPU, or precomputed offline | CPU | — | — |

Every model therefore needs **two exports**: int8 ONNX (or LiteRT) for the
TPU path and a float `.tflite` for the GPU path, each with its own CPU
reference outputs.
Every cell that runs also records: correctness against the reference, logcat
placement evidence, steady-state latency, worker RSS, and — for sustained
accelerated runs — thermal behavior (the TPU had a 2-hour soak in Stage 4D;
the GPU has never been tested under sustained load).

### 4.4 Deferred: RAM++

RAM++ (Swin-Large image tagger, 4,585 tags, ~873 MB int8, an estimated
1–2 GB resident) is **out of the grid for now**. YOLOE prompt-free's built-in
vocabulary appears to be the same 4,585 classes, so RAM++ would mostly
cross-check labels. Revisit it if YOLOE's labels prove too generic or
unreliable, or if an image-level inventory pass becomes useful on its own. If
revisited: try the classic TFLite GPU delegate first (a third-party LiteRT
port already splits it into four graphs with the deep Swin stage on CPU, after
fp16 miscomputed on a Mali GPU), then WebGPU, then CPU int8, and budget its
memory against the three graph slots.

### 4.5 Model preparation for the GPU

Learned on DINOv2-small
([litert-gpu-transformers](../hosts/cerebrate-pixel6/spikes/litert-gpu-transformers/README.md)).
Each rule removes something LiteRT 2.3.0's GPU path gets wrong or can't take
on this device:

1. **Float I/O.** No uint8 tensors at the model boundary — the GPU accelerator
   can't bind them and never writes the output.
2. **No ops that must fall back to CPU.** GPU-only compilation fails outright
   if any op can't go to the GPU, and a CPU/GPU split costs time. Freeze
   shape-dependent steps for the fixed input size (DINOv2: precompute the
   interpolated position embeddings; use the class token without expanding it),
   which removed `BROADCAST_TO` and `GATHER_ND`.
3. **No per-channel broadcast multiplies** (`[N, C] × [C]`). Fold them into the
   adjacent linear layer's weights (DINOv2's LayerScale into `o_proj` and
   `fc2`) — exact, since scaling a linear layer's output channels by λ is
   scaling its weight rows and bias by λ.
4. **Verify twice.** The prepared model against the unmodified original in
   PyTorch, then the converted `.tflite` against CPU on the device, with
   element-wise comparison — never trust a GPU run that merely completes.

Expect more rules as more architectures go through (SAM 2.1's Hiera encoder,
RF-DETR, OWLv2). Conversion is `litert-torch` (PyTorch → LiteRT) on the Mac.

Measuring a prepared model: latency only counts end to end — input copy,
run, and a synchronizing output lock — since LiteRT's GPU run call returns
before the work finishes. Accuracy is reported as worst-image and worst-token
cosine, max absolute error, relative L2 error, and a task-level check
(DINOv2: embedding similarity ranking; masks: IoU and boundary agreement after
thresholding). fp32 is the default; fp16 must pass the task-level check per
model. Each model test also takes a live temperature reading (`dumpsys
thermalservice`, "Current temperatures from HAL" section — not the cached one).

### 4.6 Standard model-preparation packaging (proposed)

**Revised 2026-10-24: start from what already exists.** Hugging Face
`litert-community` publishes GPU-clean LiteRT conversions of SAM 2.1
Hiera-Tiny (encoder and decoder), DINOv2-S/14 and RF-DETR-Seg-Nano, re-authored
with the same kinds of exact rewrites found here (LayerScale folding, ≤4-D
windowing, q/k/v split, baked position embeddings) plus others not yet hit
(overflow-safe LayerNorm, tanh-GELU, rank-4 rather than rank-3 attention,
large constants fed as inputs). The edge-compat project (`john-rocky/edge-compat`)
already provides most of the proposal below: a measured op-compatibility matrix
per LiteRT backend and version (with an *incorrect* status, not just
delegated/not), `edge-lint` (static pre-flight that predicts fallback and known
miscomputation from a `.tflite`), `edge-fix` (applies recorded rewrites), and
model cards with dated device runs. Its fleet has no Tensor G1 / Mali-G78.

So the standard becomes: **search published conversions and edge-compat
first; run `edge-lint` as pre-flight; adopt and validate (Section 4.7) before
writing anything.** The shape below applies only to gaps — models or rewrites
nobody has published — and to recording our own results:

- **A shared transform library**, one function per rewrite (for example
  `freeze_fixed_shape_inputs`, `fold_channel_scale_into_linear`). Each records
  the math, the runtime defect or limitation it works around (runtime,
  version, device), a "drop when" condition (recheck on each new LiteRT
  release), and a self-check that the rewrite is exact on random inputs.
- **A recipe per model**: source (repository + pinned revision), fixed input
  spec, the ordered transforms, the conversion target (float `.tflite` for the
  GPU, int8 for the TPU), and its validation spec (metrics, thresholds,
  task-level check, test inputs).
- **One runner on the Mac** that applies a recipe end to end: prepared vs
  original in PyTorch, converted vs PyTorch, then emits the artifact and a
  **manifest** — source revision, transforms and their versions, converter
  version, checksums, validation results.
- **Device validation** (`litert_e2e` + accuracy analysis) appends its
  CPU-vs-accelerator results and temperature reading to the same manifest.
- **The model catalog** records prepared artifacts with a `preparation` block
  (recipe, transforms, manifest checksum), so `stage-model` stages exactly
  what was validated and provenance travels with the artifact into the
  `segment` service's response.

The goal is that testing a new model is "write a recipe, run it, read the
manifest" — and that removing a rewrite once a runtime fixes the underlying
defect is a one-line recipe change, re-validated the same way.

### 4.7 Model conversion and GPU validation policy

Adopted 2026-10-24. Standing rules:

1. **Discover before converting.** Search for published LiteRT conversions,
   known GPU incompatibilities, and existing graph rewrites before
   implementing custom solutions.
2. **FP32 is the reference, not necessarily the deployment precision.**
   Validate numerical and task-level correctness against the original model.
   Pursue FP16 when its performance benefits justify the measured accuracy
   trade-offs.
3. **Distinguish weight, storage, compute, and accumulation precision.** FP16
   weights cannot be restored to FP32 fidelity by changing runtime compute
   settings. Rebuild from the original FP32 weights when necessary.
4. **Successful delegation does not establish correctness.** Evaluate
   converted models against original-model outputs, including downstream task
   metrics. Published conversions without accessible source transformations
   need particularly careful end-to-end validation.
5. **Measure synchronized end-to-end performance**, including buffer
   transfers, synchronization, and pre/post-processing as appropriate. Never
   treat asynchronous dispatch timing as inference latency.
6. **Preserve hardware-specific findings**: device, driver, LiteRT version,
   precision configuration, tensor shapes, numerical errors, and reproducible
   failures.
7. **Prioritize model validation and GPU optimization** (see Step 3's
   priority note). Correct CPU execution remains the baseline and fallback.

**Validation stages** for every adopted or prepared model:

| Stage | Comparison | Purpose |
| --- | --- | --- |
| 1. Graph equivalence | Rewritten PyTorch vs original PyTorch | Rewrites are faithful |
| 2. Conversion | LiteRT CPU vs rewritten PyTorch | No conversion defects |
| 3. Device execution | Pixel 6 GPU vs LiteRT CPU | No GPU-specific numerical problems |
| 4. Application correctness | Pixel 6 outputs vs original-model task results | Errors that remain don't matter for the task |

Published conversions without source can only go through stages 3 and 4, so
stage 4 against the original model carries their weight. For segmentation,
stage 4 means mask IoU, boundary agreement and flipped pixels across several
images and prompts, including small objects and thin structures.

**Failure classes**, kept distinct when diagnosing: *precision instability*
(overflow, underflow, accumulation, approximate nonlinearities — e.g. our SAM
decoder's fp16 collapse on an otherwise pixel-exact graph); *GPU kernel
defects* that occur at any precision (e.g. LayerScale's broadcast multiply;
the published decoder's rank-3 attention on a Pixel 8a); and *conversion or
rewrite errors* (e.g. a mis-indexed bias fold, caught by stage 1).

**Precision options in practice:** LiteRT exposes FP32, FP16, and one mixed
mode — FP16 storage with FP32 accumulation (`Fp16WithFp32Accum`) — globally,
not per op. Finer mixed precision means splitting a model into separately
compiled graphs.

Measured so far (DINOv2-small, end to end): FP32 68.6 ms, FP16 37.8 ms
(~1.8×), with FP16 degrading the worst token to cosine 0.961 and one image's
similarity ranking (7/8) despite an overall cosine of 0.9997. FP16 is worth
pursuing, but acceptance depends on task-level correctness, not aggregate
cosine.

Contributing reproducible G1 findings upstream (edge-compat's matrix and
cards) is opportunistic — after SAM runs correctly — and keeps measured
Pixel 6 results distinct from inferences drawn from other devices.

## 5. Version 1 pipeline

```text
image (from the Design Studio store, via Overmind)
   │
   ▼
YOLOE prompt-free seg (Pixel: TPU if it works, CPU otherwise)
   │  boxes + labels (4,585-class vocabulary) + coarse masks
   ▼
mask refinement, one box prompt per object (Pixel):
  EdgeSAM encoder on the TPU, or SAM 2.1 encoder on the GPU; CPU fallback;
  decoder on CPU
   │  refined masks at full resolution
   ▼
output contract (Section 7), stored next to the source image
   │
   ▼
GIMP import on the Mac worker: one named layer per object
```

### 5.1 Service interface direction

The pipeline above is an implementation detail. What the rest of Overmind —
and Buckminster in particular — should see is a **model-oriented** service,
not a framework-oriented one:

```text
segment(image, labels=["wall", "sofa", "window"])   # labels optional
  -> objects: [{label, score, box, mask}], plus provenance:
     which models ran, on which backend (TPU / GPU / CPU), with what settings
```

Whether that is served by YOLOE on the TPU, a SAM-family refiner on the GPU,
RF-DETR on CPU, or a combination is the service's business, and can change as
the grid in Section 4.3 fills in. The output contract (Section 7) is that
service's response; the GIMP import turns it into a group of named layers or
masks in the XCF, with source image, models, and settings preserved alongside
the project.

Layering: `cerebrate-graph` and its siblings stay **framework-oriented**
execution workers (one graph, tensors in, tensors out). The model-oriented
`segment` service composes them — where it lives (an MLServer model in the
guest, or an Overmind-side service calling `inference.home.arpa`) is decided
when Step 3 builds it, with the guest's ~1 GB of memory as the main
constraint for full-resolution mask handling.

## 6. Steps

Each step stops at its gate and records what was measured.

### Step 1 — General-purpose ONNX graph worker

`cerebrate-infer` accepts exactly one fixed-size input and returns one argmax.
Every model in this lane needs arbitrary named inputs and several outputs.

- **New worker `cerebrate-graph`** on the Android host: loads one `.onnx` model
  once, takes any set of named input tensors, returns every output tensor plus
  timing. Execution provider chosen at launch: `cpu`, `nnapi`, `nnapi16`,
  `xnnpack`, `webgpu` (Section 4). Same posture as its siblings: serial, one
  model per process, `SO_RCVTIMEO`, fixed port.
- **One model per process** (catalog v4 Section 8). Pipelines need several
  graphs resident at once — YOLOE, a SAM encoder, a SAM decoder — so the
  supervisor gets **three identical slots**, `graph1`–`graph3`, on fixed
  ports 8769–8771.
- **Dynamic shapes are fixed offline**, not by the worker. NNAPI needs static
  shapes; ORT's `make_dynamic_shape_fixed` tool pins them during model
  preparation on the Mac.
- **Generic MLServer adapter**, `cerebrate-graph`: a V2 request's tensors map
  one-to-one to the worker protocol and back. Model-specific pre- and
  post-processing stays out of the worker.

**Gate:** the worker reproduces CPU reference outputs on the Pixel for the
MobileNet canary and one real multi-output vision model (RF-DETR Seg Nano,
already local), reached both directly and through MLServer; `cerebrate-infer`
and the other production workers are unaffected.

### Step 2 — Two parallel tracks: GPU path (2A) and YOLOE on the TPU (2B)

The tracks are independent: 2B targets the TPU and doesn't wait on the GPU.
2A came this early because half the grid (SAM 2.1, RF-DETR, OWLv2) depends
on a working GPU path. Sequencing, per track:

- **GPU:** LiteRT 2.3.0 correctness → transformer conversion (DINOv2-small,
  then SAM 2.1) → GPU correctness → performance and model coverage →
  inference-worker integration. Conversion doesn't wait on the runtime choice:
  both GPU runtimes consume `.tflite`, so converted graphs are validated
  against CPU independently.
- **TPU:** YOLOE output trimming → int8 conversion → correctness and accuracy
  → actual TPU partitioning → performance.

#### Step 2A — GPU path characterization

1. **WebGPU on small, known graphs first**, each against its CPU reference:
   the SAM 2.1 decoder (fp32 and fp16, already in browser-perception), then
   DINOv2-small fp16 (44 MB, already local), then the SAM 2.1 encoder fp16,
   then RF-DETR again.
2. **Diagnose the device loss.** Establish whether it scales with graph size
   or single-dispatch length (a GPU watchdog), whether fp16 behaves
   differently from fp32, and what logcat and Dawn report. Verbose ORT
   logging shows which nodes WebGPU actually took.
3. **If WebGPU can't be made reliable**, characterize the classic TFLite GPU
   delegate and LiteRT 2.3.0 `CompiledModel` on the same models (converted to
   `.tflite`), with element-wise correctness checks against CPU — OpenCL is the
   stack LiteRT-LM already uses correctly here.
4. For whichever path works, a sustained-load run with thermal readings.
   Done once for DINOv2 (below); further stress tests deferred until the
   lane settles, with live temperature readings taken during each model test
   instead.
5. **A LiteRT engine in a worker**, so prepared `.tflite` models on the
   LiteRT GPU path are served through the supervisor and MLServer like
   everything else — either a second engine inside `cerebrate-graph` (same
   wire protocol, chosen by file extension) or a sibling worker. Item 3 has
   now shown transformers work, so this is the next design decision on this
   track. It must use requirement-based buffers.

**Status (2026-10-23):** items 1–2 done — WebGPU is correct only on graphs
without MatMul/Conv; those kernels crash the Mali GPU, so every real model
failed ([webgpu-op-bisect](../hosts/cerebrate-pixel6/spikes/webgpu-op-bisect/README.md)).
Item 3 done for the first transformer: the classic delegate is correct on
float MobileNet but rejects DINOv2
([tflite-gpu-delegate](../hosts/cerebrate-pixel6/spikes/tflite-gpu-delegate/README.md));
**LiteRT 2.3.0 runs a prepared DINOv2-small correctly: 68.6 ms end to end at
fp32 (cosine 1.0, task-level ranking identical) vs 344 ms CPU**
([litert-gpu-transformers](../hosts/cerebrate-pixel6/spikes/litert-gpu-transformers/README.md)).
Next: SAM 2.1's decoder and Hiera encoder through the same preparation and
check, a sustained-load thermal run (item 4), and the worker engine (item 5).

**SAM 2.1 sequence (adopted 2026-10-24):**

1. Published SAM encoder and v2 decoder (FP16) on the Pixel 6, evaluated
   against the original model, including mask IoU across eight samples with
   host-encoded box prompts.
2. Our prepared FP32 Hiera encoder on the Pixel 6 GPU, against the original
   reference, with synchronized end-to-end latency against the 10.2 s CPU
   baseline.
3. If the published FP16 models fail accuracy, try `Fp16WithFp32Accum`, then
   bisect the earliest numerical divergence.
4. An alternative FP32 decoder built from the published conversion script
   with the original FP32 weights, compared against ours (82 ms with a CPU
   split).

If the published FP16 v2 decoder also fails on the Pixel 6, that suggests a
device-specific problem but doesn't establish that G1 FP16 hardware is
responsible — distinguish driver behavior, graph structure, precision, and
input preparation before assigning a root cause. Then DINOv2 and
RF-DETR-Seg-Nano's published conversions go through the same evaluation.

**Gate:** at least one GPU path runs a transformer vision model correctly on
the Pixel with measured latency and thermal behavior — or a documented,
reproduced blocker for each path tried, leaving those models on CPU.

#### Step 2B — YOLOE prompt-free on the TPU

1. On the Mac, export a **YOLOE-v8** and a **YOLOE-11** prompt-free seg
   variant to fp32 ONNX; record reference outputs on a fixed image set;
   confirm the Pixel's CPU matches.
   **Prepare the output first:** the raw export's `output0` is
   `1×4621×8400` (4 box + 4,585 class + 32 mask-coefficient rows per anchor),
   about 155 MB of fp32 per image — unworkable to ship from the worker. Append
   a reduction to the graph during model preparation (best class index and
   score per anchor, keeping boxes and mask coefficients), shrinking it to
   about 1 MB; the appended ops are cheap and run on ORT's CPU provider.
   Box decoding, NMS, and mask assembly stay in a postprocessing step outside
   the worker.
2. Quantize each: `model.export(format="onnx", quantize=8, data=...)` with a
   few hundred representative photos (rooms first), not the COCO default.
   Confirm it is fully integer, not weight-only.
3. Run with `nnapi`; read logcat partition counts (does YOLO11's C2PSA block
   reach the TPU?); compare int8 against fp32 detections and labels.
4. One `nnapi16` attempt on each fp32 model (TPU path 3).
5. If ORT partitions badly, repeat with the int8 LiteRT export through
   TFLite + NNAPI (TPU path 2).
6. Once 2A has a working GPU path, YOLOE-11's float model on it, per the grid.

**Gate:** labeled detections on test rooms; measured TPU fraction and latency
for each path tried; accuracy cost of int8 recorded; a chosen YOLOE variant.

**Status (2026-10-23):** fp32 ONNX exports done (Ultralytics 8.4.184) for
`yoloe-v8s-seg-pf`, `yoloe-11s-seg-pf`, and `yoloe-26s-seg-pf` (55, 48, 49 MB).
All three are mostly convolution (74 / 98 / 115 Conv nodes). Attention-style
ops: v8 has a single Softmax (its box-decoding head); YOLOE-11 adds 2 MatMul
(the C2PSA block); YOLOE-26 has 4 MatMul. Input `images 1×3×640×640`;
outputs `output0 1×4621×8400` and mask prototypes `output1 1×32×160×160`.
Next: the output reduction above, then step 1's CPU check on the Pixel.

### Step 3 — Output contract and GIMP import

**Priority (2026-10-24):** Step 3 follows the model-validation workstream.
The immediate objective is several high-value vision models running correctly
and efficiently on the Pixel 6 GPU, reusable model-preparation procedures, and
documented hardware-specific findings — initially SAM 2.1, DINOv2 and RF-DETR.
The correct CPU paths remain fallbacks; the GIMP workflow is not the immediate
priority.

Write masks and labels in the Section 7 format; the Mac GIMP worker turns each
object into a named layer (source-layer copy plus layer mask, via
`gimp_run_python`), with label, score, box, and model stored as GIMP parasites
so they persist in the XCF.

**Gate:** a room photo becomes correctly named, independently editable layers
in a committed checkpoint.

### Step 4 — Mask refinement: SAM 2.1 Tiny versus EdgeSAM

Same job — YOLOE box in, precise mask out — so this is a comparison; only the
winner runs. Add an EdgeSAM adapter to browser-perception's
`PromptableSegmenter` contract and rerun its 126-object indoor benchmark with
box prompts. Time both encoders on the Pixel per the grid: EdgeSAM's CNN
encoder as int8 on the TPU, SAM 2.1's transformer encoder on whichever GPU
path Step 2A established (CPU if none); decoders on CPU.

**Gate:** a chosen refiner with measured quality and Pixel latency.

### Step 5 — OWLv2 characterization

Measure OWLv2's image tower on the Pixel — on Step 2A's GPU path, fp16 first,
with CPU as the comparison — with text embeddings precomputed for a large
vocabulary and the small text tower on CPU. Also test image-exemplar queries
for the cross-image use case.

**Gate:** a measured answer to whether OWLv2 is usable on the Pixel, and at
what latency — the bridge toward request-supplied vocabulary.

## 7. Output contract (draft)

For each source image, stored next to it, keyed by the image's SHA-256:

```json
{
  "schema_version": 1,
  "source_sha256": "…",
  "width": 1920,
  "height": 1080,
  "models": [{"id": "yoloe-11s-seg-pf@int8", "backend": "nnapi"}],
  "objects": [
    {"id": 1, "label": "armchair", "score": 0.87,
     "box": [x0, y0, x1, y1], "mask": "masks/0001.png", "refined_by": "sam2.1-hiera-tiny"}
  ]
}
```

Masks are 8-bit PNGs at source resolution. The contract is written once per
image and model version, so GIMP imports and repeated agent queries never
re-run inference.

## 8. Risks and open questions

- int8 quantization may lose accuracy; prompt-free labels may be generic
  ("lamp" for a sconce).
- YOLOE's coarse masks make refinement (Step 4) necessary, not optional.
- ORT's NNAPI provider is built on a deprecated Android API.
- **The GPU path is proven for one transformer so far** (prepared
  DINOv2-small on LiteRT 2.3.0). Other architectures may need new preparation
  rules or hit new GPU defects; models that can't be prepared stay on CPU, and
  EdgeSAM on the TPU remains the hedge for mask refinement.
- **LiteRT's GPU defects are worked around, not fixed**: uint8 I/O never
  written, per-channel broadcast multiply computed wrongly. A model that slips
  one past preparation fails silently unless the device-side check catches it
  — so every prepared model keeps its element-wise CPU comparison.
- The GPU path costs a `.tflite` conversion per model (ONNX → TFLite, or
  PyTorch → LiteRT); some transformer graphs may not convert cleanly.
- A hung GPU job wedges a serial worker (DINOv2 on WebGPU hung until the
  client timed out). Production must keep the supervisor's `STOP` and the
  adapters' request timeouts as the recovery path.
- The vendor Darwinn compiler crashed on an fp16 graph. It runs in a separate
  subprocess and production survived, but it shares the NNAPI service that
  `cerebrate-infer` uses — keep fp16 TPU attempts rare and re-verify
  production afterward.
- YOLO11's attention block may keep YOLOE-11 off the TPU; YOLOE-v8 is the
  hedge.
- Process-per-model raises memory overhead per slot; measure each worker's
  RSS (catalog `ram_mb` is still `null` for existing models) and budget the
  three graph slots together.
- Sustained GPU load is untested for heat.
- Ultralytics is AGPL-3.0 — acceptable for this home system; revisit if this
  lane is ever distributed.
- Reboot survival is unchanged: the supervisor still needs a manual relaunch
  after an Android reboot.

## 9. Not in this plan

Editing operations (removal, inpainting, compositing, recoloring);
open-text grounding as a production path; video; running inference on the Mac
or `overmind-01` as part of regular workflows; RAM++ (deferred, with revisit
conditions in Section 4.4).

## 10. Progress notes

- **2026-10-23** — Plan written. Step 1 started.
- **2026-10-23** — `cerebrate-graph` built (Android and macOS from one
  source) and verified on the Pixel by manual launch on a test port, outside
  the supervisor's ports; production workers untouched throughout. MobileNet
  (regenerated ONNX) reaches the TPU through the worker's `nnapi` backend,
  bit-exact, 3.4 ms. RF-DETR Seg Nano runs correctly on CPU at 483 ms
  (browser-perception's WASM figure on the M1 was ~1.46 s) and on XNNPACK at
  1.3 s; the TPU rejects it in fp32 and the vendor compiler crashes on it in
  fp16; WebGPU initializes on the Mali but lost the device on the first run.
  Production `cerebrate-infer` re-verified after the compiler crash. Found
  and fixed a Nagle stall (48 ms → 4.4 ms round trips). Supervisor slots and
  the generic MLServer adapter pass on the Mac (local MLServer 1.7.1);
  deploying them to the device (supervisor drain-and-swap, MLServer restart)
  is the remaining part of the Step 1 gate. Full numbers in
  [cerebrate-graph's README](../hosts/cerebrate-pixel6/cerebrate-graph/README.md#results-2026-10-23).
- **2026-10-23** — Plan revised after review. Acceleration is now matched to
  each model's architecture and size (Section 4: CNNs → TPU as int8,
  transformers → GPU as float, small dynamic graphs → CPU), with a per-model
  testing grid. Added LiteRT-LM's correct GPU result as evidence the OpenCL
  stack works. Corrected "YOLOE is a CNN": YOLOE-11 carries an attention
  block, so Step 2B tests a v8 and an 11 variant. Step 2 split into parallel
  tracks — GPU path characterization (2A) and YOLOE on the TPU (2B). RAM++
  taken out of the grid and deferred (Section 4.4).
- **2026-10-23** — **Step 1 gate met.** Supervisor drain-and-swap done
  (production workers restarted on the same configs within seconds;
  previous binary kept as `cerebrate-supervisor.prev`). The `cerebrate-graph`
  MLServer adapter deployed without restarting MLServer (repository `load`);
  `graph-canary` (MobileNet ONNX, `graph3`, CPU) returns class 795 through
  `inference.home.arpa`, and `cerebrate-infer`, `cerebrate-generate` and
  `cerebrate-gguf` all verified afterward. The guest's checkout now tracks
  this lane's branch until it is merged (production re-checked healthy
  afterward). Deploy details in the
  [supervisor](../hosts/cerebrate-pixel6/cerebrate-supervisor/README.md#deploy-record-2026-10-23)
  and [MLServer](../hosts/cerebrate-pixel6/mlserver/README.md#deploy-notes-2026-10-23)
  READMEs.
- **2026-10-23** — Step 2 started, both tracks. **2A:** ORT WebGPU is
  correct on the Pixel only for graphs without MatMul/Conv — a single-op
  bisection shows its MatMul and Conv kernels crash the Mali GPU
  (`VK_ERROR_DEVICE_LOST`), while the same models all run correctly on the
  Mac's Metal. The classic TFLite GPU delegate (OpenCL), untested here until
  now, runs float MobileNet correctly — 11.6 ms fp32 and 7.8 ms fp16 versus
  28.3 ms on CPU — and becomes the GPU path; transformers on it are next.
  **2B:** YOLOE v8/11/26 prompt-free seg exported to fp32 ONNX; graph
  inspection confirms v8 is attention-free and found the 155 MB-per-image raw
  output, now handled by an output-reduction preparation step. Production
  re-verified healthy before the tests began.
- **2026-10-23** — **LiteRT 2.3.0 correctness regression, and the first
  transformer on the GPU.** The unchanged `litert-compiled-correctness`
  harness on 2.3.0 reproduces the all-zero result on the quantized MobileNet.
  A C-API canary with a sentinel-filled output isolated it: the GPU
  accelerator can't bind the tested model's uint8 I/O tensors and never writes the output (host
  or native OpenCL buffers alike) — not a readback of GPU results. Float
  MobileNet is correct on the same path (cosine 0.99996; 8.3 ms run-call time
  vs 31.6 ms, not an end-to-end figure).
  DINOv2-small (`litert-torch` 0.10.0, converted in parallel per the revised
  sequencing) ran but was numerically wrong (cosine 0.026) — not precision,
  not the CPU/GPU split; depth and in-layer bisection traced it to LayerScale's
  per-channel broadcast multiply. Folding LayerScale into the adjacent linear
  layers and freezing the embedding step gives a fully GPU-resident model that
  is **correct: cosine 1.000000 at fp32** (see the next note for the
  corrected end-to-end latency). LiteRT
  2.3.0 `CompiledModel` becomes the transformer GPU path; model preparation
  rules recorded in Section 4.5; ORT WebGPU frozen; the model-oriented
  `segment` service direction recorded in Section 5.1.
- **2026-10-24** — **End-to-end verification, with a correction.** A
  synchronized benchmark over eight different real photos showed the earlier
  "5 ms" timed only LiteRT's run call, which returns before the GPU finishes.
  End to end, prepared DINOv2-small takes **68.6 ms at fp32 vs 344 ms on CPU
  (~5×)**, and 37.8 ms at fp16 (~9×). Against the unmodified PyTorch model,
  GPU fp32 matches the device CPU on every measure (relative L2 5.9e-6; worst
  token cosine 1.000000; task-level similarity ranking 8/8); fp16 does not
  (worst token 0.961, max abs error 2.58, ranking 7/8), so fp32 is the
  default. Sustained 5-minute load held a steady 68.5–69.4 ms; live
  temperature readings (after finding that the first poll read a stale cached
  section) showed the GPU plateau at 74–76 °C with no throttling. Further
  stress testing deferred; temperatures will be read during each model test.
  The uint8 finding is now scoped to the tested quantized MobileNet. Recorded
  the key lesson (Section 1) and proposed standard packaging for graph
  rewrites (Section 4.6).
- **2026-10-24** — **Published conversions found; validation policy
  adopted.** SAM 2.1 work found the SAM decoder correct on GPU at FP32 with a
  CPU split (82 ms vs 148 ms CPU; pixel-identical masks) but unusable at FP16
  (worst mask IoU 0.58), and the Hiera encoder at 10.2 s on CPU with only 69 of
  931 ops GPU-eligible. A prepared encoder (≤4-D windowing, q/k/v split, baked
  position embedding, folded no-memory bias) verified exactly at FP32 before
  `litert-community`'s published GPU-clean SAM 2.1, DINOv2 and RF-DETR
  conversions — with the same kinds of rewrites — and the edge-compat tooling
  came to light. Adopted: discover-before-converting, the FP32-reference
  precision policy and four validation stages (Section 4.7), the SAM
  evaluation sequence (Step 2A), and model validation ahead of Step 3.
