# tflite-gpu-delegate

Step 2A of the
[Segmentation and Labeling Lane](../../../../design-notes/Cerebrate%20Pixel%206%20%E2%80%94%20Segmentation%20and%20Labeling%20Lane.md),
the GPU fallback after ORT WebGPU's MatMul/Conv kernels crashed the Mali GPU
([webgpu-op-bisect](../webgpu-op-bisect/README.md)): does the classic TFLite
GPU delegate (`TfLiteGpuDelegateV2`, OpenCL) compute correctly on this
Pixel 6? It has never been tested here; the GPU path that was —
LiteRT `CompiledModel` — returns all zeros
([litert-compiled-correctness](../litert-compiled-correctness/README.md)).

[`main.cc`](main.cc) runs one float `.tflite` model on CPU (the reference),
then through the delegate at full fp32 precision and with fp16 precision loss
allowed, and compares every output element-wise (cosine, max/mean absolute
difference, argmax, all-zero check). Inputs are a deterministic pattern, so
any float model works.

## Result (2026-10-23)

**Correct.** The first verified-correct vision inference on this device's
GPU. Float MobileNet v1 (`mobilenet_v1_2018_02_22/mobilenet_v1_1.0_224.tflite`,
sha256 `a6e60eb9…39f9`), 20 runs:

| Path | Median | Load | vs CPU |
| --- | --- | --- | --- |
| CPU, 4 threads | 28.3 ms | 1 ms | reference |
| GPU fp32 | 11.6 ms | 1.66 s | cosine 1.000000, max abs diff 2.8e-7, same argmax |
| GPU fp16 | 7.8 ms | 1.41 s | cosine 0.998554, max abs diff 4.5e-3, same argmax |

The delegate took 29 of 31 nodes; the two it left are `SQUEEZE` (trivial
reshapes). Load time is OpenCL kernel compilation, which the delegate can
cache (`serialization_dir` / `model_token` options) — not tried yet.

What this does and doesn't establish: the OpenCL delegate's Conv kernels —
the operation ORT WebGPU crashes on — are correct here. MobileNet has no
attention, so a transformer model (MatMul, Softmax, LayerNorm) through this
delegate is the next test, after converting one to `.tflite`.

## Build

Same AAR-extraction approach as
[`cerebrate-infer`](../../cerebrate-infer/README.md) (TFLite 2.16.1, with the
two headers the AAR omits), plus the GPU delegate AAR:

```bash
curl -sL -o tflite-gpu.aar \
  "https://repo1.maven.org/maven2/org/tensorflow/tensorflow-lite-gpu/2.16.1/tensorflow-lite-gpu-2.16.1.aar"
unzip -o tflite-gpu.aar -d gpu_aar
# gpu_aar/jni/arm64-v8a/libtensorflowlite_gpu_jni.so  sha256 6580606c…00ca
# (NEEDED: only stock Android libs -- libGLESv3, libEGL, libdl, libm, liblog, libc)

"$CLANGXX" -std=c++17 -O2 -o tflite-gpu-spike main.cc \
  -I tflite_aar/headers -I gpu_aar/headers \
  -L tflite_aar/jni/arm64-v8a -L gpu_aar/jni/arm64-v8a \
  -ltensorflowlite_jni -ltensorflowlite_gpu_jni \
  -Wl,-rpath,/data/local/tmp
```

The device's `libtensorflowlite_jni.so` (production `cerebrate-infer`'s) is
already this 2.16.1 build (sha256 `a4f950eb…6623`), so only the GPU library,
the spike, and the model were pushed.

```bash
adb shell 'cd /data/local/tmp && LD_LIBRARY_PATH=/data/local/tmp ./tflite-gpu-spike mobilenet_v1_1.0_224_float.tflite 20'
```

## Transformers: rejected (2026-10-23)

DINOv2-small converted with `litert-torch` (and a version with its embedding
step frozen, so every op is GPU-eligible) fails delegate initialization:
`CONCATENATION: Expected a 4D tensor of shape BxHxWxC but got 1x1x384`, plus
unsupported `BROADCAST_TO` / `GATHER_ND` in the unfrozen graph. The delegate
creates no kernels and the model falls back to CPU (318 ms). It is a 4-D,
CNN-oriented delegate. Transformers go through LiteRT 2.3.0's `CompiledModel`
GPU path instead, which runs a prepared DINOv2-small correctly (68.6 ms end
to end at fp32 vs 344 ms CPU) — see
[litert-gpu-transformers](../litert-gpu-transformers/README.md), which also
narrows this README's mention of `CompiledModel`'s "all-zero" output to the
tested uint8-I/O quantized model.
