# Pixel 6 on-device vision experiments

Measured results from running vision models on Cerebrate's Pixel 6 — its CPU,
its Edge TPU (through NNAPI), and its Mali-G78 GPU — for the
[Segmentation and Labeling Lane](../../design-notes/Cerebrate%20Pixel%206%20%E2%80%94%20Segmentation%20and%20Labeling%20Lane.md).
Kept here so the runs can be revisited, rerun on new runtime releases, and —
where useful to others — published (for example as reports to the
[edge-compat](https://github.com/john-rocky/edge-compat) compatibility record,
whose test fleet has no Tensor G1 / Mali-G78).

- **[results.md](results.md)** — the run ledger: every configuration measured,
  with latency, accuracy, and verdict.
- The code that produced each result lives with the host, under
  [`hosts/cerebrate-pixel6/spikes/`](../../hosts/cerebrate-pixel6/spikes/) and
  [`hosts/cerebrate-pixel6/cerebrate-graph/`](../../hosts/cerebrate-pixel6/cerebrate-graph/);
  each ledger section links to it.

## Device and software

| | |
| --- | --- |
| Device | Pixel 6 (`oriole`), Tensor G1 (`gs101`), 8-core CPU (2× X1, 2× A76, 4× A55), 7.8 GB RAM |
| GPU | Mali-G78, driver `v1.r54p3-01eac0` (OpenGL ES 3.2) |
| OS | Android 17, `google/oriole/oriole:17/CP3A.260905.009/16091614:user/release-keys`, security patch 2026-09-05 |
| Runtimes | LiteRT 2.3.0 (`litert` + `litert-gpu` AARs, `CompiledModel` API); TFLite 2.16.1 (classic interpreter + GPU delegate); ONNX Runtime 1.30.0 (Android AAR: CPU, XNNPACK, NNAPI, WebGPU EPs) |
| Converters | `litert-torch` 0.10.0 (PyTorch → LiteRT), `tf2onnx` 1.16.1, Ultralytics 8.4.184 |

Workers run as native Android-host processes (the `shell` user), not in the
Debian guest, which has no accelerator access.

## Method

Every result follows the lane's validation policy (design notes, Section 4.7):

1. **Graph equivalence** — a rewritten model against the original in PyTorch.
2. **Conversion** — the converted model (LiteRT CPU) against PyTorch.
3. **Device execution** — the Pixel's accelerator against CPU.
4. **Application correctness** — device outputs against the **unmodified
   original model**, including task-level checks.

Rules that shaped the numbers:

- **Latency is end to end and synchronized**: input copy, run, and an output
  lock that waits for the device. LiteRT's GPU run call returns before the GPU
  finishes, so run-call-only timings are labelled as such and are not latency.
- **Accuracy is more than cosine**: worst-sample and worst-token cosine, max
  absolute error, relative L2 error, and a task metric — embedding similarity
  ranking for DINOv2; mask IoU at logit > 0, boundary agreement, flipped
  pixels, and best-mask agreement for SAM.
- **Inputs are real photos** (browser-perception's sample images), several per
  model, so cached or input-independent results would show up.
- **FP32 is the reference**; FP16 and mixed precision are reported but only
  accepted after passing the task metric.
- **Temperatures** are read from `dumpsys thermalservice`'s "Current
  temperatures from HAL" section (`G3D` is the GPU). The "Cached temperatures"
  section earlier in that output is stale, and `/sys/class/thermal` isn't
  readable as `shell`.
- **Failure classes** are recorded separately: precision instability, GPU
  kernel defects (wrong at any precision), and conversion/rewrite errors.

## Reproducing

Device access is through `overmind-01`'s wireless-ADB pairing
(`adb -s 192.168.68.60:5555`). LiteRT 2.3.0 libraries live in
`/data/local/tmp/litert-2.3.0/` on the device, separate from the TFLite 2.16.1
library production `cerebrate-infer` uses. Build and run instructions are in
each spike's README; the end-to-end benchmark is
[`litert_e2e`](../../hosts/cerebrate-pixel6/spikes/litert-gpu-transformers/bench.cc)
(`<model> <cpu|gpu|gpu+cpu> <req|host> <inputs.txt> <out_dir> <iterations> [sustain_s] [fp32|fp16|fp16acc32|default]`).
