# litert-compiled-correctness

Diagnostic harness, not a production component. Answers one cheap,
binary question: **does LiteRT's `CompiledModel` GPU path return real
output on this hardware, or does the tensor-buffer readback come back
all-zero?** See the
[Multi-Runtime Execution Plane](../../../../design-notes/Cerebrate%20Pixel%206%20%E2%80%94%20Multi-Runtime%20Execution%20Plane.md)
design notes' Progress Notes ("`LiteRtCompiledBackend` spike") for the
full investigation this came out of: a genuine GPU correctness bug
(the delegate executes for real — 31/31 nodes, real OpenCL init — but
the readback buffer is completely empty), found identically on both
this C++ path and a separate plain-C API attempt, on LiteRT `2.2.0`.

**Revisit trigger** (from those design notes): rerun this harness
before considering `LiteRtCompiledBackend` again, when either a newer
LiteRT release materially changes Android GPU tensor-buffer
interoperability, or a graph model is encountered that can't use the
NNAPI/TPU backend. Read the `checksum`/`gpu_output_all_zero` line in
the output — that's the whole answer.

Only `main.cc` and this top-level `CMakeLists.txt` are this project's
own code; everything else (the LiteRT C++ SDK, Abseil) is a third-party
dependency reconstructed from pinned release artifacts, not vendored
into this repo.

## Reconstructing the build environment

```bash
# 1. Prebuilt native runtime + GPU accelerator, from Google's Maven
#    (dl.google.com, NOT Maven Central -- this artifact isn't published there)
curl -sL -o litert-2.2.0.aar \
  "https://dl.google.com/dl/android/maven2/com/google/ai/edge/litert/litert/2.2.0/litert-2.2.0.aar"
mkdir -p litert_sdk/litert_cc_sdk
unzip -o litert-2.2.0.aar "jni/arm64-v8a/*" -d /tmp/litert_aar_extract
cp /tmp/litert_aar_extract/jni/arm64-v8a/*.so litert_sdk/litert_cc_sdk/

# 2. C++ SDK/wrapper source, from the matching GitHub release -- NOT
#    bundled in the AAR. Verify it's the SAME release as the AAR above
#    before trusting it (see the design notes' provenance-check section) --
#    don't assume two separately-fetched artifacts actually match.
curl -sL -o litert_cc_sdk.zip \
  "https://github.com/google-ai-edge/LiteRT/releases/download/v2.2.0/litert_cc_sdk.zip"
unzip -o litert_cc_sdk.zip -d litert_sdk
```

## Build (CMake -- this is the one path in this project that genuinely needs it)

```bash
NDK=~/Library/Android/sdk/ndk/27.1.12297006
mkdir -p build && cd build
cmake .. \
  -DCMAKE_TOOLCHAIN_FILE="$NDK/build/cmake/android.toolchain.cmake" \
  -DANDROID_ABI=arm64-v8a \
  -DANDROID_PLATFORM=android-26
cmake --build . --target litert_bench -j4
```

This will fetch and compile Abseil-cpp from source (pinned tag,
declared in `litert_sdk/litert_cc_sdk/abseil-cpp.cmake`) as part of the
build -- expect this step to take real time on first configure. Later
rebuilds after only editing `main.cc` are fast (relink only).

## Deploy and run

```bash
adb push build/litert_bench /data/local/tmp/
adb push litert_sdk/litert_cc_sdk/libLiteRt.so /data/local/tmp/
adb push litert_sdk/litert_cc_sdk/libLiteRtClGlAccelerator.so /data/local/tmp/
adb push mobilenet_v1_1.0_224_quant.tflite /data/local/tmp/
adb shell chmod +x /data/local/tmp/litert_bench
adb shell 'LD_LIBRARY_PATH=/data/local/tmp /data/local/tmp/litert_bench /data/local/tmp/mobilenet_v1_1.0_224_quant.tflite'
```

## Reading the output

```text
[CPU] ... top_class=795 top_score=102 checksum=242 reference_check=PASS
[GPU] ... top_class=0   top_score=0   checksum=0   reference_check=FAIL
[COMPARE] cpu_vs_gpu: exact_matches=978/1001 within_tolerance(+-5)=994/1001 max_abs_diff=102 gpu_output_all_zero=true
```

- `reference_check`: `PASS` if the argmax matches the known class (795)
  for this model/input.
- `checksum`: sum of the full 1001-byte output vector. `0` means the
  buffer was never populated -- the failure signature found here.
- `gpu_output_all_zero`: the direct answer to the revisit-trigger
  question. `true` = still broken; `false` = worth a real re-evaluation
  of `LiteRtCompiledBackend`.
