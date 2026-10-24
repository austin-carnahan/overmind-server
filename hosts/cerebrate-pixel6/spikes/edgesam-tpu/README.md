# edgesam-tpu

EdgeSAM's image encoder (RepViT-M1, 5.5M parameters, 1024×1024 → 64×64×256)
toward the Pixel 6 Edge TPU — the next TPU candidate after YOLOE in the
[Segmentation and Labeling Lane](../../../../design-notes/Cerebrate%20Pixel%206%20%E2%80%94%20Segmentation%20and%20Labeling%20Lane.md)
(Step 4's mask refiner). Results:
[experiments/pixel6/results.md](../../../../experiments/pixel6/results.md).

**Model:** EdgeSAM-3x, `chongzhou/EdgeSAM` rev `e0564124` (`edge_sam_3x.pth`,
sha256 `5a3e3261…6ece`), code
[chongzhou96/EdgeSAM](https://github.com/chongzhou96/EdgeSAM) at `d24d996`.
**Licence: S-Lab License 1.0 — non-commercial use only.** No LiteRT/TFLite
or TPU conversion is published (litert-community, Qualcomm and edge-compat
have none); the authors publish ONNX and CoreML only.

## The reference, and the authors' ONNX

The original model upsamples with **bicubic** interpolation (the training
config's default); the authors' ONNX/CoreML export scripts switch it to
bilinear. Their ONNX encoder faithfully exports that bilinear variant (2e-5),
but against the trained model it costs worst mask IoU 0.805, mean 0.9926, 4 of
132 masks below 0.95 — so it is not a valid starting point, and every
result here is judged against the bicubic PyTorch original
([`edgesam_reference.py`](edgesam_reference.py)): the eight lane photos with
YOLOE-v8s's **132 detections as box prompts** (the pipeline's actual shape:
YOLOE box → refined mask), one mask per box as the official demo prompts
boxes, masks compared per box ([`edgesam_common.py`](edgesam_common.py)).
The checkpoint loads only with `map_location` (CUDA tensors) and the repo's
loader uses `strict=False`; ours requires every encoder/decoder weight.

## Preparation (desktop; each step checked against the original)

1. [`edgesam_export.py`](edgesam_export.py) — our own ONNX export (bicubic).
   The one bicubic Resize (32×32 → 64×64; NNAPI has no bicubic) becomes an
   **exact construction** ([`bicubic_x2.py`](bicubic_x2.py), 5e-15 in
   float64): replicate padding as Slice + Concat, four 5×5 depthwise phase
   convolutions, channel concat, DepthToSpace. Stage 1: 5e-5 vs PyTorch, same
   as the plain export. (onnx2tf turned the open-ended slice `x[-1:INT64_MAX]`
   into an empty one — explicit indices.)
2. [`edgesam_gelu.py`](edgesam_gelu.py) — the 27 exact GELUs export as `Erf`,
   which onnx2tf makes `FlexErf` and NNAPI has no op for. Variants, task
   level on the desktop at fp32:

   | GELU | Ops each | Worst mask IoU | Mean | Flipped px | On the TPU |
   | --- | --- | --- | --- | --- | --- |
   | `erfpoly`: ½(x + \|x\|·erf(\|x\|/√2)), A&S 7.1.26 erf | ~21 | 1.0000 | 1.00000 | 3 | all ops supported, compile times out |
   | **`tanh`**: x·σ(x·(c₁ + c₃x²)), the tanh approximation | 6 | 0.9827 | 0.99892 | 6,116 | **compiles** |
   | `fit`: same chain, minimax-refitted c₁, c₃ | 6 | 0.9369 | 0.99863 | 5,083 | (not run) |

   `tanh` is written as **one dependency chain** — see the compiler defect
   below.

## Edge TPU findings (fp32 graphs, NNAPI `allow_fp16`)

- **Supported** (beyond the earlier probes): ABS, DIV, EXP, MEAN over
  256×256 (no fp16 overflow), stride-2 depthwise conv, DEPTH_TO_SPACE,
  STRIDED_SLICE + CONCATENATION, 5×5 depthwise conv.
- **Rejected:** the neck's LayerNorm (MEAN over the channel axis → RSQRT);
  the 19 ops from there on fell to the CPU. It would overflow in fp16
  anyway (it squares activations up to ~1,600).
- **Compiler defect — op order can push compilation past the driver's
  ~60 s deadline** ("Deadline exceeded: Failed to create compiled model",
  compiler status 3, up to 1.2 GB compile memory). The same eight ops — a
  1×1 conv 96→192 at 128×128 followed by the tanh GELU — compile in 0.66 s
  with the linear term computed first and time out with x², x³ and the cubic
  term first (the order onnx2tf emitted from `c₁x + c₃x³`); weights don't
  matter. Found by bisecting fragments down to that block and single-op
  probes ([`compile_probes.py`](compile_probes.py)). A GELU written as a
  chain leaves no order to choose. The near-exact GELU's timeout may be the
  same defect (not pursued: TPU fp16 error dominates anyway).
- Compile time grows with graph size at these resolutions: 54 ops 7.6 s,
  110 ops 10 s, 352 ops 37.7 s, 410–430 ops ~43 s, free memory never below
  2.2 GB (floor 1.5 GB).

Guarded sequence as in yoloe-tpu ([`edgesam_fp16tpu_run.sh`](edgesam_fp16tpu_run.sh):
hard timeout, memory floor, one attempt, stop on first failure);
fragments and bisects in [`edgesam_tpu_fragments.py`](edgesam_tpu_fragments.py).

## Results on the device (8 photos, 132 box prompts, vs the original)

[`edgesam_task_accuracy.py`](edgesam_task_accuracy.py) decodes device
embeddings with the original prompt encoder and mask decoder. Latency is
synchronized end to end (input write through output read).

| Encoder path | Latency | Worst mask IoU | Mean IoU | < 0.95 | Flipped px |
| --- | --- | --- | --- | --- | --- |
| CPU fp32 (XNNPACK) | 1.73 s | 0.9999 | 1.00000 | 0 | 14 |
| **GPU fp32** (LiteRT 2.3, `erfpoly` graph, 835/835 ops) | 267 ms | 1.0000 | 1.00000 | 0 | 1 |
| GPU fp16 + fp32 accumulation | 169 ms | 0.9199 | 0.99834 | 1 | 6,454 |
| TPU fp16-relaxed (`tanh`), neck on CPU (2 partitions) | 196 ms | 0.9441 | 0.99829 | 1 | 7,441 |
| **TPU stage (410/410 ops) → GPU fp32 neck (20 ops)** | **130 + 16 ms** | 0.9441 | 0.99830 | 1 | 7,393 |

TPU compile 43 s per load (GPU 0.7 s). On the TPU, the fp16 relaxation's own
error is ~5e-3 relative after the first stage; most flipped pixels come from
the GELU approximation (6,116 already at fp32).
