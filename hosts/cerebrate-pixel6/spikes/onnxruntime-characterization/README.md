# onnxruntime-characterization

Phase C Stage 1 of the
[Operational Model Catalog v4](../../../../design-notes/cerebrate_pixel6_operational_model_catalog_v4.md)
(Sections 3.1, 6.1-6.3): does ONNX Runtime run the same MobileNet v1
1.0 224 quantized canary correctly on CPU and XNNPACK, on this device?
Not a different model — the exact `.tflite` file already deployed
elsewhere in this project, converted to ONNX, so a class mismatch can
only mean a real backend problem, never a confounded "different ground
truth."

## Result

**CPU: PASS.** **XNNPACK: crashes inside ONNX Runtime's own code**
(`libonnxruntime.so`, not this spike's code) — a real, reproducible
defect, not a usage bug. Per catalog v4 Section 6.3, this is enough to
promote ORT as the default *portable* CPU-tier candidate for new graph
models; TFLite+NNAPI remains the only proven *accelerated* Pixel 6 graph
path (Stage 2 characterizes ORT's NNAPI EP next, separately).

```text
CPU        top_class=795 top_val=120 expected=795 [PASS] load_us=41265 run_us=16566
XNNPACK    [SIGSEGV inside libonnxruntime.so during Run() -- see below]
```

## Getting the ONNX model: convert the existing canary, don't re-export

MobileNet ONNX exports commonly floating around (e.g. the ONNX Model
Zoo's) are a *different* model — different architecture variant,
different quantization or none at all — so a class mismatch against
them would be uninformative (does it mean ORT is broken, or just that
it's a different network with a different correct answer?). Converting
the *exact* `.tflite` already deployed on this device keeps the
comparison apples-to-apples.

```bash
# Same file already staged on the Pixel and cached at
# /mnt/models/direct/mobilenetv1/ on overmind-01 -- verify the checksum
# matches models/catalog.yaml before trusting this conversion at all.
sha256sum mobilenet_v1_1.0_224_quant.tflite
# ecc3a67c47c5a609ec35f6a58a7d97532834e43df4cb7d3f1204a8164b7d20dd

python3 -m venv tf2onnx_venv && tf2onnx_venv/bin/pip install tensorflow tf2onnx
tf2onnx_venv/bin/python3 -m tf2onnx.convert \
  --tflite mobilenet_v1_1.0_224_quant.tflite \
  --output mobilenet_v1_1.0_224_quant.onnx \
  --opset 13
```

**Verified off-device, before ever touching Android**, with ONNX
Runtime's own Python bindings (`pip install onnxruntime`) and the exact
deterministic `i % 256` input pattern used everywhere else in this
project: raw `argmax` over the resulting `[1, 1001]` uint8 output is
`795` — the reference class, no index-shift or off-by-one needed. This
confirmed the conversion preserved the model's real behavior before any
Android-specific variable (NNAPI, XNNPACK, the NDK toolchain) could be
blamed for a mismatch that was actually just a bad conversion.

## Build

```bash
# Download and inspect the AAR -- confirms NNAPI and XNNPACK are
# genuinely built into this .so before trusting either (same discipline
# as the litert-compiled-correctness spike's provenance checks).
curl -sL -o onnxruntime-android.aar \
  "https://repo1.maven.org/maven2/com/microsoft/onnxruntime/onnxruntime-android/1.30.0/onnxruntime-android-1.30.0.aar"
unzip -o onnxruntime-android.aar -d ort_aar
# ort_aar/headers/*.h (full C API, unlike the legacy TFLite AAR's
# incomplete headers -- nothing extra to fetch from GitHub this time)
# ort_aar/jni/arm64-v8a/libonnxruntime.so

NDK=~/Library/Android/sdk/ndk/27.1.12297006
llvm-nm -D ort_aar/jni/arm64-v8a/libonnxruntime.so | grep NnapiFactory
# 0000...  T OrtSessionOptionsAppendExecutionProvider_Nnapi@@VERS_1.30.0
strings ort_aar/jni/arm64-v8a/libonnxruntime.so | grep XnnpackExecutionProvider
# XnnpackExecutionProvider   -- confirms it's actually compiled in

CLANGXX=$NDK/toolchains/llvm/prebuilt/darwin-x86_64/bin/aarch64-linux-android24-clang++
"$CLANGXX" -o onnxruntime-characterization main.cc \
  -I ort_aar/headers \
  -L ort_aar/jni/arm64-v8a -lonnxruntime \
  -Wl,-rpath,/data/local/tmp \
  -O2
```

## Deploy and run

```bash
adb push onnxruntime-characterization /data/local/tmp/
adb push ort_aar/jni/arm64-v8a/libonnxruntime.so /data/local/tmp/
adb push mobilenet_v1_1.0_224_quant.onnx /data/local/tmp/
adb shell chmod +x /data/local/tmp/onnxruntime-characterization
adb shell 'LD_LIBRARY_PATH=/data/local/tmp /data/local/tmp/onnxruntime-characterization /data/local/tmp/mobilenet_v1_1.0_224_quant.onnx'
```

`libc++_shared.so` is not a dependency of `libonnxruntime.so` itself
(its `NEEDED` entries are only stock Android system libraries), but this
spike's own binary needs it since it's compiled with `clang++` — already
staged at `/data/local/tmp/` from `cerebrate-infer`'s deploy.

## The XNNPACK crash: real, reproducible, inside ONNX Runtime itself

Localized by adding `stderr`-flushed progress markers between each ORT
C API call (kept in `main.cc` — this spike crashes reliably enough that
they're worth leaving in, not scaffolding to strip out): the crash
happens inside `OrtApi::Run()`, after session creation and input tensor
setup both succeed cleanly. `stdout`'s verdict line is otherwise
silently lost on a crash (fully buffered when not a tty) — the CPU
run's `PASS` line only became visible after adding an explicit
`fflush(stdout)`, worth remembering for any future spike in this style.

```text
signal 11 (SIGSEGV), code 2 (SEGV_ACCERR), fault addr ... (read)
Cause: possible buffer overflow accessing after secondary allocation
backtrace:
  #00-#14  all inside /data/local/tmp/libonnxruntime.so
  #15-#16  onnxruntime-characterization (this spike's own Run() call site)
  #17  __libc_init
```

All the actual crashing frames are inside ONNX Runtime's own compiled
code, not this spike's — a targeted search for a matching upstream
GitHub issue (XNNPACK EP + quantized model + crash) didn't surface a
clear existing report, but the on-device stack trace is first-party
evidence on its own, the same standard this project has held to
throughout (e.g. the LiteRT `CompiledModel` GPU readback bug). Not
investigated further here: whether this is specific to this exact
converted graph's quantization op pattern, this exact ORT version
(1.30.0), or a broader XNNPACK+quantized-uint8 limitation. CPU already
satisfies Stage 1's actual requirement (a dependable correctness
baseline), so this is recorded as a real finding and left there rather
than chased — XNNPACK was always the optional accelerated-CPU tier, not
the baseline itself.

## Not yet done (Stage 2)

NNAPI execution provider correctness + delegation evidence — a
separate, lower-confidence hypothesis per catalog v4 Section 3.1, gated
independently of this stage's CPU/XNNPACK result.
