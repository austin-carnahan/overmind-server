# cerebrate-infer

Minimal persistent inference worker for `cerebrate-pixel6` (Stage 4C — see
[the design notes](../../../design-notes/2026-09-16-pixel6-inference-node.md)
for the full narrative and thermal/latency findings). Loads a TFLite model
and creates the NNAPI delegate (forcing `google-edgetpu`) **once**, then
serves TCP requests one at a time: run inference, return
`request_id`, `top_class`, `top_score`, `inference_us`.

Deliberately narrow: no concurrency, no auth, no model registry, one fixed
dummy input. `InferenceEngine` is a real seam (see `cerebrate-infer.cc`) —
`NnapiTfliteEngine` is implemented; a future `LiteRtEngine` is declared in
the design notes but not implemented, since the LiteRT v2 spike found it
~13× slower on this specific (Tensor G1) hardware — see the design notes'
"Backend decision" section before assuming this should move to LiteRT.

## Build (no Bazel — AAR extraction only)

The legacy TFLite C API + NNAPI delegate ships inside the **Android AAR**
for `org.tensorflow:tensorflow-lite`, not as a standalone download.
**2.17.0 dropped native AAR publishing to Maven Central — use 2.16.1.**

```bash
# 1. Get the AAR and extract headers + the arm64-v8a native library
curl -sL -o tflite.aar \
  "https://repo1.maven.org/maven2/org/tensorflow/tensorflow-lite/2.16.1/tensorflow-lite-2.16.1.aar"
unzip -o tflite.aar -d tflite_aar
# jni/arm64-v8a/libtensorflowlite_jni.so
# headers/tensorflow/lite/...

# 2. The AAR's bundled headers are missing two files — pull them from the
#    matching v2.16.1 tag (not master, to keep ABI/version consistent)
mkdir -p tflite_aar/headers/tensorflow/lite/core/async/c
curl -sL -o tflite_aar/headers/tensorflow/lite/core/async/c/types.h \
  "https://raw.githubusercontent.com/tensorflow/tensorflow/v2.16.1/tensorflow/lite/core/async/c/types.h"
curl -sL -o tflite_aar/headers/tensorflow/lite/core/c/registration_external.h \
  "https://raw.githubusercontent.com/tensorflow/tensorflow/v2.16.1/tensorflow/lite/core/c/registration_external.h"

# 3. Compile as C++ (nnapi_delegate_c_api.h uses C++-only nested-enum
#    syntax despite its extern "C" wrapper — a plain C compile fails)
NDK=~/Library/Android/sdk/ndk/27.1.12297006   # any recent NDK works
CLANGXX=$NDK/toolchains/llvm/prebuilt/darwin-x86_64/bin/aarch64-linux-android24-clang++
"$CLANGXX" -o cerebrate-infer cerebrate-infer.cc \
  -I tflite_aar/headers \
  -L tflite_aar/jni/arm64-v8a -ltensorflowlite_jni \
  -Wl,-rpath,/data/local/tmp \
  -O2
```

Verify the delegate symbols are actually exported before trusting any of
this (confirmed once already, worth re-checking after a version bump):

```bash
$NDK/toolchains/llvm/prebuilt/darwin-x86_64/bin/llvm-nm -D \
  tflite_aar/jni/arm64-v8a/libtensorflowlite_jni.so | grep NnapiDelegate
```

## Deploy

```bash
adb push cerebrate-infer /data/local/tmp/
adb push tflite_aar/jni/arm64-v8a/libtensorflowlite_jni.so /data/local/tmp/
# C++ runtime — needed because we compile with clang++, not plain clang
adb push $NDK/toolchains/llvm/prebuilt/darwin-x86_64/sysroot/usr/lib/aarch64-linux-android/libc++_shared.so /data/local/tmp/
adb push mobilenet_v1_1.0_224_quant.tflite /data/local/tmp/
adb shell chmod +x /data/local/tmp/cerebrate-infer
```

**Run as a kept-alive background task, not `adb shell 'cmd &'`** — a
process backgrounded with `&` inside a single transient `adb shell`
invocation dies when that invocation's connection ends (hit this twice
across this project already). Keep the `adb shell` process itself alive
instead:

```bash
adb shell 'LD_LIBRARY_PATH=/data/local/tmp /data/local/tmp/cerebrate-infer /data/local/tmp/mobilenet_v1_1.0_224_quant.tflite 8765'
```

## Test from Debian

```bash
echo | nc 10.70.217.78 8765
# request_id=1 top_class=795 top_score=120 inference_us=1190
```

`10.70.217.78` is the guest's current AVF NAT gateway address — not
assumed stable across VM restarts (the guest's whole networking stack is
AVF-managed); re-check `ip route` inside the guest if this stops working.
