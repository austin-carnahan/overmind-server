# Docling + Granite-Docling experiment

Evaluates Docling as a document-ingestion tool on Overmind, then
whether `ibm-granite/granite-docling-258M` is useful enough to justify
running it on Cerebrate Pixel 6 — per the plan the user gave for this
experiment, revised mid-run into a leaner framework once the first
approach (full-page VLM conversion via Python/transformers, on
Overmind) proved too slow to be worth waiting out. Deliberately small:
no `docling-serve`, no persistent ingestion service, no ONNX/ Vulkan
work, no production integration.

Real PDF used throughout:
[`input/sampling-variance-CFR.pdf`](input/sampling-variance-CFR.pdf) —
a 6-7 page research paper (Gibson et al. 2012, "Generalized Sampling
and Variance in Counterfactual Regret Minimization"), chosen for
structural variety: two-column layout, dense inline math notation,
display equations, a pseudocode listing, and three real figures
(a multi-panel tree diagram, two line charts).

## Result summary

| Path | Result |
| --- | --- |
| Docling default pipeline (Overmind, Pi 4) | Works. Clean prose/headers/abstract. **Math-heavy sections badly broken**: reading order scrambles into single-character fragments, every display equation is an unresolved `<!-- formula-not-decoded -->` placeholder. 3 of 5 detected "pictures" are real figures with good fidelity; 2 are small inline formulas misclassified as pictures. ~6.5 min, ~2.4GB peak RSS. |
| Granite-Docling full-page VLM via Docling's own `VlmPipeline` + transformers (Overmind, Pi 4) | **Killed after 92+ minutes**, no page completed. Operationally unusable on this CPU via this path, independent of output quality. |
| Granite-Docling via `llama-mtmd-cli` on Pixel 6 (native, CLI, direct `--image`) | **Works correctly.** Real, well-formed DocTags: correctly identified and classified a real chart (`<picture><line_chart>`). ~1m44s per image (~99% vision encoding), ~813MB stable RSS, deterministic (`--temp 0`, reproduced identically twice). |
| Same model via `llama-server`'s OpenAI-compatible `/v1/chat/completions` | **Broken** — degenerate repeating `0.0 0.0 0.0...` output, burns the full token budget. Matches a real, still-open upstream bug (see below), not a config mistake here. |
| Same model via `llama-server`'s native `/completion` endpoint, hand-built chat template | Image tiling genuinely correct, model reads real content off the image (chart legend/axis text appeared verbatim) — but output isn't valid `<doctag>` structure, degrades into `0.0` repetition. **Superseded** by the decisive test below. |
| Same model via `llama-server`'s native `/completion` endpoint, using the server's own `/apply-template` output verbatim | **Still broken — decisive negative result.** Same degenerate `0.0` repetition, this time burning the full requested token budget, even with the exact server-generated prompt (correct marker placement, correct image tiling, no hand-reconstruction involved at all). Rules out chat-template reconstruction as the cause. |

**Recommendation:** Granite-Docling is real and does recover genuine
image content that the default pipeline can't (see below on the
"materially improve" question, still open pending a same-page,
apples-to-apples comparison — not done in this pass). The CLI path
(`llama-mtmd-cli`) is proven correct and fast enough to be interesting
for selective, low-volume enrichment (a handful of figures per
document, not full-page conversion). **The persistent `llama-server`
HTTP path is conclusively not usable for this model as of `b11028`** —
not a templating mistake on this end, but a genuine
Granite-Docling-specific defect in `llama-server`'s multimodal
generation path, isolated by eliminating every other variable (marker,
image tiling, and finally the chat template itself, using the server's
own `/apply-template` output verbatim). `libmtmd`/CLI inference is
healthy; the server's serving path is not, for this model, today. Any
future "Docling on Overmind calls out to a warm Pixel service"
architecture should build on the proven CLI-per-call pattern (accepting
its per-call model-load/encode cost) rather than a persistent server,
unless a future llama.cpp release fixes this.

## Stage 1: Docling baseline on Overmind

### Environment

Isolated venv at `/mnt/disks/ssd1/experiments/docling-venv` (Python
3.12.14 via `uv`, **not** the OS microSD card — see "Environmental
findings" below for why that distinction mattered here).

```text
docling            2.128.0
docling-core       2.97.0
docling-ibm-models 4.0.2
transformers       5.17.0
torch              2.14.0+cpu
rapidocr           3.9.2
```

### Reproduce

```bash
uv venv /mnt/disks/ssd1/experiments/docling-venv --python 3.12
uv pip install --python /mnt/disks/ssd1/experiments/docling-venv/bin/python3 --torch-backend cpu docling
# opencv-python needs libGL.so.1, not installed on this headless server;
# opencv-python-headless is a drop-in replacement with no GL dependency
uv pip uninstall --python .../docling-venv/bin/python3 opencv-python
uv pip install --python .../docling-venv/bin/python3 opencv-python-headless

python3 run_default_pipeline.py sampling-variance-CFR.pdf out-default
```

[`run_default_pipeline.py`](run_default_pipeline.py) uses
`PdfPipelineOptions(generate_picture_images=True, images_scale=2.0)` —
without this, `DocumentConverter()`'s default options record picture
bounding boxes but never write the actual image files, despite
requesting `ImageRefMode.REFERENCED` on export (a real gap in the first
pass of this script, fixed before the numbers below).

### Result

```text
conversion wall-clock: 367-371s
pages: 7   tables: 0   pictures: 5
Elapsed (wall clock): 6:25-6:31 (two runs, consistent)
Maximum resident set size: ~2.37-2.48 GB
CPU: ~291% (multi-threaded, not memory- or I/O-bound)
```

Full output: [`out-default/document.md`](out-default/document.md),
[`out-default/document.json`](out-default/document.json), extracted
images under `out-default/document_artifacts/`.

**Quality, inspected directly, not just counted:**

- Title, authors, abstract, introduction: clean, correct Markdown,
  right reading order.
- Once dense game-theory notation appears (inline subscripts,
  superscripts, set notation), reading order **collapses into isolated
  single-character/token fragments** — e.g. real output includes lines
  reading just `R`, `T`, `i`, `(`, `I, a`, `∈`, `i`, `-` in sequence,
  spanning what should be one coherent sentence with embedded math.
- **Every display equation is `<!-- formula-not-decoded -->`** — nine
  occurrences, zero equations actually recovered.
- Of the 5 detected "pictures": 3 are real figures (a 3-panel tree
  diagram, two line charts) extracted at good visual fidelity,
  legends/axes/labels all legible. The other 2 are small inline
  formulas (`π^σ_i(h) = ...`, `v_i(σ,I) = Σ...`) that the layout model
  misclassified as raster pictures instead of parsing as text/math —
  concrete, visual evidence of the same math-handling weakness seen in
  the Markdown.

This is the real baseline Granite-Docling would need to improve on:
not "does it get more pages," but specifically **does it recover
equations and correct the math-notation reading-order collapse**.

## Stage 1 (abandoned): full-page Granite-Docling via Docling's own VlmPipeline

Before the user proposed the leaner llama.cpp-based framework, this
was attempted first: Docling's `VlmPipeline` with
`GRANITEDOCLING_TRANSFORMERS` (the HF `transformers` backend, CPU),
same PDF, same machine.

```bash
python3 run_granite_docling_pipeline.py sampling-variance-CFR.pdf out-granite
```

**Killed after 92+ minutes**, no page had completed (7-page PDF,
observed pace implied roughly 13+ min/page and climbing). Peak RSS
during the run stayed a modest ~2.1GB (no OOM risk — this host has
**zero swap configured**, a real fact worth knowing before running
anything memory-heavier here), so the blocker was purely throughput,
not memory. This result is what motivated testing Granite-Docling via
llama.cpp on the Pixel instead of via Python/transformers on Overmind
— full per-page VLM conversion in this configuration is not
operationally reasonable regardless of output quality.
[`run_granite_docling_pipeline.py`](run_granite_docling_pipeline.py) is
kept for reference; not recommended to rerun as-is.

## Stage 2: Granite-Docling via llama.cpp on Pixel 6

### Artifacts, verified before use

- llama.cpp source: `https://github.com/ggml-org/llama.cpp`, tag
  `b11028` (2026-09-17), commit `972d2313bc0bf0a45f634f77d95c9fb03aeab12c`.
- Confirmed real, merged Granite-Docling support before building
  anything: GitHub PRs
  [#16206](https://github.com/ggml-org/llama.cpp/pull/16206) ("Model:
  Granite docling + Idefics3 preprocessing (SmolVLM)") and
  [#16438](https://github.com/ggml-org/llama.cpp/pull/16438) ("Granite
  Docling stopping"), both merged early October 2025, well before this
  build.
- Model: `ibm-granite/granite-docling-258M-GGUF` (official IBM repo,
  not a community conversion) —
  `granite-docling-258M-bf16.gguf` (332MB) +
  `mmproj-model-f16.gguf` (190MB, the vision projector). Cached via the
  established HF-cache convention at
  `/mnt/models/huggingface` on overmind-01.

### Build (Android NDK cross-compile, matches this project's existing spike convention)

```bash
NDK=~/Library/Android/sdk/ndk/27.1.12297006
cmake -S . -B build-android \
  -DCMAKE_TOOLCHAIN_FILE=$NDK/build/cmake/android.toolchain.cmake \
  -DANDROID_ABI=arm64-v8a \
  -DANDROID_PLATFORM=android-28 \
  -DGGML_NATIVE=OFF -DGGML_OPENMP=OFF -DGGML_LLAMAFILE=OFF -DLLAMA_OPENSSL=OFF \
  -DGGML_CPU_KLEIDIAI=ON \
  -DCMAKE_BUILD_TYPE=Release
cmake --build build-android --config Release --target llama-mtmd-cli llama-server -j8
```

`GGML_CPU_KLEIDIAI=ON` per the plan's "treat CPU/KleidiAI as the
expected path" — enables Arm's optimized CPU microkernels; no Vulkan/GPU
work attempted, per scope. No `libc++_shared.so` dependency (statically
linked) and no CUDA/GPU shared-library dependencies — confirmed via
`llvm-readobj -d`, not assumed.

### Deploy

```bash
adb push build-android/bin/{libggml-base.so,libggml-cpu.so,libggml.so,libllama-common.so,libllama-server-impl.so,libllama.so,libmtmd.so,llama-mtmd-cli,llama-server} /data/local/tmp/llamacpp/
adb push granite-docling-258M-bf16.gguf mmproj-model-f16.gguf /data/local/tmp/llamacpp/
adb shell chmod +x /data/local/tmp/llamacpp/llama-mtmd-cli /data/local/tmp/llamacpp/llama-server
```

### CLI result (correct)

```bash
adb shell 'LD_LIBRARY_PATH=/data/local/tmp/llamacpp /data/local/tmp/llamacpp/llama-mtmd-cli \
  -m /data/local/tmp/llamacpp/granite-docling-258M-bf16.gguf \
  --mmproj /data/local/tmp/llamacpp/mmproj-model-f16.gguf \
  --image test-figure.png -p "Convert this page to docling." -n 2048 --temp 0'
```

Test image: one of the real figures extracted in Stage 1 (a line chart,
`out-default/.../image_000003_....png`).

```text
<doctag><picture><loc_0><loc_0><loc_500><loc_500><line_chart></picture>
</doctag>
```

Correct on every count that matters: real `<doctag>` structure, correct
element type (`picture`), correct specific classification
(`line_chart` — the image genuinely is one), full-image bounding box.
Deterministic: reran with `--temp 0`, byte-identical output both times.

**Timing** (external wall-clock via `time adb shell ...`): **1m44.560s**
total. Internal log shows this is almost entirely vision encoding — 27
image-patch chunks, ~6.2s each (~99s of the ~104s), with fast
generation once encoding finished.

**Memory**: sampled `/proc/<pid>/status` `VmRSS` every 15s during a run
— stable at **~813MB** throughout. Notably lower than the
Python/transformers path's ~2.1-2.5GB.

**Thermal**: `dumpsys thermalservice` TPU-zone sensor (shared thermal
zone, not TPU-specific engagement — nothing here uses `google-edgetpu`)
rose from a ~26°C baseline to ~38°C after one run, ~43°C after two
consecutive runs. Noticeable, not alarming — no throttling threshold is
configured for this sensor on this device (`NaN` in both directions,
consistent with earlier findings elsewhere in this project).

**Model load time** (via `llama-server` log): **~1.4 seconds** —
dramatically faster than the Python/transformers path's model
construction overhead.

### HTTP server: two attempts, both short of "correct"

#### Attempt 1 — OpenAI-compatible `/v1/chat/completions`

```bash
curl http://<pixel>:8768/v1/chat/completions -d '{"messages":[{"role":"user","content":[
  {"type":"text","text":"Convert this page to docling."},
  {"type":"image_url","image_url":{"url":"data:image/png;base64,..."}}
]}],"temperature":0,"max_tokens":2048}'
```

**Broken**: degenerate repeating `"0.0 0.0 0.0 ..."` for the full
2048-token budget (`finish_reason: "length"`), 5m17s total. This is
not a configuration mistake on this side — it matches a real, specific,
still-apparently-unresolved upstream report:
[llama.cpp#16601](https://github.com/ggml-org/llama.cpp/issues/16601),
"Eval bug: granite docling outputs differ between llama-mtmd-cli and
openai-compatible chat completion endpoints" (opened Oct 15 2025,
labeled `bug-unconfirmed`/`stale`, no documented fix found in the
visible issue content). The reporter's own hypothesis — that image
slicing/prompt formatting used by `mtmd-cli` isn't fully replicated by
`llama-server`'s OpenAI-compatible code path — matches what was found
independently here.

#### Attempt 2 — native `/completion` endpoint, hand-built prompt

The server docs describe a lower-level, non-OpenAI shape:
`{"prompt": {"prompt_string": "...", "multimodal_data": ["<base64>"]}}`,
with a literal media-marker placeholder inside `prompt_string` standing
in for where the image goes.

**First failure** (before understanding the marker): every request
returned `{"error":{"message":"Failed to tokenize prompt"}}`, and the
server log showed `number of media markers in text (0) does not match
number of bitmaps (1)` even though the literal string `<__media__>`
(the library's documented default marker, confirmed via
`mtmd_default_marker()` in `tools/mtmd/mtmd.cpp`) was verifiably present
in the JSON actually sent (checked by round-tripping the request body
through `json.load`).

**Root cause, found by reading `tools/server/server-common.cpp`**:
`llama-server` does **not** use the library's default marker. Its own
`get_media_marker()` generates a **random per-process marker**
(`<__media_XXXXXXXX__>`) on every server start, unless the
`LLAMA_MEDIA_MARKER` environment variable is set explicitly — this
constraint isn't mentioned in the server's own `--help` output or
README multimodal section; it was found only by reading source. Fixed
by restarting with `LLAMA_MEDIA_MARKER="<__media__>"` set, confirmed via
the server's own `/props` endpoint (`"media_marker": "<__media__>"`)
before retrying.

**After the marker fix, tokenization succeeded**, and the image tiling
was genuinely correct — the prompt echoed back
`<row_1_col_1>...<row_3_col_4>` plus a `<global-img>` tile, the expected
Idefics3-style slicing, matching what `mtmd-cli` does internally. The
model even read real content off the image: the output included
`MCCFR`, `Algorithm 1`, and `Variance` verbatim — the chart's actual
legend and axis labels. **But** the output was not wrapped in valid
`<doctag>...</doctag>` structure and still degraded into the same
`0.0` repetition pattern after that real content.

**Working hypothesis, not confirmed**: the exact chat-template wrapping
`mtmd-cli` applies automatically (reading the GGUF's own embedded
chat-template metadata) was hand-reconstructed here —

```text
<|start_of_role|>user<|end_of_role|><__media__>Convert this page to docling.<|end_of_text|>
<|start_of_role|>assistant<|end_of_role|>
```

— by eye, from the template `mtmd-cli` printed at startup for a
*generic* example exchange, not the literal template this specific
request needs. A 258M-parameter model fine-tuned narrowly for one
output format is plausibly far more sensitive to exact template
fidelity (extra/missing whitespace, a wrong special-token boundary,
etc.) than a larger general-purpose chat model would be, which would
explain "real content extracted, but structurally wrong" rather than
either full success or full failure.

#### Attempt 3 — decisive test: `/apply-template` then `/completion`, no hand-reconstruction at all

Rather than keep guessing at the template by eye, `llama-server` has a
dedicated endpoint, `/apply-template`, that returns the model's *own*
exact chat-template output for a given `messages` array — the same
input shape `/v1/chat/completions` takes — without running inference.
This eliminates the one remaining unverified variable in Attempt 2.

```bash
curl http://<pixel>:8768/apply-template -d '{"messages":[{"role":"user","content":[
  {"type":"text","text":"Convert this page to docling."},
  {"type":"image_url","image_url":{"url":"data:image/png;base64,..."}}
]}]}'
```

```text
{"prompt":"<|start_of_role|>user<|end_of_role|>Convert this page to docling.<__media__><|end_of_text|>\n<|start_of_role|>assistant<|end_of_role|>"}
```

**This immediately revealed a real discrepancy**: the server's actual
template places the media marker *after* the text
(`"...docling.<__media__>"`), the reverse of what was hand-built in
Attempt 2 (`"<__media__>Convert this page..."`). A genuinely promising
lead — until it was tested.

Feeding this exact server-generated prompt string (marker order
correct, verified) straight into `/completion` with the same
`multimodal_data`:

```text
{"content":"<doc> 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 ...
 (repeats for the full requested budget)",
 "tokens_predicted":512,"stop_type":"limit", ...
 "prompt":"<|start_of_role|>user<|end_of_role|>Convert this page to docling.<fake_token_around_image><row_1_col_1>...<row_3_col_4>\n\n<fake_token_around_image><global-img><fake_token_around_image><|end_of_text|>\n<|start_of_role|>assistant<|end_of_role|>"}
```

**Still the same degenerate `0.0` repetition** — this time burning the
*entire* requested token budget (512/512, `stop_type: "limit"`), even
though every previously-suspect variable is now confirmed correct:
marker placement (from the server's own template), image tiling
(`row_1_col_1`...`row_3_col_4` + `global-img`, byte-identical shape to
what the working CLI path produces internally), and the chat template
itself (the server's own output, not a guess). There is nothing left to
hand-reconstruct.

**Conclusion, not a hypothesis anymore**: this is a genuine
Granite-Docling-specific defect in `llama-server`'s multimodal
*generation* path (something downstream of prompt construction, since
prompt construction is now proven correct), not a templating mistake on
this end and not the marker issue. `libmtmd`/CLI inference is healthy;
`llama-server`'s serving path is broken for this specific model, as of
build `b11028`. Per the plan this test was meant to settle exactly this
question, debugging stopped here rather than digging into
`llama-server`'s internal generation loop itself — that's upstream
`llama.cpp` engineering, not something to chase inside a "keep this
small" experiment.

### CLI vs. server, side by side

| | `llama-mtmd-cli --image` | `/v1/chat/completions` | `/completion`, hand-built template | `/completion`, server's own `/apply-template` output |
| --- | --- | --- | --- | --- |
| Tokenizes | yes | yes | no, until `LLAMA_MEDIA_MARKER` set | yes |
| Marker placement | n/a (internal) | n/a | before text (wrong, as it turned out) | after text (**confirmed correct**, from the server itself) |
| Image tiling | correct (internal) | unknown — never got past garbage | **confirmed correct** (`row_*_col_*` + `global-img`) | **confirmed correct**, identical shape |
| Reads real image content | yes | no | **yes** (legend/axis text verbatim) | not inspected (immediate `0.0` repetition) |
| Valid `<doctag>` structure | **yes** | no | no | **no** |
| Deterministic/reproducible | yes (`--temp 0`, 2 runs identical) | not retested | not retested | yes (`--temp 0`) |

Every variable that could plausibly explain the difference between the
working CLI and the broken server path has now been eliminated one at a
time — the marker, the image tiling, and finally the chat template
itself. What's left is `llama-server`'s own multimodal generation code,
which is where this stops without a llama.cpp-level fix.

### Options for continuing this path (not attempted further this pass — likely blocked on an upstream fix)

1. **File or find an upstream llama.cpp issue** describing this exact
   symptom (server generates degenerate output even with a verified
   correct prompt/tiling, while `mtmd-cli` on the identical model+image
   is correct) — a more precise report than the existing
   [#16601](https://github.com/ggml-org/llama.cpp/issues/16601), which
   was closed without a documented fix and predates this decisive
   isolation.
2. **Diff `llama-mtmd-cli`'s and `llama-server`'s actual generation code
   paths** (both use `libmtmd` for encoding, but something in how the
   server drives generation afterward — batching, KV cache handling,
   sampling defaults — evidently differs) — real upstream-engineering
   effort, not something to attempt inside this experiment's scope.
3. **Check whether `/completion` (or a variant) can accept a structured
   `messages` array plus `multimodal_data`**, letting the server apply
   its own chat-template logic the same way `mtmd-cli` does internally,
   instead of requiring a raw pre-templated string. Not confirmed to
   exist in this build; worth checking `server-common.cpp`/
   `server-chat.cpp` more thoroughly before assuming it doesn't.
4. **Use the CLI-per-call pattern instead** (recommended, given the
   above): shell out to `llama-mtmd-cli` per image needing enrichment
   from the Overmind-side integration script (e.g. over the existing
   AVF/ADB path, or a tiny wrapper), accepting the cost of a fresh model
   load (~1-2s) and full vision encoding (~1-2 min) per call, with no
   warm server. Proven correct today, with no upstream dependency.
5. **Watch upstream `llama.cpp#16601`** (and file a sharper follow-up
   per option 1) for a real fix landing — this project is already on
   today's latest tag, so "wait for a newer release" isn't actionable
   without a specific fix commit to target.

## Follow-up: ONNX vision encoder correctness (off-device, HF reference)

Before any on-device NNAPI work, verified that
`onnx-community/granite-docling-258M-ONNX`'s `vision_encoder.onnx`
(the official, pre-split export) actually matches the real HF
`transformers` model's output, on the exact same image and processor
settings — [`compare_vision_encoder.py`](compare_vision_encoder.py):

```bash
python3 compare_vision_encoder.py test-chart.png <hf_checkpoint_dir> <onnx_vision_encoder_path>
```

```text
HF image_hidden_states shape: (13, 64, 576)
ONNX image_features shape:    (13, 64, 576)

max_abs_error:  1.625e-03
mean_abs_error: 6.194e-05
mean_rel_error: 4.744e-05
cosine_sim:     1.00000000
verdict: PASS
```

The 13-tile shape independently confirms the same image tiling seen in
the `llama-mtmd-cli` DocTags output above (12 sub-tiles + 1 global
image). One real snag along the way: HF's local cache stores files as
symlinks into a shared, independently-hashed blob store, which ONNX
Runtime's external-data loader rejects (`External data path escapes
model directory`) since the `.onnx` and `.onnx_data` blobs resolve to
different real directories — fixed by copying both (dereferenced) into
one plain directory before loading.
[`dump_vision_encoder_tensors.py`](dump_vision_encoder_tensors.py)
saves the exact input/reference tensors from this same run as raw
binary files, used by the on-device spike below.

## Follow-up: does ORT/NNAPI accelerate the vision-encoding bottleneck? No — closed decisively

The CLI path's ~104s per image is ~99% vision encoding. Separate spike
[`hosts/cerebrate-pixel6/spikes/granite-docling-vision-encoder/`](../../hosts/cerebrate-pixel6/spikes/granite-docling-vision-encoder/README.md)
isolated the real ONNX vision encoder
(`onnx-community/granite-docling-258M-ONNX`) and tested it against ORT's
NNAPI execution provider, using the same correctness-tensor discipline
as the MobileNet ORT characterization. **Result: correctness passes
cleanly (bit-identical output, `cosine_sim=1.0`), but NNAPI never
partitions a single node from this graph** — confirmed both as-exported
(dynamic `batch_size`/`num_images` dimensions) and after fixing those
shapes to static values via `onnxruntime.tools.make_dynamic_shape_fixed`
(a real, plausible cause per ONNX Runtime's own mobile docs, eliminated
directly rather than assumed). `logcat` shows NNAPI discovers
`google-edgetpu` but never logs a `GetCapability` partitioning pass or a
Darwinn compilation, for either graph. Closed: the ~99s vision-encoding
cost stays a CPU cost on this Pixel 6 via this export and ORT version;
no further NNAPI/TPU work planned on this specific graph.

## Follow-up: does LiteRT-LM's own `.litertlm` conversion compare to the `llama.cpp` path? Blocked, not answered

Separate spike
[`hosts/cerebrate-pixel6/spikes/granite-docling-litertlm/`](../../hosts/cerebrate-pixel6/spikes/granite-docling-litertlm/README.md)
tried `litert-community/granite-docling-258M` as a same-runtime
alternative to the CLI path (Cerebrate already depends on LiteRT-LM for
`cerebrate-generate`). **Never reached a quality comparison**: the
plain C API's `SessionAdvanced` path (used by `generate_content` and
`run_prefill`/`run_decode` alike) cannot accept image input at all —
verified against the real LiteRT-LM source across three consecutive
releases, not one error message taken at face value. A genuinely
working C++ path exists (`InputImage(TensorBuffer)`, LiteRT-LM's full
C++ SDK — a heavier build than the plain-C spikes elsewhere in this
project), but wasn't built out for this spike; the proven `llama.cpp`
path already meets the current need. `models/schema.json` gained
`api_requirements`/`cerebrate_support` fields as a direct result, so a
future multimodal `.litertlm` gets its required integration surface
checked before staging or benchmarking, instead of rediscovering this.

## Environmental findings (worth keeping in mind for future work on this host)

- **`overmind-01` has zero swap configured.** No OOM was hit in this
  experiment, but any future memory-heavier run has no degradation path
  — it's a hard OOM-kill, not a slowdown.
- **`uv`'s torch backend resolution defaulted to a CUDA-tagged build**
  (`torch==2.14.0+cu130`) even on this GPU-less aarch64 host, ballooning
  the venv to 5.7GB before `--torch-backend cpu` fixed it down to 1.3GB.
  Worth specifying explicitly on any future ML-package install here.
- **`uv`'s shared package cache (`~/.cache/uv`) lives on the OS microSD
  card**, not the SSD, and reached 6.3GB over the course of this one
  experiment. Not fixed here (relocating it globally via `UV_CACHE_DIR`
  is a host-wide change, out of scope for "keep this experiment
  small") — worth revisiting if more ML-heavy experiments land on this
  host.
- **RapidOCR's default model source is `modelscope.cn`** (China-hosted).
  One download attempt timed out after 60s; an immediate retry
  succeeded in under a second per file. Treated as transient here, but
  worth knowing this dependency exists if it recurs.
