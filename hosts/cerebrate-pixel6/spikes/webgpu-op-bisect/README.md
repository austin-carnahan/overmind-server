# webgpu-op-bisect

Step 2A of the
[Segmentation and Labeling Lane](../../../../design-notes/Cerebrate%20Pixel%206%20%E2%80%94%20Segmentation%20and%20Labeling%20Lane.md):
why does ONNX Runtime's WebGPU execution provider (Dawn on Vulkan, in the
stock ORT 1.30.0 Android AAR) fail on every real model on this Pixel 6?

## Result (2026-10-23)

**WebGPU's MatMul and Conv kernels crash the Mali GPU
(`VK_ERROR_DEVICE_LOST`); its element-wise, normalization, and Softmax
kernels run correctly.** Every vision model is mostly MatMul and Conv, so ORT
WebGPU is blocked on this device for now.

Real models, through [`cerebrate-graph`](../../cerebrate-graph/README.md)'s
`webgpu` backend, compared against ORT CPU references:

| Model | Pixel (Mali, Vulkan) | M1 Mac (Metal), control |
| --- | --- | --- |
| `times2` (one Mul) | correct, bit-exact | correct |
| SAM 2.1 decoder fp32 / fp16 | "Failed to wait for the operation" ~12 s in | correct, 41 / 35 ms |
| DINOv2-small fp16 | worker hung; client timed out at 120 s | correct, 22 ms |
| SAM 2.1 encoder fp16 | device lost | correct, 498 ms |
| RF-DETR Seg Nano fp32 | device lost ~11 s in | correct, 131 ms |

So the models are fine; the failure is specific to this GPU stack. And it is
not graph size or job length: the SAM decoder takes 41 ms on the Mac.

[`make_ops.py`](make_ops.py) builds single-operator fp32 graphs sized like
DINOv2/SAM tensors, with ORT CPU references; [`op_loop.sh`](op_loop.sh) runs
each on the Pixel's WebGPU (from `overmind-01`, test inputs in the guest at
`/home/droid/cg-test`):

| Works (correct vs reference) | Fails (`VK_ERROR_DEVICE_LOST`) |
| --- | --- |
| Mul (384 and 2M elements), broadcast Add, Softmax, LayerNormalization, Erf, ReduceMean, Transpose | MatMul (`1×257×384 · 384×384`, `1×4096×256 · 256×256`, batched `1×6×257×64 · 1×6×64×257`), Conv (3×3 64→64; 14×14 stride-14 patch embed) |

With `CEREBRATE_GRAPH_VERBOSE=1`, ORT logs to logcat: the MatMul program
(`MatMul[...|4-4-1|...]`, an 8×8 tiled vec4 kernel) starts, then
`WebGPU device lost (1): vkWaitForFences failed with VK_ERROR_DEVICE_LOST`.
Every ORT WebGPU shader declares `enable subgroups;`, including the working
Softmax and LayerNorm ones, so the declaration alone isn't the trigger;
logcat truncates the MatMul shader before its body, so whether it calls
subgroup functions is unconfirmed.

None of ORT's `ep.webgpuexecutionprovider.*` options switch the MatMul/Conv
implementation. Options not pursued, for a later pass:

- Hand ORT a `WGPUDevice` created without the `subgroups` feature
  (`webgpuInstance`/`webgpuDevice` options) — tests the subgroup hypothesis
  directly; needs Dawn's API in the worker.
- Re-test on each newer ORT release.

The GPU fallback in the plan — the classic TFLite GPU delegate over OpenCL —
works correctly on this device; see
[tflite-gpu-delegate](../tflite-gpu-delegate/README.md).
