# efficientsam3-tpu

Can EfficientSAM3 RV-M's image encoder move from the Pixel 6 GPU (FP32,
715 ms; [efficientsam3-gpu](../efficientsam3-gpu/README.md)) to the Edge
TPU with fp16-relaxed inference, keeping the CPU text encoder and the
validated GPU grounding? A bounded spike in the
[Segmentation and Labeling Lane](../../../../design-notes/Cerebrate%20Pixel%206%20%E2%80%94%20Segmentation%20and%20Labeling%20Lane.md):
small fragments only, no full-encoder compile (MI-GAN showed that the TPU
compiler's memory escapes our watchdog; [migan-tpu](../migan-tpu/README.md)).
Results: [experiments/pixel6/results.md](../../../../experiments/pixel6/results.md).

**Answer: no-go for TPU acceleration of the encoder.** The trunk doesn't
compile at the model's 1008×1008 input. Where it does compile (1024×1024),
it is half the GPU's speed and needs 775 MB of compiler memory for 60 ops.
The trunk is also the precision-sensitive half. The neck runs well on the
TPU, but the GPU's own FP16 + FP32-accumulation mode matches that speed and
already passes validation. The useful result is a GPU-only configuration:
**trunk FP32 + neck FP16/FP32 acc., ≈ 519 ms (−28%), 20/20 detections on
the 11-sample chain** — a candidate variant, not yet registered.

## The vision graph

| Part | What | MACs | GPU FP32 | GPU FP16 + FP32 acc. | GPU FP16 |
| --- | --- | --- | --- | --- | --- |
| Trunk | RepViT-M1.1 (1008 → 32×32×512) + head (1×1 → 1024, GELU, 3×3 1024 → 1024) + bilinear to 72×72 | ~36 G | 244 ms | 137 ms | 110 ms |
| Neck | SAM 3 simple FPN: 2×2 stride-2 transposed convs up to 288×288, then 256-channel 1×1 + 3×3 per level (the 36×36 level is discarded) | 106 G | 504 ms | 276 ms | 251 ms |
| Whole graph | | | 723 ms | 409 ms | 349 ms |

Synchronized end to end (input write through output read; LiteRT 2.3
CompiledModel, median of 8). Two-thirds of the time is the neck, mostly its
3×3 256 → 256 conv at 288×288 (49 GMACs). EdgeSAM's encoder is the same
family (RepViT-M1 at 1024 → 64×64), but it is narrower and has no FPN at
this scale.

## Precision first (no TPU needed)

Which parts tolerate fp16-level error? Each row is the phone-native chain
(vision → grounding on the GPU, text features from the original) scored
with [`esam3_e2e_accuracy.py`](../efficientsam3-gpu/esam3_e2e_accuracy.py)
on the 11 validation samples (20 reference detections, two of them at
scores 0.504 and 0.510).

| Vision | Grounding | Kept | Max kept score diff | Worst final-mask IoU | Flipped px (of 6.38 M) |
| --- | --- | --- | --- | --- | --- |
| FP32 (registered `default`) | FP32 | 20/20 | 2.4e-6 | 1.0000 | 1 |
| FP32 (registered `fast`) | FP16 + FP32 acc. | 20/20 | 1.6e-3 | 0.9986 | 643 |
| whole graph FP16 + FP32 acc. (FPN rel L2 5.5e-3) | FP32 | **19/20** | 1.1e-2 | — (laptop 0.510 lost) | 1,766 on the rest |
| whole graph FP16 (FPN rel L2 1.1e-2) | FP32 | **19/20** | 1.6e-2 | — (same) | 6,896 on the rest |
| tanh GELU everywhere, FP32 (desktop) | FP32 (desktop) | 20/20 | 2.1e-3 | 0.9994 | 266 |
| **trunk FP32 + neck FP16 + FP32 acc.** | FP32 | **20/20** | 9.2e-4 | 0.9997 | 120 |
| **trunk FP32 + neck FP16 + FP32 acc.** | FP16 + FP32 acc. | **20/20** | — | 0.9987 | 687 |

**The trunk is the sensitive part.** At reduced precision across the whole
vision graph, the borderline laptop detection moves 10× further than
reduced-precision grounding moves it, and falls under 0.5. The neck at
reduced precision costs almost nothing. The tanh GELU rewrite
(edgesam-tpu's TPU form) is harmless on its own.

## TPU fragments (fp16-relaxed NNAPI, pinned to `google-edgetpu`)

[`esam3_tpu_prep.py`](esam3_tpu_prep.py) builds fragments (ONNX → onnx2tf
float32, tanh GELU written as one chain). Each fragment matches PyTorch on
the desktop to ≤ 2e-6.
[`esam3_fp16tpu_run.sh`](esam3_fp16tpu_run.sh) runs one at a time (migan-tpu's
guarded runner). Error is rel L2 against the fragment's PyTorch output, on
photos 0 and 3.

| Fragment | Ops | TPU compile | Compile memory | TPU E2E | TPU rel L2 | GPU FP32 | GPU FP16 + FP32 acc. (rel L2) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| B0: stem (3×3 s2 conv, GELU, 3×3 s2 conv), 1008 → 252×252×64 | 10 | 0.7 s | 3 MB | 18.9 ms | 7.0e-4 | 23.1 ms | 15.1 ms (1.2e-3) |
| B1: + RepViT block 1 | 30 | **fails** (status 1) | 27 MB | — | — | — | — |
| B2: + block 2 | 45 | **fails** | 98 MB | — | — | — | — |
| T1: + block 3 | 60 | **fails** | 144 MB | — | — | 47.4 ms | 35.6 ms (7.2e-3) |
| T1K: T1 at 1024×1024 (photo zero-padded) | 60 | 12.8 s | **775 MB** | **93.0 ms** | 4.3e-3 | — | — |
| PSE: block 1's SE module alone (MEAN over 252×252, two 1×1 convs, sigmoid gate) | 5 | **fails** | 15 MB | — | — | — | — |
| PDW: block 1's RepVGG depthwise alone | 6 | 0.6 s | 0 MB | 17.9 ms | 8.3e-4 | — | — |
| PCM: block 1's channel mixer alone | 9 | 2.7 s | 104 MB | 20.5 ms | 4.0e-4 | — | — |
| N1S: neck conv_1x1 + conv_3x3 (256 → 256), central 144×144 | 2 | 1.2 s | 149 MB | 30.2 ms | 1.5e-4 | 47.8 ms | 33.5 ms (1.4e-3) |
| N1: the same pair at 288×288 | 2 | not compiled | — | — | — | 152.8 ms | 97.9 ms |

Every op was accepted by the driver ("Ops supported = N, not supported =
0"); the failures are compile failures (`CompilerSpawner ... Status: 1`,
"Failed to create compiled model with HAL API"), not op rejections.

- **Size-specific compiler failure:** the SE module's global average (MEAN
  over 252×252) doesn't compile. edgesam-tpu's MEAN over 256×256 does, and
  so does the same 60-op fragment at 1024. Padding the input to 1024 is not
  an exact fix, because the SE means would include the padding.
  Equivalent forms (two 1-D means, average-pool, a ones-convolution) were
  not tried.
- **Slow on RepViT's first stage:** at 1024 the TPU takes 93 ms for the stem
  and three blocks, against 47 ms for the GPU at FP32. Each block part
  costs ~18–20 ms alone, so stage 1 of RepViT-M1.1 at this resolution is a
  poor TPU fit.
- **Compile memory grows fast at high resolution:** T1K needed 775 MB for 60
  ops. EdgeSAM's whole 410-op encoder needed ≈1.2 GB, and RepViT-M1.1's
  stages are wider. A full-trunk compile is uncharacterized and would be
  attempted only with approval.
- **More accurate than the GPU's mixed mode** on every fragment (1.7–9×
  lower error) — e.g. the neck pair at 1.5e-4 vs 1.4e-3.
- **The neck fits the TPU:** 1.6× faster than GPU FP32 on the N1S pair,
  with a small compile. But the GPU's mixed mode is about as fast (33.5 vs
  30.2 ms) and already passes the 11-sample chain.

## Assessment

| Option | Vision latency (estimate) | Quality | Risk |
| --- | --- | --- | --- |
| Whole encoder on the TPU | trunk ≥ GPU's (stage 1: 2× slower) + neck; no gain | likely fails (trunk at fp16-level) | doesn't compile at 1008; compile memory uncharacterized |
| GPU trunk FP32 → TPU neck | ≈ 244 + ~250 ms (from N1S scaling) + 21 MB hand-off ≈ 500 ms | very likely passes (TPU neck error < the GPU mixed neck's, which passes) | neck compile at 288×288 uncharacterized; transposed convs need a rewrite |
| **GPU trunk FP32 → GPU neck FP16 + FP32 acc.** | **≈ 519 ms (measured, summed)** | **passes** (20/20, both grounding variants) | none new: same runtime and graphs, split in two |

First-prompt latency (vision + 17 ms text + grounding):

| Grounding | Vision as today | Split-precision vision |
| --- | --- | --- |
| `fast` | 2.46 s | ≈ 2.26 s (−8%) |
| `default` | 4.02 s | ≈ 3.82 s |

Later prompts on the same image don't change, because grounding (1.72 /
3.28 s per prompt) dominates. A TPU neck would only matter for freeing the
GPU while grounding runs (pipelining across images), not for one request's
latency.

**Recommendation: no-go for full-encoder TPU acceleration.** Register the
GPU split-precision vision as a candidate configuration instead (needs your
approval; no serving change at this stage).

**If a TPU neck is still wanted later**, these are the next safe
boundaries, one compile each, stopping at the first large footprint:

1. N1 at full 288×288 — 2 ops; N1S used 149 MB, so roughly 4× is expected.
2. Neck level 0 alone, with each 2×2 stride-2 transposed conv rewritten
   exactly as a 1×1 conv to 4·C_out + DEPTH_TO_SPACE (non-overlapping
   kernel; DEPTH_TO_SPACE is proven on this TPU), plus its tanh GELU.
3. Levels 1 and 2.

Never compile the whole neck first.

**Validation for any new vision configuration:** run the phone-native chain
on the eight photos. Trunk on the GPU at FP32, then the candidate neck, then
grounding on the GPU at FP32 and at FP16 + FP32 acc., with text features
from the CPU encoder. Score the 11 samples with `esam3_e2e_accuracy.py`
against the original model. Pass: the same kept set (20/20, including the
0.504 and 0.510 detections), and final-mask IoU and flipped pixels within
the registered `fast` levels (≥ 0.998, ~10³ pixels). Record the GELU
rewrite in the preparation metadata as an approximate functional rewrite.

## Scripts

- [`esam3_tpu_prep.py`](esam3_tpu_prep.py) — steps `gelu` (the tanh-GELU
  desktop chain), `split` (trunk and neck LiteRT graphs for the GPU),
  `frag` (T1, N1), `bisect` (B0–B2, T1K), `probe` (PSE, PDW, PCM, N1S).
- [`esam3_fp16tpu_run.sh`](esam3_fp16tpu_run.sh) — the guarded single-fragment
  TPU run (on overmind-01).
- GPU runs use `litert_e2e` from
  [litert-gpu-transformers](../litert-gpu-transformers/README.md); the
  chains reuse efficientsam3-gpu's device inputs and grounding graph.
