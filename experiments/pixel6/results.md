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
