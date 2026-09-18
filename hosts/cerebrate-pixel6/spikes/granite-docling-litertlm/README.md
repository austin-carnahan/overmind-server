# granite-docling-litertlm

Follow-up to
[experiments/docling](../../../../experiments/docling/README.md) and
[`granite-docling-vision-encoder`](../granite-docling-vision-encoder/README.md):
evaluates `litert-community/granite-docling-258M` (an existing INT8
`.litertlm` conversion) as an alternative to the proven `llama.cpp` /
`llama-mtmd-cli` path for selective Docling enrichment, since LiteRT-LM
already fits Cerebrate's existing native-worker architecture more
naturally than adding a second permanent runtime.

## Result: blocked before any quality comparison could run

**Not a Granite-specific defect, and not a preprocessing mistake on this
end.** The plain C API this project's other LiteRT-LM work
(`cerebrate-generate`) already uses cannot pass image input through
`SessionAdvanced` at all — confirmed by reading the real LiteRT-LM
source across three consecutive releases (`v0.16.0`, `v0.17.0`,
`v0.17.1`, the current latest), not assumed from one error message.

```text
loading engine model=.../granite-docling-258M.litertlm backend=cpu vision_backend=cpu ...
engine loaded in 4050493 us
image: .../chart_512.png (96054 bytes)
E0000 ... engine.cc:954] Failed to generate content: INTERNAL: Image must be
preprocessed before being used in SessionAdvanced.
```

## Root cause, traced through the real source, not guessed

`litert_lm_input_data_create(kLiteRtLmInputDataTypeImage, data, size)`
(`c/engine.cc`) constructs an `InputImage` from the raw bytes as an
opaque string — the "encoded file" representation:

```cpp
case kLiteRtLmInputDataTypeImage:
  return std::make_unique<LiteRtLmInputData>(
      litert::lm::InputImage(std::string(static_cast<const char*>(data), size)))
      .release();
```

But `SessionAdvanced`'s prefill/generate path (`session_utils.cc`,
`PreprocessContents`) only accepts an `InputImage` that is *already* a
`TensorBuffer`:

```cpp
if (input_image->IsTensorBuffer() || input_image->IsTensorBufferMap()) {
  ...
} else {
  return absl::InternalError("Image must be preprocessed before being used in SessionAdvanced.");
}
```

There is no public C API function to get from "raw bytes" to
"TensorBuffer" — no image-preprocessing entry point, and no session or
modality config (`litert_lm_session_config_*`) that changes this. Every
entry point that reaches `SessionAdvanced` — `generate_content` *and*
`run_prefill`/`run_decode` — hits the identical check.

**The genuinely working path is real, but it isn't the plain C API.**
`runtime/core/session_utils_test.cc`'s `PreprocessContentsMultimodal`
test passes, using exactly the representation `PreprocessContents`
wants:

```cpp
std::vector<float> dummy_image_data = {0.1f, 0.2f, 0.3f};
auto image_tensor = CopyToTensorBuffer<float>(dummy_image_data, {1, 1, 1, 3});
contents.emplace_back(InputImage(std::move(image_tensor)));
```

`InputImage(litert::TensorBuffer)` and `CopyToTensorBuffer<T>` are real,
C++ types from LiteRT-LM's core source — not exposed in the plain
`engine.h`/`conversation.h` headers this project's C-API spikes have
used throughout. Also checked and ruled out: `conversation.h`'s
`LiteRtLmConversation` API (which sounded like it might be the
multimodal-aware layer) has **zero** mentions of image or audio
anywhere in its 503 lines — it's a JSON-message/tool-calling/system-prompt
layer, not a preprocessing one.

## What this means for a future native worker

The model card's only two documented working paths are the Android
Kotlin app (Google AI Edge Gallery) and the Swift runtime on Apple
platforms — both reach `InputImage(TensorBuffer)` internally, neither
exposes it. That does **not** mean multimodal LiteRT-LM requires
writing an Android app, though: the real, verified path is

```text
Android native binary
        |
LiteRT-LM full C++ SDK -- InputImage(TensorBuffer)
        |
multimodal .litertlm
```

— the same heavier CMake+Abseil-cpp build already characterized in the
`litert-compiled-correctness` spike's "C++ SDK" path (as opposed to the
lightweight plain-C-API compiles every other Pixel spike has used), not
the Conversation API. It would also require independently determining
the exact tensor shape/dtype/normalization each vision tower expects
(not exposed anywhere in the plain headers) — real, nontrivial
additional work, not just a bigger build.

**Not built now.** Per the plan this spike followed: this is worth
investigating the next time a compelling multimodal `.litertlm`
appears, not something to build just to rescue this one model when the
proven `llama.cpp` path already works for the actual current need.

## Recorded so this isn't rediscovered

`models/schema.json` gained `api_requirements`/`cerebrate_support`
fields on the artifact definition specifically because of this finding
— see [`models/catalog.yaml`](../../../../models/catalog.yaml)'s
`smollm2-135m-instruct` entry for the populated (working, text-only)
example. Policy going forward: a text-only `.litertlm` can go straight
to the existing native C worker; a multimodal one needs its required
`litertlm_surface` checked against what's actually reachable *before*
staging or benchmarking it — this spike is the reason that check exists.

## Reproduce (up to the point it fails)

```bash
NDK=~/Library/Android/sdk/ndk/27.1.12297006
CLANGXX=$NDK/toolchains/llvm/prebuilt/darwin-x86_64/bin/aarch64-linux-android24-clang++
"$CLANGXX" -o granite-docling-litertlm main.cc \
  -I litertlm_c/include -L litertlm_c/lib/android_arm64 -llitert-lm \
  -Wl,-rpath,/data/local/tmp -O2

adb push granite-docling-litertlm litertlm_c/lib/android_arm64/liblitert-lm.so /data/local/tmp/litertlm-spike/
adb push granite-docling-258M.litertlm /data/local/tmp/litertlm-spike/
adb push chart_512.png equation_512.png /data/local/tmp/litertlm-spike/
adb shell chmod +x /data/local/tmp/litertlm-spike/granite-docling-litertlm

adb shell 'LD_LIBRARY_PATH=/data/local/tmp/litertlm-spike:/data/local/tmp /data/local/tmp/litertlm-spike/granite-docling-litertlm /data/local/tmp/litertlm-spike/granite-docling-258M.litertlm /data/local/tmp/litertlm-spike/chart_512.png "Convert this page to docling."'
```

Images were pre-resized to exactly 512x512 with PIL's explicit
`BILINEAR` filter before pushing — the model card warns other
resampling filters produce hallucinated output — though this spike
never reached the point of exercising that requirement, since
generation fails before any actual inference runs.

Model load itself succeeds (~4.05s); the failure is specifically in
`generate_content`, after the image input is constructed and handed to
the session.
