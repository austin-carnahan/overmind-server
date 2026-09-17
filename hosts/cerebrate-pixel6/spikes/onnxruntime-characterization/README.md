# onnxruntime-characterization

Phase C of the
[Operational Model Catalog v4](../../../../design-notes/cerebrate_pixel6_operational_model_catalog_v4.md)
(Sections 3.1, 6.1-6.3): does ONNX Runtime run the same MobileNet v1
1.0 224 quantized canary correctly on CPU, XNNPACK (Stage 1), and NNAPI
(Stage 2), on this device? Not a different model — the exact `.tflite`
file already deployed elsewhere in this project, converted to ONNX, so
a class mismatch can only mean a real backend problem, never a
confounded "different ground truth."

## Result

**CPU: PASS. NNAPI: PASS, genuinely reaches `google-edgetpu`, bit-exact
correct output — a real, positive correction of catalog v4's low-confidence
hypothesis. XNNPACK: crashes inside ONNX Runtime's own code**
(`libonnxruntime.so`, not this spike's code) — a real, reproducible
defect, not a usage bug.

```text
CPU           top_class=795 top_val=120 expected=795 [PASS] load_us=44026 run_us=6263
NNAPI(no-cpu) top_class=795 top_val=120 expected=795 [PASS] load_us=916328 run_us=7726 exact_matches=1001/1001 within_tolerance(+-5)=1001/1001 max_abs_diff=0
NNAPI(cpu-ok) top_class=795 top_val=120 expected=795 [PASS] load_us=936488 run_us=6354 exact_matches=1001/1001 within_tolerance(+-5)=1001/1001 max_abs_diff=0
XNNPACK       [SIGSEGV inside libonnxruntime.so during Run() -- see below]
```

Per catalog v4 Section 6.3's promotion rule: **ORT is promoted as the
first backend attempted for new graph models on this Pixel 6**, not just
the default portable CPU-tier fallback — the stronger outcome, since
NNAPI genuinely reached hardware acceleration here. TFLite+NNAPI's own
proven accelerated path isn't retired (Section 3.2's stated conditions
for keeping it still apply case-by-case), but it's no longer the *only*
accelerated graph option.

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

## Stage 2: NNAPI, verified against real delegation evidence, not just a passing Run()

Per catalog v4 Section 6.2's acceptance criteria, two separate NNAPI
configurations are run and compared against the CPU reference output
element-by-element (`kToleranceForMatch`), not just by argmax — the
same discipline that caught LiteRT `CompiledModel`'s GPU readback bug,
since a delegate that "runs successfully" can still return garbage or
an all-zero buffer:

- **`NNAPI(no-cpu)`** — `NNAPI_FLAG_CPU_DISABLED` set, so CPU fallback
  through NNAPI's own `nnapi-reference` implementation cannot silently
  produce an "accelerated" result. This is the real test.
- **`NNAPI(cpu-ok)`** — no flags, the permissive default. A comparison
  point to isolate whether `CPU_DISABLED` specifically breaks something,
  versus NNAPI integration failing regardless of the flag.

Both passed with **bit-exact** output (`exact_matches=1001/1001,
max_abs_diff=0`) against the CPU reference. An exact match on its own
is not proof of real acceleration — it's equally consistent with a
silent CPU fallback ORT itself didn't report as an error — so this was
corroborated with independent, direct evidence rather than trusted at
face value: `adb logcat` during the run shows

```text
Manager : Found interface google-edgetpu (version = 2.0)
onnxruntime: NnapiExecutionProvider::GetCapability, number of partitions
  supported by NNAPI: 3 number of nodes in the graph: 149 number of
  nodes supported by NNAPI: 146
android.hardware.neuralnetworks@service-darwinn-aidl: Ops supported = 29, not supported = 0
Darwinn : CompilerSpawner: Started Request #13 ... Completed Request #13, Status: 0
ExecutionPlan::SimpleBody::finish: compilation finished successfully on google-edgetpu
```

repeated once per compiled partition per run (four times total across
both NNAPI runs) — genuine TPU device discovery, genuine graph
partitioning (146 of 149 nodes delegated), genuine Darwinn compiler
invocation, genuine successful compilation onto `google-edgetpu`. TPU
temperature alone (26.0°C → 27.0°C across the whole run) was checked
too but treated as inconclusive on its own — a single quick inference is
too brief a workload for thermal drift to be a reliable signal either
way; the logcat evidence is what actually settles it.

The bit-exact match to CPU is itself a real, somewhat interesting
finding, not a red flag once corroborated: unlike the LiteRT GPU
investigation (float16 GPU compute paths genuinely diverging from
float32 CPU, `max_abs_diff=102`), a deterministic int8-quantized MobileNet
apparently produces identical output whether computed by CPU or by
`google-edgetpu` for this graph — plausible for simple, fully-integer
quantized ops, and worth remembering as a real data point rather than
assumed to generalize to every future quantized model.

**This corrects catalog v4 Section 3.1's own stated low-confidence
hypothesis** (drawn from `microsoft/onnxruntime#20782`, reporting NNAPI
failing to reach `google-edgetpu` on Pixel 6a/8 Pro) — for this exact
device, this exact model, and ONNX Runtime 1.30.0, NNAPI genuinely
reaches the TPU with `NNAPI_FLAG_CPU_DISABLED` set. That GitHub report
predates this ORT release and may describe a since-fixed regression, a
different model's operator set, or a device-specific difference between
Pixel 6 and 6a/8 Pro — this result doesn't invalidate that report, it
just means the failure mode it describes doesn't reproduce here, now,
for this workload. Recorded as what was actually measured, per this
project's own standing rule, not generalized beyond what was tested.

Load time (`~916-936ms`) is dominated by NNAPI/Darwinn compilation
overhead (visible directly in the logcat `CompilerSpawner` timings,
serialized across several hundred ms each) — over 20x slower to load
than CPU's `~44ms`. Run time itself (`~6-8ms`) is not dramatically
faster than CPU (`~6ms`) for this specific tiny quantized model; the
TPU's benefit for a model this small and fast may be power/thermal
efficiency under sustained load rather than raw single-shot latency,
consistent with what `cerebrate-infer`'s own NNAPI path found elsewhere
in this project. Not measured here: resident memory, or behavior under
the kind of sustained multi-minute load `cerebrate-infer`'s Stage 4C/4D
testing used — this spike is a single-shot correctness/delegation
check, not a soak test.

## Not yet done

Recording this result in the catalog's validation fields and updating
the design docs' promotion decision (catalog v4 Phase C, item 5) is a
separate step from this spike itself.
