# litert-gpu-transformers

Step 2A of the
[Segmentation and Labeling Lane](../../../../design-notes/Cerebrate%20Pixel%206%20%E2%80%94%20Segmentation%20and%20Labeling%20Lane.md):
the LiteRT 2.3.0 correctness regression, and the first transformer on the
Pixel 6's GPU.

## Result (2026-10-23)

**LiteRT 2.3.0's `CompiledModel` GPU path runs a transformer correctly on
this Pixel 6 — once the model is prepared for it.** Prepared DINOv2-small
(fp32, 224×224, all 621 ops in one GPU partition):

| Path | vs CPU | Mean | Best |
| --- | --- | --- | --- |
| CPU (XNNPACK) | reference | ~330 ms | ~315 ms |
| **GPU, fp32 precision** | **cosine 1.000000**, max abs diff 1.1e-4 | **5.0 ms** | 4.3 ms |
| GPU, default precision (fp16) | cosine 0.999693, max abs diff 0.68 | 6.2 ms | 4.1 ms |

Times use buffers created from the compiled model's requirements. Plain
host-memory buffers give the same output but take 38–68 ms (copies), so a
worker must use requirement-based buffers.

The way there settled four separate questions.

### 1. The 2.2.0 failure reproduces on 2.3.0, unchanged

The [litert-compiled-correctness](../litert-compiled-correctness/README.md)
harness, `main.cc` unchanged, rebuilt against 2.3.0 (build adjustments below),
same quantized MobileNet: 31/31 nodes on `LITERT_CL`, OpenCL and the GPU
environment initialize, `Failed to get buffer requirements` for the input and
output tensors, then `top_class=0 checksum=0 gpu_output_all_zero=true`
(CPU: class 795, checksum 242). GPU mean 9.7 ms, CPU 33.4 ms.

### 2. "All-zero" is a never-written output, and only for uint8 I/O

[`canary.cc`](canary.cc) uses the plain C API, pre-fills the output with a
sentinel byte (`0xAB`) before running, waits on any buffer event, then counts
sentinel bytes, and tries three buffer strategies (from requirements, aligned
host memory, managed OpenCL buffers):

- **Quantized MobileNet (uint8 in/out):** every GPU strategy left all 1,001
  sentinel bytes untouched — the bound output buffer is **never written**, even
  with native OpenCL buffers. The GPU compiled model reports only host-memory
  requirements after failing to get its own. The harness's "all zeros" were its
  zero-initialized buffer. This was the only model ever tested on this path
  before (2.2.0 and 2.3.0).
- **Float MobileNet (float32 in/out):** GPU-only compilation fails
  (`kLiteRtStatusErrorCompilation`) because two `SQUEEZE` ops can't go to the
  GPU; with GPU + CPU allowed it is **correct** — cosine 0.999961, same top
  class, 8.3 ms vs 31.6 ms CPU — and buffer requirements are available (input
  buffer type 14, packed OpenCL).

So the old "readback bug" label was too specific: the defect is that the GPU
accelerator can't bind uint8 I/O tensors and silently never writes them.
Float models — which converted transformers are — work.

### 3. DINOv2: wrong numbers, traced to one op

`facebook/dinov2-small` (revision `ed25f3a3…`) converted with
`litert-torch` 0.10.0 matches PyTorch on CPU (cosine 1.000000). On the GPU it
ran (693/749 ops; `BROADCAST_TO` and `GATHER_ND` from the embedding step left
on CPU), 39.5 ms vs 335 ms, but the output was wrong: cosine 0.026.

- Not precision: forcing fp32 (`LrtSetGpuAcceleratorCompilationOptionsPrecision`)
  or fp16-with-fp32-accumulation gave the same cosine.
- Not the CPU/GPU partition boundary: freezing the embedding step for a fixed
  224×224 input (precomputed position embeddings, class token used directly)
  put all 645 ops on the GPU in one partition, 6 ms — same wrong output.
- Depth bisection ([`bisect_depth.py`](bisect_depth.py)): the embedding step
  alone is correct (cosine 0.999995); one transformer layer is not (0.417).
- Inside layer 0 ([`bisect_layer0.py`](bisect_layer0.py)): LayerNorm,
  Q projection, attention scores, Softmax, attention context, `o_proj`, and the
  residual add are all correct (cosine ≥ 0.99965); **the LayerScale multiply —
  `[1,257,384] × [384]` per-channel constant — is wrong (0.427)**. Every DINOv2
  layer has two.

### 4. The fix is a model-preparation step

[`prepare_dinov2.py`](prepare_dinov2.py): freeze the embedding step, and fold
each LayerScale vector into the linear layer before it (`o_proj`, `fc2`) —
scaling a linear layer's output channels by λ is exactly scaling its weight
rows and bias by λ. The prepared model differs from the original by at most
7e-5 in PyTorch and gives the results at the top.

Classic TFLite GPU delegate, for comparison: it rejects both the original and
frozen DINOv2 at initialization (`CONCATENATION: Expected a 4D tensor ...
got 1x1x384`) — it is a CNN-oriented, 4-D delegate.

## What this means for the lane

- **LiteRT 2.3.0 `CompiledModel` becomes the GPU runtime for transformers**,
  with float I/O and requirement-based buffers. The classic delegate stays
  useful for 4-D CNN graphs.
- **Model preparation is part of the GPU path**, with rules learned here:
  float I/O (no uint8 tensors at the boundary); remove ops the GPU can't take
  (freeze shape-dependent steps for a fixed input size); fold per-channel
  broadcast multiplies into adjacent weights. Every prepared model is checked
  against its unmodified original in PyTorch, then against CPU on the device.
- The LayerScale/broadcast-multiply defect, the uint8 I/O defect, and the
  `SQUEEZE`-only GPU compilation failure are reproducible here with the files
  in this directory; recheck each on later LiteRT releases.

## Build

```bash
curl -sL -o litert-2.3.0.aar \
  "https://dl.google.com/dl/android/maven2/com/google/ai/edge/litert/litert/2.3.0/litert-2.3.0.aar"
# New in 2.3.0: the GPU accelerator ships separately.
curl -sL -o litert-gpu-2.3.0.aar \
  "https://dl.google.com/dl/android/maven2/com/google/ai/edge/litert/litert-gpu/2.3.0/litert-gpu-2.3.0.aar"
curl -sL -o litert_cc_sdk.zip \
  "https://github.com/google-ai-edge/LiteRT/releases/download/v2.3.0/litert_cc_sdk.zip"
# sha256: litert-2.3.0.aar 9508c6e9…89dc, litert-gpu-2.3.0.aar 173a4c38…824f,
# litert_cc_sdk.zip 44ebb188…28d2 (302776 bytes, matching the v2.3.0 release
# asset size from GitHub's API)
unzip -o litert_cc_sdk.zip -d /tmp/litert_sdk_2.3.0
unzip -o litert-2.3.0.aar 'jni/arm64-v8a/*' -d aar && cp aar/jni/arm64-v8a/libLiteRt.so /tmp/litert_sdk_2.3.0/litert_cc_sdk/
unzip -o litert-gpu-2.3.0.aar 'jni/arm64-v8a/*' -d gpu && cp gpu/jni/arm64-v8a/libLiteRtClGlAccelerator.so /tmp/litert_sdk_2.3.0/litert_cc_sdk/

NDK=~/Library/Android/sdk/ndk/27.1.12297006
mkdir -p build && cd build
cmake .. -DCMAKE_TOOLCHAIN_FILE="$NDK/build/cmake/android.toolchain.cmake" \
  -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-26
cmake --build . --target litert_bench litert_c_canary -j8
```

Two 2.3.0 differences from the 2.2.0 recipe: the GPU accelerator moved to the
separate `litert-gpu` artifact, and `absl::raw_hash_set` must be linked
explicitly ([`CMakeLists.txt`](CMakeLists.txt)).

On the device the 2.3.0 libraries live in `/data/local/tmp/litert-2.3.0/`, so
the 2.2.0 copies in `/data/local/tmp/` are untouched:

```bash
adb shell 'cd /data/local/tmp && LD_LIBRARY_PATH=/data/local/tmp/litert-2.3.0:/data/local/tmp \
  ./litert-2.3.0/litert_c_canary dinov2-small-prepared-fp32.tflite gpu fp32'
# canary args: <model.tflite> [gpu|gpu+cpu] [default|fp16|fp32|fp16acc32]
```

Model conversion runs on the Mac:

```bash
uvx --python 3.12 --with litert-torch==0.10.0 --with transformers --with huggingface_hub \
  python -I prepare_dinov2.py <out-dir>
```
