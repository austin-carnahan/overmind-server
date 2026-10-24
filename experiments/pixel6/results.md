# Pixel 6 run ledger

Newest sections last. Environment and method: [README.md](README.md). "E2E" =
synchronized end-to-end latency (median); "run call" = asynchronous dispatch
time only, not latency. Accuracy is against the unmodified original model
unless stated.

## 2026-10-23 — ONNX Runtime 1.30.0 through `cerebrate-graph`

Code: [cerebrate-graph](../../hosts/cerebrate-pixel6/cerebrate-graph/README.md).

| Model | Backend | Result | Time | Verdict |
| --- | --- | --- | --- | --- |
| MobileNet v1 quant (ONNX, from the cataloged `.tflite`) | CPU | bit-exact vs reference, class 795 | 9.7 ms inference | correct |
| MobileNet v1 quant | NNAPI → Edge TPU | bit-exact; 146/149 nodes on `google-edgetpu` | 3.4 ms inference, 4.4 ms round trip | **correct, accelerated** |
| RF-DETR Seg Nano fp32 (123 MB) | CPU | cosine 1.000000 vs Mac ORT reference | **483 ms** | correct |
| RF-DETR Seg Nano fp32 | XNNPACK | cosine 1.000000 | 1,334 ms | correct, slower |
| RF-DETR Seg Nano fp32 | NNAPI | TPU driver accepts 0 of 19 op types in fp32; session refuses to load | — | TPU takes no fp32 |
| RF-DETR Seg Nano fp32 | NNAPI + `USE_FP16` | driver accepts the ops; vendor Darwinn compiler crashes (tombstone in `libdarwinn_hal.so`) | — | compiler defect |
| RF-DETR Seg Nano fp32 | WebGPU | `[Device] is lost` ~11 s into the first run | — | see WebGPU below |

## 2026-10-23 — ONNX Runtime WebGPU EP (Dawn on Vulkan)

Code: [webgpu-op-bisect](../../hosts/cerebrate-pixel6/spikes/webgpu-op-bisect/README.md).
Every real model failed on the Pixel (SAM 2.1 decoder fp32/fp16, DINOv2-small
fp16, SAM 2.1 encoder fp16, RF-DETR) and passed on an M1 Mac's Metal (SAM
decoder 41 ms, DINOv2 fp16 22 ms, SAM encoder fp16 498 ms, RF-DETR 131 ms).

| Single-op graphs (fp32, model-sized tensors) | Result |
| --- | --- |
| Mul, broadcast Add, Softmax, LayerNormalization, Erf, ReduceMean, Transpose | correct |
| MatMul (3 shapes), Conv (3×3; 14×14 patch embed) | `VK_ERROR_DEVICE_LOST` |

**Kernel defect:** ORT WebGPU's MatMul/Conv kernels crash this Mali GPU.
Frozen pending a driver or ORT change.

## 2026-10-23 — Classic TFLite 2.16.1 GPU delegate (OpenCL)

Code: [tflite-gpu-delegate](../../hosts/cerebrate-pixel6/spikes/tflite-gpu-delegate/README.md).

| Model | Path | Result | Time (invoke) | Verdict |
| --- | --- | --- | --- | --- |
| MobileNet v1 float | CPU | reference | 28.3 ms | — |
| MobileNet v1 float | GPU fp32 | cosine 1.000000, same top class; 29/31 nodes | 11.6 ms | correct |
| MobileNet v1 float | GPU fp16 | cosine 0.998554, same top class | 7.8 ms | correct |
| DINOv2-small (`litert-torch`) | GPU | rejected at init: `CONCATENATION` needs 4-D; `BROADCAST_TO`, `GATHER_ND` unsupported | — | CNN-only delegate |

## 2026-10-23/24 — LiteRT 2.3.0 `CompiledModel` GPU (OpenCL, ML Drift)

Code: [litert-gpu-transformers](../../hosts/cerebrate-pixel6/spikes/litert-gpu-transformers/README.md).

| Model | Config | Result | Verdict |
| --- | --- | --- | --- |
| MobileNet v1 **quant** (uint8 I/O) | GPU, any buffer type | output buffer **never written** (sentinel intact) — the old "all-zero" result | uint8-I/O defect (this model) |
| MobileNet v1 float | GPU + CPU (2 `SQUEEZE` on CPU) | cosine 0.999961, same top class; 8.3 ms run call vs 31.6 ms | correct |
| DINOv2-small (`litert-torch`, unprepared) | GPU, any precision | cosine 0.026 | kernel defect, traced to LayerScale's `[N,C]×[C]` broadcast multiply |

**DINOv2-small, prepared** (embedding step frozen for 224×224, LayerScale
folded into `o_proj`/`fc2`; 621/621 ops on GPU), eight photos:

| Config | E2E | Worst token cosine | Max abs | Rel L2 | Similarity ranking | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| CPU (XNNPACK) | 344 ms | 1.000000 | 4.8e-4 | 6.3e-6 | 8/8 | reference |
| **GPU fp32** | **68.6 ms** (~5×) | 1.000000 | 7.1e-4 | 5.9e-6 | 8/8 | **correct** |
| GPU fp16 | 37.8 ms (~9×) | 0.961 | 2.58 | 3.1% | 7/8 | degraded |

Sustained (GPU fp32): 5 min at 68.5–69.4 ms medians per 10 s window; live
temperatures over 3 min: `G3D` 34 → 74–76 °C plateau, skin 31 → 40 °C,
thermal status 0, no GPU-frequency throttling.

## 2026-10-24 — SAM 2.1 Hiera-Tiny

Code: [sam21-gpu](../../hosts/cerebrate-pixel6/spikes/sam21-gpu/README.md).
Eight samples: four photos × two box prompts; masks judged against the
unmodified PyTorch model (whose outputs match browser-perception's ONNX export
exactly).

**Decoder (box prompt), our conversion of the transformers graph** — GPU-only
compilation fails (42/397 ops: 5-D reshapes/slices, `SELECT_V2`):

| Config | E2E | Worst mask IoU | Mean IoU | Pixels flipped (24 masks) | Same best mask | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| CPU | 148 ms | 1.00000 | 1.00000 | 0 | 8/8 | reference |
| **GPU + CPU, fp32** (3 GPU partitions) | **82 ms** | 1.00000 | 1.00000 | 0 | 8/8 | **correct** |
| GPU + CPU, fp16 | 66 ms | 0.578 | 0.895 | 5,718 | 8/8 | precision failure |

**Decoder (box prompt), GPU-clean re-authoring** adapted from
`litert-community/SAM2.1-Hiera-Tiny-Mask-Decoder` (revision `049c2500`; rank-4
attention, plain LayerNorm, 3-token box prompt, fp32 weights) — stages 1–2
exact (mask IoU 1.0, cosine 1.0); 328/328 ops on GPU:

| Config | E2E | Worst mask IoU | Mean IoU | Pixels flipped | Same best mask | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| CPU | 203 ms | 1.00000 | 1.00000 | 0 | 8/8 | correct |
| GPU fp32 | 87 ms | 0.000 | 0.011 | 117,162 | 5/8 | **kernel defect** — wrong at every precision |
| GPU fp16 + fp32 accumulation | 52 ms | 0.000 | 0.011 | 117,200 | 2/8 | kernel defect |
| GPU fp16 | 55 ms | 0.000 | 0.007 | 114,300 | 1/8 | kernel defect |

**Root cause (bisection, [`bisect_box_decoder.py`](../../hosts/cerebrate-pixel6/spikes/sam21-gpu/bisect_box_decoder.py)):
large baked constants.** With the `[1,256,64,64]` dense prompt, `[4096,256]`
positional table and output tokens baked into the graph, the GPU output is
already wrong after the first transformer block (keys cosine 0.70); fed as
inputs instead, the same graph is exact (cosine 1.00000, rel L2 4e-7). Same
class of defect `litert-community`'s RF-DETR card reports for this GPU
accelerator, now reproduced on the G1. (Our prepared DINOv2 bakes a 98K-element
constant without trouble, and the published fp16 decoder bakes these same
constants cast to fp16 without trouble — size and dtype may matter; not
established.)

**Decoder (box prompt), constants as inputs** (328/328 on GPU; the benchmark
rewrites 24 MB of embeddings and constants every iteration, ~20 ms of the
total — in use only the 3 KB prompt changes per box):

| Config | E2E | Worst mask IoU | Mean IoU | Pixels flipped | Same best mask | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| CPU | 203 ms | 1.00000 | 1.00000 | 0 | 8/8 | reference |
| **GPU fp32** | **80 ms** | **1.00000** | 1.00000 | **0** | 8/8 | **correct** |
| GPU fp16 + fp32 accumulation | 57 ms | 0.978 | 0.9946 | 314 | 8/8 | slight degradation |
| GPU fp16 | 60 ms | 0.559 | 0.895 | 5,756 | 8/8 | precision failure |

**Published v2 decoder, unmodified** (`litert-community`, rev `049c2500`;
425/425 on GPU), with its native 2-token point prompt (one positive click +
padding), eight samples (four photos × two clicks), against the original
model decoding the same clicks ([`prep_published_point.py`](../../hosts/cerebrate-pixel6/spikes/sam21-gpu/prep_published_point.py)):

| Config | E2E | Worst mask IoU | Mean IoU | Pixels flipped | Same best mask | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| CPU | 206 ms | 0.975 | 0.9988 | 18 | 8/8 | fp16-weight error |
| GPU fp32 compute | 69 ms | 0.975 | 0.9988 | 18 | 8/8 | fp16-weight error; no constants defect |
| GPU default (fp16) | 48 ms | 0.557 | 0.963 | 1,739 | 7/8 | precision failure |

Its card reports binary IoU 0.999 vs CPU at fp16 on a Pixel 8a; on this
Pixel 6, against the original model, pure fp16 fails. Across every SAM 2.1
formulation tried — two decoders, two encoders, ours and published — **pure
FP16 fails on the G1, FP16 with FP32 accumulation lands at worst mask IoU
≈ 0.98, and FP32 is exact.**

**Image encoder** (four photos; task metric = masks decoded by the original
fp32 decoder from the device embeddings, eight box prompts):

| Encoder | Config | E2E | emb2 rel L2 | Worst mask IoU | Mean IoU | Pixels flipped | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Ours, unprepared conversion | CPU | 10.2 s | — | — | — | — | reference speed |
| **Ours, prepared** (≤4-D windowing, q/k/v split, baked pos-embed, folded no-memory bias; 797/797 on GPU) | **GPU fp32** | **1.38 s** (~7.4×) | 2.8e-6 | **1.0000** | 1.0000 | **0** | **correct** |
| Ours, prepared | GPU fp16 + fp32 acc. | 0.77 s | 0.5% | 0.981 | 0.9956 | 316 | slight degradation |
| Ours, prepared | GPU fp16 | 0.64 s | 3.4% | 0.833 | 0.951 | 3,151 | precision failure |
| Published `litert-community` v2 fp16 (rev `d701df10`; 867/867 on GPU) | CPU | 9.4 s | 0.1% | 0.991 | 0.9986 | 67 | fp16-weight error |
| Published v2 fp16 | GPU fp32 compute | 1.31 s | 0.1% | 0.991 | 0.9986 | 67 | fp16-weight error |
| Published v2 fp16 | GPU fp16 + fp32 acc. | 0.74 s | 0.5% | 0.981 | 0.9940 | 395 | slight degradation |
| Published v2 fp16 | GPU default (fp16) | 0.62 s | 3.5% | 0.852 | 0.954 | 2,918 | precision failure |

The published card reports, on a Pixel 8a, that mask quality holds at fp16
(one center click). On this Pixel 6, judged against the original model across
eight box prompts, pure fp16 does not hold for either encoder.

**Decision (2026-10-24):** SAM 2.1 ships as two variants — **`default`**: FP32
(prepared encoder + constants-as-inputs box decoder; exact), and **`fast`**:
the same graphs at FP16 with FP32 accumulation (encoder 0.77 s, decoder 57 ms;
worst mask IoU ≈ 0.98). Pure FP16 is not offered.

## 2026-10-24 — Published DINOv2-S/14 (`litert-community/DINOv2-ViT-S14-LiteRT`, rev `f3be8d98`)

Code: [published-litert-eval](../../hosts/cerebrate-pixel6/spikes/published-litert-eval/README.md).
448×448, patch tokens `[1024, 384]`, eight photos, against the original timm
model (`vit_small_patch14_dinov2.lvd142m` at 448). Desktop LiteRT CPU: erf file
rel L2 0.08%, tanh file 0.46% (GELU approximation). All on GPU (864/864 tanh,
768/768 erf).

| File | Config | E2E | Worst token cosine | Max abs | Rel L2 | Similarity ranking | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| erf | CPU | 1.99 s | 0.99999 | 0.043 | 0.08% | 8/8 | fp16-weight error |
| **erf** | **GPU fp32 compute** | **253 ms** (~7.8×) | 0.99999 | 0.043 | 0.08% | 8/8 | **correct (fp16 weights)** |
| erf | GPU fp16 + fp32 acc. | 144 ms | 0.578 | 11.3 | 11.1% | 8/8 | precision failure |
| erf | GPU fp16 (default) | 119 ms | 0.557 | 9.3 | 12.0% | 7/8 | precision failure |
| tanh | CPU | 1.98 s | 0.99992 | 0.19 | 0.46% | 8/8 | GELU-approx error |
| tanh | GPU fp32 compute | 253 ms | 0.99992 | 0.19 | 0.46% | 8/8 | correct (approx GELU) |
| tanh | GPU fp16 + fp32 acc. | 140 ms | 0.581 | 11.3 | 11.1% | 8/8 | precision failure |
| tanh | GPU fp16 (default) | 120 ms | 0.548 | 9.5 | 12.2% | 7/8 | precision failure |

Unlike SAM, FP32 accumulation doesn't rescue FP16 here. The card's "device
fp16 vs desktop fp32: corr 0.996" (Pixel 8a) does not hold on this Pixel 6.
For comparison, our prepared DINOv2-small at 224 (FP32 weights) is exact at
68.6 ms with FP16 at 3.1% error.

## 2026-10-24 — Published RF-DETR-Seg-Nano (`litert-community/RF-DETR-Seg-Nano-LiteRT`, rev `8fee237c`)

Code: [published-litert-eval](../../hosts/cerebrate-pixel6/spikes/published-litert-eval/README.md).
Graph A (1293/1293 on GPU) → host step on its device outputs → graph B
(884/884 on GPU); eight photos, 25 detections from Roboflow's original
`rfdetr` 1.9.3 model. E2E = graph A + graph B (host step: a few ms).

| Config | Graph A | Graph B | Total | Matched | Same class | Worst box IoU | Worst mask IoU | Mean mask IoU | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Desktop LiteRT CPU | — | — | — | 25/25 (+1 extra) | 25 | 0.956 | 0.983 | 0.996 | fp16-weight error |
| CPU | 1.22 s | 274 ms | ~1.5 s | 25/25 (+1) | 25 | 0.956 | 0.983 | 0.998 | fp16-weight error |
| **GPU fp32 compute** | 239 ms | 114 ms | **~354 ms** | 25/25 (+1) | 25 | 0.956 | 0.983 | 0.998 | **correct (fp16 weights)** |
| **GPU fp16 + fp32 acc.** | 136 ms | 69 ms | **~205 ms** | 25/25 (+1) | 25 | 0.984 | 0.988 | 0.998 | **correct (fp16 weights)** |
| GPU fp16 (default) | 128 ms | 68 ms | ~196 ms | 24/25 | 24 | 0.544 | 0.548 | 0.988 | precision failure |

For reference, ONNX Runtime ran the original fp32 RF-DETR on this phone's CPU
in 483 ms (2026-10-23). Here FP16+FP32 accumulation is as good as FP32
compute; pure FP16 loses one detection and badly displaces another.

## 2026-10-24 — Published Depth Anything V2 Small (`litert-community/depth-anything-v2-small`, rev `178427e4`)

Code: [published-litert-eval](../../hosts/cerebrate-pixel6/spikes/published-litert-eval/README.md).
FP32 weights; fixed 518×686 input; eight photos against the original
Transformers checkpoint (rev `5426e4f0`). Desktop LiteRT CPU: FP32 file exact
(rel L2 8e-7); int8-weight file 2.5%. 494/494 ops on GPU. Depth metrics after
least-squares scale+shift alignment; order agreement on 200k random pixel
pairs per image.

| File | Config | E2E | Raw rel L2 | AbsRel | δ<1.25 (worst) | Order agreement (worst) | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| FP32 | CPU | 5.25 s | 1e-6 | 0.000 | 1.0000 | 1.00000 | reference |
| **FP32** | **GPU fp32** | **661 ms** (~7.9×) | 1e-6 | 0.000 | 1.0000 | 1.00000 | **correct** |
| **FP32** | **GPU fp16 + fp32 acc.** | **340 ms** | 0.66% | 0.005 | 0.9955 | 0.99978 | **near-identical** |
| FP32 | GPU fp16 | 291 ms | 2.0% | 0.022 | 0.984 | 0.9948 | moderate degradation |
| int8 weights | CPU | 3.03 s | 3.4% | 0.019 | 0.985 | 0.9988 | int8-weight error |
| int8 weights | GPU fp32 | 664 ms | 2.8% | 0.021 | 0.986 | 0.9993 | no GPU speed gain |

The card's warning that reduced GPU precision gives "substantially incorrect"
depth came from native WebGPU testing; on this Pixel's LiteRT GPU, pure FP16
degrades moderately and the mixed mode is near-identical.

## 2026-10-24 — Published MI-GAN 512 Places2 (`litert-community/MI-GAN-512-Places2-LiteRT`, rev `179a35d8`)

Code: [published-litert-eval](../../hosts/cerebrate-pixel6/spikes/published-litert-eval/README.md).
FP16 weights; 509/509 ops on GPU. Reference: the FP32 generator extracted from
co-author Andranik Sargsyan's `migan.onnx` (rev `406830d0`). Eight photos with
object-removal masks (top RF-DETR reference instance, dilated; 1.7–62% of the
image). Judged inside the removed region of the composite only; desktop LiteRT
CPU: 58–71 dB.

| Config | E2E | Worst PSNR | Mean PSNR | Worst SSIM | Worst rel L2 | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| CPU | 1.43 s | 58.4 dB | 64.4 dB | 0.9993 | 0.6% | fp16-weight error |
| **GPU fp32 compute** | **147 ms** (~9.8×) | 58.4 dB | 64.4 dB | 0.9993 | 0.6% | **correct (fp16 weights)** |
| GPU fp16 + fp32 acc. | 92 ms | 48.5 dB | 54.8 dB | 0.9983 | 1.9% | near-identical |
| GPU fp16 (default) | 79 ms | 41.2 dB | 49.5 dB | 0.9938 | 4.3% | visually near-identical |

The first model where pure FP16 holds up (PSNR ≥ 41 dB in the infilled region).
CPU worked here despite the card's note that XNNPACK declines this graph.

## 2026-10-24 — OWLv2 B/16 ensemble (our conversion, rev `cfd3195b`)

Code: [owlv2-gpu](../../hosts/cerebrate-pixel6/spikes/owlv2-gpu/README.md).
No published LiteRT conversion existed. Image tower and text tower as separate
graphs, vocabulary as data; host step computes logits and adds the box bias.
Stage 1 (prepared tower + host step vs original forward): logits ≤ 1.3e-5,
boxes ≤ 1.2e-7, objectness exact. Stage 2 (converted vs eager): cosine
1.000000 on every output. Eight photos, 24 text queries (household objects).

**Image tower** (354 MB fp32, `[1,3,960,960]`, 3,600 patches):

| Config | E2E | Logit max diff | Detections (ref 75) | Matched | Box IoU min | Score max diff | Top patch / query | Objectness top-100 | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CPU (XNNPACK) | 35.9 s | — | — | — | — | — | — | — | reference latency |
| GPU fp32, box bias on device | 4.51 s | 0.016 | 81 | 0 | — | — | 192/192 | 1.000 | **wrong boxes** (G1 defect) |
| **GPU fp32, box bias on host** | **4.53 s** (~7.9×) | 0.016 | 75 | 75 | 1.0000 | 0.0002 | 192/192 | 1.000 | **correct** |
| GPU fp16 + fp32 acc. | 2.38 s | 60.1 | 602 | 73 | 0.55 | 0.17 | 0/192 | 0.946 | fails |
| GPU fp16 | 2.01 s | 59.9 | 608 | 67 | 0.56 | 0.21 | 0/192 | 0.860 | fails |

The box defect: with `sigmoid(box_head(feats) + box_bias)` in the graph, the
GPU output has the box head's patch-0 value at every patch — x and y take only
the 60 grid values the baked `[1,3600,4]` bias supplies, w and h are constant.
Emitting the box logits and adding the bias on the host fixes it exactly.
G3D rose 27 → 63–66 °C over each 8-image GPU run (~36 s busy), back to
25–36 °C within minutes.

**Text tower** (254 MB fp32, token ids `[32,16]` int32 → `[32,512]`); three
batches of 32 phrases, against the original `get_text_features`:

| Config | E2E per 32 phrases | Placement | Worst row cosine | Nearest vocabulary entry same | Verdict |
| --- | --- | --- | --- | --- | --- |
| CPU (XNNPACK) | 1.08 s | 691/702 XNNPACK | 1.000000 | 96/96 | correct |
| **GPU + CPU** | **229 ms** | 662/702 GPU (int token ops on CPU) | 1.000000 | 96/96 | **correct** |
| GPU only | — | — | — | — | compile fails (int ops must fall back) |

**Task checks on the GPU fp32 image-tower outputs:**

- *Large vocabulary* — all 4,585 YOLOE prompt-free class names as queries:
  every one of the 355 patches the original scores ≥ 0.2 gets the same best
  label (355/355); best-logit max diff 0.015. Host step (3,600 × 512 ·
  512 × N, plus argmax) in the Pixel's Debian guest (numpy): 8 ms for 24
  queries, 110 ms for 1,203, 882 ms for 4,585.
- *Image exemplars* — three crops (laptop, dog, mirror) run through the image
  tower on the GPU; query = class embedding of the crop's highest-objectness
  box (transformers' rule), against `image_guided_detection` on all eight
  photos at score ≥ 0.9: 6/6, 34/34 and 39/39 detections matched, box IoU
  ≥ 0.9999, score diff ≤ 1e-4.

OWLv2 joins DINOv2 as FP32-only on the G1: both reduced-precision modes fail
(logit errors ~60, ~8× the detections, wrong top patch for every query).

## 2026-10-24 — Variant decisions (GPU models)

Same naming as SAM 2.1: **`default`** is FP32 compute (exact against the
original), **`fast`** a reduced-precision mode that passed the task checks.

| Model | `default` | `fast` |
| --- | --- | --- |
| SAM 2.1 Hiera-Tiny | FP32, 1.38 s encoder | FP16 + FP32 acc., 0.77 s (worst mask IoU ≈ 0.98) |
| RF-DETR-Seg-Nano (published) | FP32, ~354 ms | FP16 + FP32 acc., ~205 ms (all detections matched, mask IoU ≥ 0.983) |
| Depth Anything V2 Small (published) | FP32, 661 ms | FP16 + FP32 acc., 340 ms (depth order 99.98%) |
| MI-GAN 512 (published) | FP32 compute, 147 ms | FP16, 79 ms (≥ 41 dB in the infilled region) |
| DINOv2-S/14 | FP32 only | — (both reduced modes fail) |
| OWLv2 B/16 (ours) | FP32 only, 4.53 s image tower | — (both reduced modes fail) |
| YOLOE-v8s prompt-free (ours; added 2026-10-24) | FP32, 186 ms (exact: 132/132 detections, mask IoU 1.0000) | FP16 + FP32 acc., 108 ms (132/132 kept, plus one borderline extra; mask IoU ≥ 0.969, mean 0.996) |
| EfficientSAM3 RV-M (ours; added 2026-10-24, experimental) | FP32: vision 715 ms per image + grounding 3.28 s per prompt (exact) | FP16 + FP32 acc. grounding, 1.72 s per prompt (all detections kept, final-mask IoU ≥ 0.9986); vision stays FP32. Pure FP16 rejected (changes detections) |

## 2026-10-24 — EfficientSAM3 RV-M (our conversion, checkpoint rev `85b05896`)

Code: [efficientsam3-gpu](../../hosts/cerebrate-pixel6/spikes/efficientsam3-gpu/README.md).
Bounded spike: RV-M converted, EV-M inspected only, text prompts only. Three
graphs: vision, text, grounding (fusion encoder + decoder + heads). Stage 1
(wrappers vs the original `Sam3Processor` path): exact (0 difference);
prepared grounding vs original: logits ≤ 1.9e-4, mask logits ≤ 7.4e-3.
Stage 2 (converted vs eager): cosine 1.000000 for every output of every graph.

**Desktop CPU baseline** (Mac, eight photos, 24 prompts): masks follow object
boundaries closely; the correct phrase usually scores highest but competing
phrases also clear 0.5 (details in the lane plan's spike section). Per stage:
image backbone 1,070 ms (once per image), text encoder 114 ms (cacheable per
phrase), fusion encoder 774 ms, decoder 185 ms, heads 1,076 ms (≈ 2.0 s per
prompt, not cacheable — early fusion).

**Operator inspection:** RV-M backbone 340 ops, convolutions only (no
matmuls, nothing above 4-D; 42 unfused batch-norm multiplies). EV-M backbone
297 ops with 14 matmuls and 7 divisions (linear attention). Text encoder: int32
input and 32 ops above 4-D. Grounding: 2,642 ops; boolean padding-mask ops,
5-D box-bias tensors, ops on constants.

**Device, per graph** (G3D 25 → 42–51 °C across runs):

| Graph | Config | Placement | E2E | Accuracy | Verdict |
| --- | --- | --- | --- | --- | --- |
| Vision | CPU | 340/340 XNNPACK | 10.47 s | rel L2 2e-6 | reference |
| **Vision** | **GPU fp32** | **340/340** | **715 ms** (~14.6×) | rel L2 1.7–1.9e-6 (3 photos) | **exact, no preparation** |
| **Text** | **CPU** | 268/270 XNNPACK | **17 ms / phrase** | worst token cosine 1.000000 (25 phrases) | **exact** |
| Text | GPU only | 68/270 GPU-able | — | — | compile fails (5-D attention reshapes, int ops) |
| Text | GPU + CPU | 68 GPU / 202 CPU | 20 ms | cosine 1.000000 | no gain |
| Grounding, unprepared | CPU | 2,554/2,642 XNNPACK | 14.65 s | — | reference latency |
| Grounding, unprepared | GPU only | 1,056/2,642 GPU-able | — | — | compile fails (`BROADCAST_TO`, 5-D, ops on constants) |
| Grounding, unprepared | GPU + CPU | 1,056 GPU / 1,586 CPU | 4.0 s | — | mostly CPU |
| Grounding, first prepared build (queries/presence still constants, 6-layer scoring) | GPU | all ops on GPU | 3.27 s | logits pinned at −12, masks cosine ~0.5 | **wrong** (bisected) |
| **Grounding, prepared** | **GPU fp32** | **2,490/2,490** | **3.28 s / prompt** | 11 samples, 20 kept detections: same kept set, **mask IoU 1.0000, 0 flipped pixels**, kept score/box diff ~1e-7 | **exact** |
| **Grounding, prepared** | **GPU fp16 + fp32 acc.** | 2,490/2,490 | **1.72 s / prompt** | 11 samples: same kept set (incl. scores 0.504, 0.51), kept score diff ≤ 1.9e-3, box ≤ 9.3e-4, mask IoU ≥ 0.9987 | **near-identical** |
| Grounding, prepared | GPU fp16 | 2,490/2,490 | 1.73 s | 3 samples: one kept detection replaced (mask IoU 0.24), others ≥ 0.9907 | fails |

Grounding inputs on the device were the desktop FPN features (the device
vision graph matches them to rel L2 2e-6); the full on-device chain was not
run end to end.

**Grounding per stage on the GPU** (nested variants: encoder only, + decoder
and scoring, + heads): fusion encoder 2,627 ms fp32 / 1,321 ms mixed (80%;
self-attention over 5,184 image tokens), decoder + scoring 264 / 153 ms,
segmentation heads 386 / 244 ms. On the desktop CPU the heads were the
largest piece; on the Pixel GPU the convolution-heavy heads are cheap and the
encoder dominates.

**Bisect record (G1 defects found):** (1) layer 0's self-attention over the
200×256 learned query embeddings (a weight used as an activation, folded by
the converter into a constant attention-value operand) computed wrongly —
cosine 0.86 — fixed by feeding the queries and presence token as inputs;
(2) the scores came out wrong with every input exact — first attributed to
the reshape into `[6,1,200,1]`; the minimal reproduction (below) pinned it to
a batch-broadcast `BATCH_MATMUL` `[6,1,200,256]`×`[256,1]` — fixed by scoring
only the last decoder layer (the only one the outputs use), at batch 1.
Ops on constants (`SIGN`, `MEAN`, `FLOOR_DIV`) were rejected rather than
miscomputed. One transient run failure (OpenCL `-14`, a kernel execution
error) on an intermediate build did not recur on the final graph.

**Per image + per prompt, Pixel GPU:** 715 ms vision once per image, text
17 ms per phrase on CPU (cacheable), then 3.28 s (fp32) or 1.72 s (mixed) per
prompt.

## 2026-10-24 — EfficientSAM3 RV-M: phone-native chain, variants, reproductions, caching

Code: [efficientsam3-gpu](../../hosts/cerebrate-pixel6/spikes/efficientsam3-gpu/README.md),
[g1-gpu-repros](../../hosts/cerebrate-pixel6/spikes/g1-gpu-repros/README.md).

**Phone-native chain** ([`esam3_e2e_accuracy.py`](../../hosts/cerebrate-pixel6/spikes/efficientsam3-gpu/esam3_e2e_accuracy.py)):
every stage on the phone, each fed the phone's own outputs — vision on the GPU
(FP32, 340/340) → text on the CPU → grounding on the GPU (2,490/2,490); host
steps only image preprocessing, tokenization and the padding mask. The same
11 samples (20 detections, including scores 0.504 and 0.510) against the
original model on the desktop CPU, at two levels: raw (kept set, scores,
boxes, 288×288 masks) and final (the processor's own post-processing —
bilinear upsample to the photo, sigmoid > 0.5 — applied to the device
outputs). The host post-processing reproduces the processor's saved masks
exactly (10/10 checkable samples), so the final level compares against the
original pipeline itself.

| Variant | Detections retained | Kept score diff | Kept box diff | Final masks (photo resolution) | Verdict |
| --- | --- | --- | --- | --- | --- |
| **default** (grounding FP32) | **20/20** | ≤ 2.4e-6 | ≤ 2.4e-7 | IoU 1.0000; 1 pixel of 6,376,448 differs (a value at the 0.5 threshold) | **exact** |
| **fast** (grounding FP16 + FP32 acc.) | **20/20** | ≤ 1.6e-3 | ≤ 9.3e-4 | IoU ≥ 0.9986; 643 of 6,376,448 pixels differ | **near-identical** |

**Variants registered** (decision 2026-10-24): `default` = FP32, `fast` =
grounding at FP16 with FP32 accumulation (vision FP32 in both), pure FP16
rejected. Both pass the phone-native chain — the condition set for
production promotion. Not yet in `models/catalog.yaml`: its schema requires
a serving worker (binary and port), and no worker serves the LiteRT GPU
models yet.

**Minimal reproductions** of the two silent G1 miscomputations (relative L2
against the PyTorch reference; full table in the repro README):

| Case | CPU | GPU |
| --- | --- | --- |
| `BATCH_MATMUL` `[6,1,200,256]` × `[256,1]` (one op) | 3.1e-7 | **1.2** |
| same values at batch 1 | 2.9e-7 | 2.9e-7 |
| attention block, values from a constant `[201,1,256]` (15 ops) | 5.0e-7 | **0.87** |
| same block, that tensor as an input | 3.3e-7 | 3.6e-7 |
| `BATCH_MATMUL` with a constant `[8,201,32]` operand, alone / after softmax | ≤ 1.4e-7 | ≤ 2.1e-7 |

The first defect was originally attributed to the reshape into
`[6,1,200,1]`; the reproduction corrects that to the batch-broadcast matmul
(the converter re-fuses a 2-D rewrite into it).

**Caching the first fusion layer** ([`esam3_cache_check.py`](../../hosts/cerebrate-pixel6/spikes/efficientsam3-gpu/esam3_cache_check.py)):
the dependency was checked before any restructuring. The fusion encoder adds
no text to the image features before its layers (`add_pooled_text_to_img_feat`
is off for the image model), and each pre-norm layer runs norm → self-attention
over image tokens only → residual → cross-attention to the prompt → FFN. So
layer 0's self-attention is prompt-independent — confirmed on the original
model: its post-self-attention state is bit-identical across "laptop", "bed"
and "person" on the same photo, while the layer's output after
cross-attention differs by up to 1.8. That block alone on the GPU: 364 ms
FP32 / 190 ms mixed (rel L2 1.3e-7 / 3.1e-4), matching its FLOP share (11.8%
of the fusion encoder: 30.2 GFLOP of 255). Caching it per image would save
about 11% per prompt (3.28 → ~2.9 s default, 1.72 → ~1.53 s fast) for a
one-time per-image cost of the same and 5.3 MB of state. Everything after it
is prompt-dependent (from layer 0's cross-attention on, every image token
carries the text). Not implemented.

## 2026-10-24 — YOLOE prompt-free (v8s, 11s): step 1 and first TPU attempts

Code: [yoloe-tpu](../../hosts/cerebrate-pixel6/spikes/yoloe-tpu/README.md).
Ultralytics 8.4.184 fp32 ONNX exports, prepared (reduced outputs, Split →
Slice, DFL as a 2-D softmax — all exact: 0 difference from the unmodified
ONNX). Same-input check: on 640×640 letterboxed photos the ONNX export and
the original `.pt` give identical predictions. Task evaluator (Ultralytics'
NMS and masks, class-agnostic as YOLOE's predictor sets) reproduces the `.pt`
predictions on 8/8 photos for both models.

| Model | Config | Result |
| --- | --- | --- |
| v8s | CPU (ORT) | **727 ms**; outputs cosine 1.000000 vs desktop (best-class index differs on 85/8,400 low-score anchors — near-ties) |
| 11s | CPU (ORT) | **667 ms** |
| v8s | `nnapi` (fp32) | Edge TPU driver: **0 / 292 ops supported** — as expected, no strict fp32 |
| v8s | `nnapi16` (fp32 relaxed to fp16), unprepared head | driver: 291 / 292 supported; DFL softmax rejected (`axis == -1 \|\| axis == input_rank - 1`) |
| v8s | `nnapi16`, prepared | driver: **288 / 288 supported**; Edge TPU compiler **crashed** (SIGSEGV in `libdarwinn_hal.so`) |
| 11s | `nnapi16`, prepared | driver: **425 / 425 supported** (C2PSA attention included); compiler crashed the same way |
| v8s | `nnapi16`, class head removed | compile timed out (`Deadline exceeded`) |
| 11s | `nnapi16`, class head removed | **memory exhaustion: the low-memory killer killed the Terminal app and the Debian VM** |

With fp16 relaxation the Edge TPU *accepts* every op of both models
(earlier "the TPU takes no fp32 work" holds for strict fp32 only), but its
compiler can't build them: it crashes with the 4,585-class head and runs out
of time and then memory without it.

**Incident (04:26:54):** during the last compile the phone's low-memory
killer ran a mass kill (167 processes in three minutes) that included
`com.android.virtualization.terminal` and its `VmService` — the Debian VM,
MLServer and the reverse tunnels went down; the Android-side workers kept
running. Restored at 04:32 with the documented relaunch
(`adb shell am start -n com.android.virtualization.terminal/.new2.ui.MainActivity`):
VM booted, tunnels and `cerebrate-mlserver` auto-started, all five models
READY, `inference.home.arpa` 200. Outage ≈ 7 minutes. TPU compile
experiments stopped pending a decision on how to protect the VM.

## 2026-10-24 — YOLOE prompt-free on the GPU; int8 backbone partition (desktop)

Code: [yoloe-tpu](../../hosts/cerebrate-pixel6/spikes/yoloe-tpu/README.md).
Task check against Ultralytics' predictions from the original `.pt` on the
eight letterboxed photos (v8s 132 detections, 11s 112): matched one-to-one by
class (of 4,585) and box IoU ≥ 0.5; "any label" counts reference detections
found at IoU ≥ 0.5 regardless of label.

**GPU (float LiteRT, our `litert-torch` conversion; stage 2 cosine 1.000000):**

| Model | Config | Placement | E2E | Matched | Box IoU min | Mask IoU min / mean | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| v8s | CPU (ORT) | — | 727 ms | (raw outputs = desktop) | | | reference latency |
| v8s | CPU (LiteRT XNNPACK) | 296/300 | 1,676 ms | 132/132 | 1.0000 | 1.0000 / 1.0000 | correct, slow |
| **v8s** | **GPU fp32** | **300/300** | **186 ms** (~3.9× ORT CPU) | **132/132** | 1.0000 | 1.0000 / 1.0000 | **exact** |
| v8s | GPU fp16 + fp32 acc. | 300/300 | 108 ms | 132/132 (+1 extra borderline) | 0.965 | 0.969 / 0.996 | near-identical |
| v8s | GPU fp16 | 300/300 | 98 ms | 127/132 | 0.942 | 0.940 / 0.992 | degraded |
| 11s | CPU (ORT) | — | 667 ms | | | | reference latency |
| **11s** | **GPU fp32** | **399/399** | **179 ms** (~3.7×) | **112/112** | 1.0000 | 1.0000 / 1.0000 | **exact** |
| 11s | GPU fp16 + fp32 acc. | 399/399 | 107 ms | 111/112 | 0.940 | 0.916 / 0.996 | one detection lost |
| 11s | GPU fp16 | 399/399 | 90 ms | 109/112 | 0.812 | 0.785 / 0.992 | degraded |

No preparation was needed for the GPU (unlike the transformers), and the
best-class `ARG_MAX` over 4,585 classes runs on the GPU too. G3D 25 → 43 °C.

**int8 backbone + neck (TPU partition), desktop ORT emulation, fp32 head:**
the partition chained back is exact; quantized (QDQ, uint8 activations,
int8 per-channel weights) with indoor COCO calibration:

| Backbone | Matched | Any label | Score max diff | Mask IoU mean |
| --- | --- | --- | --- | --- |
| v8s fp32 | 132/132 | 132 | 0.0000 | 1.0000 |
| v8s int8, MinMax (300 photos) | 80/132 | 104 | 0.31 | 0.932 |
| v8s int8, percentile 99.999 (32 photos) | 101/132 | 119 | 0.23 | 0.956 |
| 11s fp32 | 112/112 | 112 | 0.0000 | 1.0000 |
| 11s int8, MinMax | 71/112 | 102 | 0.29 | 0.947 |
| 11s int8, percentile | 85/112 | 104 | 0.32 | 0.961 |

int8 costs roughly a fifth to a quarter of exact-label detections even with
better calibration; many of the losses are label flips between near-synonyms
among 4,585 classes rather than missed objects. TPU compile of the int8
backbone (9 MB) not yet run — waiting for the VM watchdog on overmind-01.

## 2026-10-24 — YOLOE backbone on the Edge TPU (int8)

Code: [yoloe-tpu](../../hosts/cerebrate-pixel6/spikes/yoloe-tpu/README.md).
All runs with the VM watchdog active and a memory guard (minimum free memory
3.57–3.65 GB: the small int8 backbone compiles without memory pressure).

**ORT + NNAPI on the QDQ int8 backbone:** ORT's NNAPI provider can't take
quantized `Sigmoid` (180 node units — every SiLU), `Slice` (64) or `MaxPool`
(8): 55 partitions, 503/695 nodes; the TPU then rejects float tensors at the
partition boundaries (`input.type != TENSOR_FLOAT32`) and the load fails.
Not viable without rewriting SiLU.

**TFLite + NNAPI (TPU path 2), fully-integer TFLite from litert-torch PT2E**
(YOLOE-v8s backbone + neck; 212 ops, all int8 — after spelling SiLU out as
`x * sigmoid(x)`; as `nn.SiLU` it stayed float):

| Config | Placement | Load (incl. compile) | Median |
| --- | --- | --- | --- |
| TFLite CPU (int8 kernels) | — | 4 ms | 132 ms |
| **TFLite + NNAPI → Edge TPU** | 76/212 nodes delegated in 7 partitions; driver 200/236 NNAPI ops supported, compiled (status 0) | 1.47 s | **90 ms** |

The 36 rejected ops are the graph's 24 int8→int8 `QUANTIZE` requantizations
(where branches with different scales meet, mostly at concatenations) and
their neighbours: the TPU only takes `QUANTIZE` from float input
(`RET_CHECK input.type != TENSOR_FLOAT32`, ×24).

**Accuracy problems, two separate ones:**
- *Quantization (PT2E):* feature cosine vs fp32 — PyTorch's own quantized
  model 0.97 / 0.90 / 0.88 (80², 40², 20²), after conversion to TFLite 0.75 /
  0.57 / 0.43. Too lossy to use (the ORT QDQ int8 kept 119/132 objects on the
  desktop; this one was not usable through the head at all).
- *TPU vs CPU int8:* the TPU's outputs differ from TFLite's CPU int8 kernels
  in 33% of feature values, by up to 29 quantization steps — far beyond
  rounding.

YOLOE-11's C2PSA attention (batched matmul, softmax) is not quantized by this
PT2E quantizer and stays float. Status: the Edge TPU *can* run a YOLOE int8
backbone (compiled, 90 ms partly on TPU) but not yet *correctly* or fully;
the GPU fp32 path (186 ms whole model, exact) remains the reference.

## 2026-10-24 — YOLOE backbone on the Edge TPU: TensorFlow full-integer (bounded round)

The one bounded round decided on 2026-10-24: rebuild the int8 backbone with
TensorFlow's classic full-integer quantizer (onnx2tf 1.28.8, TensorFlow
2.19.0; per-channel weights; 150 indoor calibration photos) and measure TPU
placement, latency and task accuracy once; stop unless it runs fully on the
TPU within a few detections of fp32.

The resulting YOLOE-v8s backbone + neck is exactly what the TPU wants: 182
ops, all int8 (NHWC, int8 I/O), **no requantizations**, no float ops.

| Config | Placement | Load | Median | Matched (of 132) | Any label | Mask IoU mean |
| --- | --- | --- | --- | --- | --- | --- |
| fp32 backbone (reference) | — | — | — | 132 | 132 | 1.000 |
| int8, desktop | — | — | — | 82 | 100 | 0.939 |
| int8, phone CPU (TFLite) | — | 4 ms | 125 ms | 82 (identical to desktop) | 100 | 0.939 |
| **int8, Edge TPU** | **182/182 ops, 1 partition**; driver 182/182; compiled (status 0) | 2.34 s | **8.7 ms** | **84** | **105** | 0.922 |

(The backbone's int8 feature maps go through the fp32 head on the desktop
for scoring.) Minimum free memory during the compile: 3.4 GB.

- **The Edge TPU runs the whole YOLOE backbone in 8.7 ms** — ~14× the CPU's
  int8 kernels, and for scale, ~21× faster than the GPU's 186 ms for the
  *whole* fp32 model.
- **The TPU's arithmetic is not the problem:** its int8 values differ from
  TFLite's CPU kernels in 42% of positions (up to 62 steps), yet task
  accuracy is equal or slightly better (84 vs 82 matched).
- **int8 quantization is:** about a third of exact-label detections are lost
  (feature cosine vs fp32 0.59–0.87). YOLOE's prompt-free head picks among
  4,585 near-synonymous classes, so small feature shifts flip labels; most
  objects are still found (105/132 at any label).

Gate not met → YOLOE stays on the GPU (fp32, exact, 186 ms). YOLOE-11 not
taken through this round. For future TPU candidates: the toolchain that works
is fp32 ONNX → onnx2tf full-integer → TFLite + NNAPI pinned to
`google-edgetpu` (whole graph on the TPU, single partition); what decides a
model's fit is how well it tolerates int8 — fixed-vocabulary or
coarse-output models are better candidates than a 4,585-class
open-vocabulary head.

## 2026-10-24 — Edge TPU precision probes (TPU investigation, step 1)

Code: [tpu-precision-probes](../../hosts/cerebrate-pixel6/spikes/tpu-precision-probes/README.md)
(capability matrix there). Tiny graphs, classic TFLite converter, TFLite +
NNAPI pinned to `google-edgetpu`.

| Probe | Mode | TPU placement | Median | Rel L2 vs fp32 |
| --- | --- | --- | --- | --- |
| conv block | CPU fp32 | — | 30.5 ms | 7e-7 |
| conv block | TPU strict fp32 / fp16 weights | 0 ops supported | — | — |
| conv block | **TPU fp16-relaxed** | 9/9 | **2.9 ms** | 3.7e-2 (max-pool padding defect; 3.8e-4 before the max-pool) |
| conv block | CPU int8 | — | 8.8 ms | 2.0e-2 |
| conv block | TPU int8 | 9/9 | **1.2 ms** | 4.2e-2 (same defect) |
| attention block | CPU fp32 | — | 1.22 ms | 2e-7 |
| attention block | **TPU fp16-relaxed** | 13/13 | **0.83 ms** | 1.0e-3 |
| attention block | TPU int8 (per-channel dense weights) | rejected (`FULLY_CONNECTED`: per-channel int8 not accepted) | — | — |
| attention block | TPU int8, per-tensor weights | 13/13 | 0.66 ms | 4.6e-2 (= CPU int8) |
| either | TPU int16 activations | not delegated (int64 biases) | — | — |
| 24 × conv+SiLU (160×160×64) | CPU fp32 | — | 762 ms | 2e-6 |
| 24 × conv+SiLU | **TPU fp16-relaxed** | 72/72, compile 1.36 s | **20.7 ms** | **9.2e-4** |

Single ops (sigmoid, SiLU, conv, strided conv, max-pool, resize, add +
concat) on the TPU: int8 bit-identical to TFLite's CPU int8; fp16-relaxed
1e-5–3e-4. The conv block's error enters at its 5×5 max-pool: **the TPU pads
SAME max-pooling with zeros** (all large errors in the 2-pixel border where
the true maximum is ≤ 0; TPU output exactly `max(true, 0)`). Exact
workaround for inputs with a known lower bound: `maxpool(x + c) − c`.

## 2026-10-24 — YOLOE-v8s int8 accuracy diagnosis (TPU investigation, step 2)

Code: [`yoloe_int8_diagnose.py`](../../hosts/cerebrate-pixel6/spikes/yoloe-tpu/yoloe_int8_diagnose.py).
The onnx2tf full-integer backbone (desktop TFLite CPU kernels; the TPU
matched them at task level) → fp32 head, against Ultralytics' 132 reference
detections.

- **Input mapping is exact:** the letterboxed image (k/255) through the int8
  input (scale 1/255, zero point −128) and back differs by 6e-8.
- **Detections:** 83 matched, **17 label flips, 32 missed.**
  - *Misses are borderline detections pushed under the threshold:* all 32
    have an int8 score below 0.25 for the original label at the original
    anchor (median 0.15); the original model's confidence on them was low to
    begin with (median 0.30, 26/32 below 0.35; matched detections median
    0.60).
  - *Flips concentrate where the original model was undecided:* its top-1 vs
    top-2 class margin is smaller for flipped detections (median 0.085)
    than for matched ones (0.135). Many are near-synonyms (quilt → bedding,
    toilet paper → paper towel, baby bottle → bottle); some are not
    (sugar bowl → ashtray, sponge → diamond, handbag → hassock). The original
    label ranks 2nd in 5 of 17 flips, 6th or worse in 6.
- **Layer by layer (134 int8 tensors vs their float32 twins):** no single
  catastrophic layer — error accumulates with depth: cosine ~0.95–0.99 at
  160×160 and 80×80, 0.87–0.91 at 40×40, ~0.80–0.85 at 20×20 (the SPPF
  output ~0.80) and in the neck (lowest ~0.77). The biggest per-op drops are
  at the SiLU **multiplies** (x · sigmoid(x)), whose outputs are re-quantized
  per tensor; the sigmoids themselves stay at 0.95–0.99.

