# granite-docling-vision-encoder

Follow-up to
[experiments/docling](../../../../experiments/docling/README.md):
that experiment found `llama-mtmd-cli`'s Granite-Docling conversion on
this Pixel 6 spends ~99% of its ~104s runtime in vision encoding. This
spike isolates the vision encoder alone and asks whether ONNX
Runtime's NNAPI execution provider can accelerate it — the same
correctness-first discipline as the `onnxruntime-characterization`
spike, applied to a real transformer graph instead of a CNN.

## Result

**Correctness: clean pass, both as exported and after shape-fixing.
Acceleration: no — NNAPI never partitions any node from this graph,
static shapes or not.** Closed decisively, not left ambiguous.

```text
dynamic-shape graph (as exported):
  CPU            run_us=28046569  exact=479232/479232  cosine_sim=1.00000000
  NNAPI(no-cpu)  run_us=29027974  exact=479232/479232  cosine_sim=1.00000000  (bit-identical to CPU)
  NNAPI(cpu-ok)  run_us=29478911  exact=479232/479232  cosine_sim=1.00000000  (bit-identical to CPU)

static-shape graph (make_dim_param_fixed, batch_size=1, num_images=13):
  CPU            run_us=27978642  exact=479232/479232  cosine_sim=1.00000000
  NNAPI(no-cpu)  run_us=28820397  exact=479232/479232  cosine_sim=1.00000000  (bit-identical to CPU)
  NNAPI(cpu-ok)  run_us=29674889  exact=479232/479232  cosine_sim=1.00000000  (bit-identical to CPU)
```

No `NnapiExecutionProvider::GetCapability` log line and no
`ExecutionPlan::SimpleBody::finish: compilation finished successfully
on google-edgetpu` line appeared in `logcat` for **either** graph —
both were prominent, explicit lines in the MobileNet ORT/NNAPI
characterization
([`onnxruntime-characterization`](../onnxruntime-characterization/README.md)).
NNAPI discovers the `google-edgetpu` device (`Found interface
google-edgetpu (version = 2.0)` appears every run) but never attempts a
partitioning pass against this graph at all — not "tried and failed to
delegate," but never tried. Consistent with the on-device numbers: all
three backends produce bit-identical output at nearly identical
latency (~28-30s), and TPU-zone thermal rise (~1-6°C per run,
cumulative across repeated runs) is consistent with sustained CPU work,
not TPU engagement.

## Why static shapes were tried before giving up

ONNX Runtime's own mobile documentation states NNAPI does not support
dynamic input shapes and recommends fixing them for mobile deployment.
The as-exported `vision_encoder.onnx` has symbolic `batch_size` and
`num_images` dimensions on both inputs — a real, plausible, testable
explanation for zero partitioning, not idle speculation. Worth
eliminating before concluding the graph itself is simply unsupported.

**It made no difference.** Both the dynamic and the static-shape graphs
partition zero nodes to NNAPI. This is the actual, closing evidence:
the cause isn't (only) dynamic shapes — it's that this vision
transformer's operator mix (attention, layer norm, GELU, and however
the Idefics3-style pixel-shuffle connector is expressed in the graph)
isn't one NNAPI's execution provider claims here, regardless of shape
staticness.

## Correctness methodology

Judged on the intermediate `image_features` tensor (Idefics3's
post-connector `image_hidden_states`, shape `(13, 64, 576)` — 13 image
tiles for the real test chart, 64 tokens/tile, 576-wide hidden size
matching the language decoder), not generated DocTags text — comparing
full tensors element-by-element (exact matches, tolerance, max/mean
absolute difference, cosine similarity), the same discipline that
caught LiteRT `CompiledModel`'s GPU readback bug and ORT's XNNPACK
crash on MobileNet earlier in this project.

The exact `pixel_values`/`pixel_attention_mask` tensors and the CPU
reference output were computed **off-device**, on Overmind, using the
real `ibm-granite/granite-docling-258M` HF `transformers` checkpoint
and its real image processor on the same test image used throughout
the Docling experiment — verified first against the HF reference itself
(`max_abs_error=1.6e-3, cosine_sim=1.0`, see
[experiments/docling](../../../../experiments/docling/README.md)) —
then dumped to raw binary files so this on-device C canary could feed
identical, deterministic tensors without reimplementing Idefics3's
image resize/tiling logic in C.

## Reproduce

### 1. Get the ONNX artifact (real, official, pre-split exactly as needed)

```bash
python3 -c "
from huggingface_hub import hf_hub_download
hf_hub_download(repo_id='onnx-community/granite-docling-258M-ONNX', filename='onnx/vision_encoder.onnx')
hf_hub_download(repo_id='onnx-community/granite-docling-258M-ONNX', filename='onnx/vision_encoder.onnx_data')
"
```

HF's local cache stores both files as symlinks into a shared,
independently-hashed blob store — ONNX Runtime's external-data loader
rejects this (`External data path escapes model directory`) since the
`.onnx` and `.onnx_data` blobs resolve to different real directories.
Fix by copying both (dereferenced) into one plain directory together
before loading:

```bash
cp -L .../onnx/vision_encoder.onnx .../onnx/vision_encoder.onnx_data ./onnx-vision-encoder/
```

### 2. Dump the exact test tensors + CPU reference (off-device, needs `transformers`+`onnxruntime`)

```bash
python3 dump_vision_encoder_tensors.py test-chart.png <hf_checkpoint_dir> onnx-vision-encoder/vision_encoder.onnx tensors/
```

See [`../../../../experiments/docling/dump_vision_encoder_tensors.py`](../../../../experiments/docling/dump_vision_encoder_tensors.py).

### 3. (This experiment's addition) Fix dynamic shapes

```python
import onnx
from onnxruntime.tools.make_dynamic_shape_fixed import make_dim_param_fixed, fix_output_shapes

model = onnx.load("onnx-vision-encoder/vision_encoder.onnx")
make_dim_param_fixed(model.graph, "batch_size", 1)
make_dim_param_fixed(model.graph, "num_images", 13)  # matches this test image's real tile count
fix_output_shapes(model)
onnx.save(model, "onnx-vision-encoder/vision_encoder.static.onnx")
```

`onnx.load()` inlines external data by default, so the saved static
model is a single self-contained ~374MB file (no separate
`.onnx_data`) — simpler to deploy, not smaller (same weights).
`fix_output_shapes` couldn't fully resolve the output's declared shape
expression (`batch_size * num_images` stays symbolic in metadata) but
this doesn't affect actual runtime shapes or correctness, only that one
cosmetic annotation.

### 4. Build (same AAR/NDK setup as `onnxruntime-characterization`)

```bash
NDK=~/Library/Android/sdk/ndk/27.1.12297006
CLANGXX=$NDK/toolchains/llvm/prebuilt/darwin-x86_64/bin/aarch64-linux-android24-clang++
"$CLANGXX" -o granite-docling-vision-encoder main.cc \
  -I ort_aar/headers -L ort_aar/jni/arm64-v8a -lonnxruntime \
  -Wl,-rpath,/data/local/tmp -O2
```

### 5. Deploy and run

```bash
adb push granite-docling-vision-encoder ort_aar/jni/arm64-v8a/libonnxruntime.so /data/local/tmp/vision-encoder-spike/
adb push onnx-vision-encoder/vision_encoder.onnx onnx-vision-encoder/vision_encoder.static.onnx /data/local/tmp/vision-encoder-spike/
adb push tensors/ /data/local/tmp/vision-encoder-spike/tensors/
adb shell chmod +x /data/local/tmp/vision-encoder-spike/granite-docling-vision-encoder

adb shell 'LD_LIBRARY_PATH=/data/local/tmp/vision-encoder-spike /data/local/tmp/vision-encoder-spike/granite-docling-vision-encoder /data/local/tmp/vision-encoder-spike/vision_encoder.onnx /data/local/tmp/vision-encoder-spike/tensors'
# then rerun with vision_encoder.static.onnx for the shape-fixed comparison
```

## Closed, not left ambiguous

Per the plan this spike followed: dynamic-shape zero partitioning was a
real, testable, plausible-not-speculative hypothesis (ONNX Runtime's
own mobile docs say NNAPI needs static shapes), and it was eliminated
directly rather than assumed. With that ruled out, the remaining
explanation — this transformer graph's specific operator combination
isn't one ORT's NNAPI EP claims on this device/version — is the actual
closing finding. No further NNAPI/TPU work on this specific graph is
planned; the ~99-second vision-encoding bottleneck stays a CPU cost on
this Pixel 6, at least via this export and this ORT version.
