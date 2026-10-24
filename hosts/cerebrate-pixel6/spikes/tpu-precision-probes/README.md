# tpu-precision-probes

What the Pixel 6's Edge TPU (Tensor G1, NNAPI device `google-edgetpu`) can
compute, and how accurately — step 1 of the TPU investigation that followed
YOLOE's int8 results ([yoloe-tpu](../yoloe-tpu/README.md)). Tiny TensorFlow
graphs (the ops YOLO-family models use, plus attention) converted with the
classic TFLite converter, run with the TFLite NNAPI bench
(`../yoloe-tpu/tflite-nnapi-bench`, NNAPI pinned to `google-edgetpu`, NNAPI's
CPU fallback disallowed; `tpu16` adds the delegate's `allow_fp16`), compared
with the fp32 reference. Results:
[experiments/pixel6/results.md](../../../../experiments/pixel6/results.md).

## Capability matrix (2026-10-24)

| Precision | On the TPU | Accuracy vs fp32 | Speed |
| --- | --- | --- | --- |
| fp32, strict | **no** — driver supports 0 ops | — | — |
| fp16 weights (dequantized to fp32), strict | **no** — 0 ops | — | — |
| **fp32 with fp16 relaxation** (`allow_fp16`) | **yes** — every op tested (conv, SiLU, add, concat, max-pool, resize, strided conv, matmul, softmax) | fp16-level: single ops 1e-5–3e-4 rel L2; 24 conv+SiLU layers 9e-4 | conv block 2.9 ms vs 30.5 ms CPU; 24-layer ladder 20.7 ms vs 762 ms CPU (37×) |
| int8 (full integer) | **yes** | single ops bit-identical to TFLite's CPU int8 kernels | ~2.4× faster than fp16-relaxed (conv block 1.2 ms) |
| int8, dense/attention layers | **only with per-tensor weights** — NNAPI `FULLY_CONNECTED` rejects per-channel int8 weights (`TENSOR_QUANT8_SYMM_PER_CHANNEL`) | as int8 | attention block 0.66 ms |
| int16 activations (16×8) | **no** — the graph carries int64 biases, which NNAPI can't represent | — | — |

**Defect: max-pool with SAME padding pads with 0, not −∞** — in both int8
and fp16. Every large error of the conv probe is in the 2-pixel border where
the true maximum is ≤ 0, and the TPU returns exactly `max(true, 0)` there
([`tpu_probe_bisect.py`](tpu_probe_bisect.py) truncates the block stage by
stage; the error enters at the max-pool). Isolated max-pool on mostly-positive
input hides it. Exact workaround when the input has a known lower bound `m`
(SiLU: −0.2785): `maxpool(x + c) − c` with `c ≥ −m`. Relevant to YOLO's SPPF
(three chained 5×5 max-pools at 20×20, so the border effect reaches 6
pixels).

Compile cost scales mildly: 0.23 s (2 layers), 0.42 s (8), 1.36 s (24
layers, 72 ops, 3.6 MB); free memory never below 3.4 GB.

**Added by the EdgeSAM encoder** ([edgesam-tpu](../edgesam-tpu/README.md),
fp16 relaxation): ABS, DIV, EXP, MEAN over 256×256 (no overflow), stride-2
depthwise conv, 5×5 depthwise conv, DEPTH_TO_SPACE, STRIDED_SLICE +
CONCATENATION all run on the TPU; a LayerNorm (MEAN over the channel axis,
RSQRT) does not. **The compiler has a ~60 s deadline, and op order can
blow it**: a 1×1 conv + tanh GELU at 128×128×192 compiles in 0.66 s with
the linear term first and times out with x², x³ first (same ops, any
weights). Write elementwise formulas as single dependency chains. At
1024×1024 inputs compile time grows with graph size (430 ops ≈ 43 s).

## Scripts

- [`tpu_probe_models.py`](tpu_probe_models.py) — conv and attention blocks in
  fp32 / fp16w / int8 / int8pt (per-tensor) / int16x8, and the fp32 size
  ladder.
- [`tpu_probe_ops.py`](tpu_probe_ops.py) — single-op probes (sigmoid, SiLU,
  conv, max-pool, resize, strided conv, add + concat).
- [`tpu_probe_bisect.py`](tpu_probe_bisect.py) — the conv block truncated
  after each stage.
- [`tpu_probe_run.sh`](tpu_probe_run.sh) — one model in one mode on the
  device (runs on overmind-01): delegate placement, TPU driver verdict and
  compile status, latency, minimum free memory with a memory guard.
- [`tpu_probe_accuracy.py`](tpu_probe_accuracy.py) — every device output vs
  its fp32 reference.
