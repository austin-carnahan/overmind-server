# migan-tpu

Can MI-GAN 512 Places2's convolutional generator run faster on the Pixel 6
Edge TPU than its validated GPU `fast` configuration (pure FP16, 79 ms, ≥ 41
dB in the infilled region; [published-litert-eval](../published-litert-eval/README.md))
while keeping its inpainting quality? A bounded research spike in the
[Segmentation and Labeling Lane](../../../../design-notes/Cerebrate%20Pixel%206%20%E2%80%94%20Segmentation%20and%20Labeling%20Lane.md),
using the fp16-relaxed TPU approach from [yoloe-tpu](../yoloe-tpu/) and
[edgesam-tpu](../edgesam-tpu/README.md). No serving work. Results:
[experiments/pixel6/results.md](../../../../experiments/pixel6/results.md).

**Answer: no — stopped after two fragments.** The TPU is slower than the GPU
on the first encoder block alone, and compiling the whole encoder exhausted
the phone's memory.

## Preparation (desktop)

- [`migan_prep.py`](migan_prep.py) — the original fp32 generator (the one
  extracted from the author-hosted `migan.onnx` for published-litert-eval)
  with its input fixed at `[1,4,512,512]` and simplified with onnxsim:
  equivalent to the original on the eight evaluation inputs.
- [`migan_fragments.py`](migan_fragments.py) — growing fragments from the
  input, onnx2tf to float32 TFLite (`-b 1 -ois 222:1,4,512,512`; without it
  the shapes stay dynamic and one conv becomes `FlexConv2D`). All builtin
  ops — CONV_2D, DEPTHWISE_CONV_2D, LEAKY_RELU, MINIMUM/MAXIMUM (±256
  clamps), RESIZE_NEAREST_NEIGHBOR, PAD, MUL, ADD — so nothing obviously
  unsupported. Every fragment matches the original on the desktop to ≤ 2e-5.

| Fragment | Ends at | Ops | Size | Output |
| --- | --- | --- | --- | --- |
| F1 | encoder block b512 | 22 | 0.1 MB | 256×256×128 |
| F2 | the whole encoder | 168 | 11.9 MB | 4×4×512 |
| F3 | synthesis b128 RGB | 329 | 23.7 MB | 128×128×3 |
| F4 | generator output | 425 | 28.0 MB | 512×512×3 |

## Device (fp16-relaxed NNAPI, pinned to `google-edgetpu`)

[`migan_fp16tpu_run.sh`](migan_fp16tpu_run.sh) runs one fragment under a
timeout and a memory floor (yoloe-tpu's guarded runner). GPU timings use
LiteRT 2.3 CompiledModel (`litert_e2e`), synchronized, output read included.

| Fragment | Config | Placement | Compile | E2E median | Max abs diff | Rel L2 |
| --- | --- | --- | --- | --- | --- | --- |
| F1 | TPU fp16-relaxed | 22/22 TPU | 2.6 s, −173 MB free | 34.1 ms | 3.9e-3 | 7.6e-4 |
| F1 | GPU FP16 | 22/22 GPU | — | 23.5 ms | 1.6e-2 | 1.7e-3 |
| F1 | GPU FP32 | 22/22 GPU | — | 39.7 ms | 9.5e-7 | 1.2e-7 |
| F2 | TPU fp16-relaxed | all ops accepted | **deadline exceeded** (~60 s) | — | — | — |

Reference: the original's tensor at the same point (output abs max 3.39),
two photos.

- **F1** — accurate (closer to the reference than GPU FP16), but 45% slower
  than GPU FP16 on a block whose GPU cost is mostly reading back its 32 MB
  output. The whole generator takes 79 ms on the GPU, so a TPU first block
  plus GPU remainder can't win, and the TPU only pays off if it runs most of
  the graph.
- **F2** — the driver accepted every op and started compiling. The compiler's
  memory grew to **3.09 GB RSS**, free memory fell from 3.24 GB to 840 MB,
  and the low-memory killer killed four cached apps before the driver's
  deadline ended the compile. Free memory recovered to 4.0 GB. The Debian VM
  and production MLServer survived (7/7 models ready, no restarts).

**The memory guard does not stop the compile.** It kills the bench client,
but the TPU compiler is a separate `system`-owned child of the darwinn HAL.
The shell user can't kill it, and it keeps running until the driver's
deadline. For comparison: EdgeSAM's 410-op encoder compiled in ≈1.2 GB, and
YOLOE's 188-op backbone in 410 MB. MI-GAN's 168-op encoder (mostly
512-channel convolutions) went past 3 GB.

## Not pursued

F3/F4 would compile more of the same graph, and F2 already exceeds what the
phone can safely compile, so they were not run. Other options:

- **int8** — compiles smaller, but the GAN's output quality would have to be
  re-validated from scratch; FP16 is already near the limit (41 dB).
- **Splitting the encoder** into several TPU graphs — each segment's 4–32 MB
  activations would cross back through host memory, and F1 already loses
  that trade.

Neither is worth the compile risk. MI-GAN stays on the GPU: `default` FP32
compute (147 ms) and `fast` FP16 (79 ms).
