# Doclet Optimization Experiments

## Objective

Identify the highest-value ways to reduce Doclet end-to-end PDF → Markdown latency without sacrificing output quality or destabilizing the production pipeline.

Current baseline for the 7-page `sampling-variance-CFR.pdf` paper is approximately:

- Standard Docling conversion on Overmind Pi 4: ~6–6.5 min
- Selective Granite-Docling enrichment on Pixel 6:
  - 5 pictures
  - 9 formulas
  - ~14 VLM calls total
  - current Granite vision path is roughly ~100 s per substantial image
- Expected end-to-end runtime: ~25–30 min

Optimization work should proceed from low-risk measurement/configuration changes toward architectural changes.

## Baseline Instrumentation

Before optimizing anything, record per-stage and per-item timings.

For every conversion capture:

- total conversion wall time
- standard Docling pipeline time
- number of pictures
- number of formulas
- each enrichment item's:
  - type
  - page
  - crop dimensions
  - encoded input dimensions
  - request start/end
  - model processing time
  - generated token count
  - success/failure
- Overmind CPU/RAM/swap peak
- Pixel RSS and temperature
- final Markdown output

Use the same reference PDFs for all experiments.

Primary fixture:

`sampling-variance-CFR.pdf`

Add later:

- mostly textual born-digital PDF
- equation-heavy paper
- figure/chart-heavy paper
- table-heavy paper
- longer 25–50 page document

## Experiment 1 — Crop Resolution

**Question:** Are we sending substantially more pixels to Granite than individual formulas and figures require?

Test several maximum input sizes while keeping everything else constant, for example:

- current behavior
- 768 px long edge
- 512 px
- 384 px
- 256 px where appropriate

Measure:

- vision-processing latency
- formula transcription accuracy
- figure/chart description quality

Run formulas and pictures separately.

### Success criterion

Adopt a smaller resolution if it produces a meaningful latency reduction with no material degradation on the relevant item class.

This is likely the lowest-hanging fruit, especially for small formula crops.

---

## Experiment 2 — Item-Class-Specific Preprocessing

**Question:** Should formulas and pictures use different preprocessing policies?

Compare:

```text
FormulaItem
→ tightly cropped
→ lower resolution
→ formula-specific prompt

PictureItem
→ larger crop
→ higher resolution
→ description-specific prompt
```

Also test small padding margins around formula bounding boxes to determine whether Docling's exact crop is sufficient.

### Success criterion

A class-specific policy substantially reduces formula latency while preserving correct LaTeX transcription.

---

## Experiment 3 — Skip Low-Value Enrichment

**Question:** Are all detected regions worth sending to the VLM?

For each item, record size and type. Test simple gates such as:

- minimum crop area
- minimum dimension
- known decorative/image classes
- figures that already contain useful captions
- formulas whose `orig` representation may already be adequate

Compare output with and without enrichment for those cases.

### Success criterion

Skip an item class or threshold when the VLM result adds little useful information relative to its runtime cost.

---

## Experiment 4 — Parallel Enrichment

**Question:** Can the Pixel process more than one independent VLM request efficiently?

Test concurrency:

```text
1
2
3
```

Measure:

- throughput
- per-request latency
- RSS
- thermals
- errors
- sustained throttling

Do not assume concurrency helps; the vision encoder may already saturate the useful CPU resources.

### Success criterion

Increase concurrency only if total document time falls materially without instability or major per-request slowdown.

---

## Experiment 5 — Persistent Model Residency

The current proven implementation may invoke `llama-mtmd-cli` per request.

Model loading is only ~1.4 s versus roughly ~100 s of current vision processing, so this is expected to be low value.

Still, once larger bottlenecks are addressed, compare:

```text
exec-per-request
vs.
persistent warm libmtmd worker
```

### Success criterion

Only implement persistent residency if model startup becomes a meaningful fraction of total item latency.

At current performance this experiment should remain low priority.

---

## Experiment 6 — llama.cpp Runtime Tuning

Test runtime parameters individually rather than changing many at once:

- CPU thread count
- batch size
- image preprocessing settings
- relevant llama.cpp / mtmd performance flags
- quantized model variants if compatible

Capture both vision-encoding and generation time separately.

### Success criterion

A setting must improve throughput reproducibly without changing output correctness or causing thermal instability.

---

## Experiment 7 — Alternative Granite Artifacts / Quantization

Compare compatible Granite-Docling GGUF variants if available:

```text
BF16 baseline
vs.
quantized variants
```

Measure:

- model RAM
- vision latency
- generation latency
- formula accuracy
- chart/figure quality

### Success criterion

Prefer the smallest/fastest artifact that retains equivalent task quality on the reference suite.

---

## Experiment 8 — Alternative Runtime

Only after the existing llama.cpp path is well characterized, revisit other already-identified runtimes.

Candidates include:

- LiteRT-LM multimodal via the full C++ SDK
- materially newer llama.cpp/libmtmd versions
- future accelerator-compatible runtime/model combinations

Do not revisit:

- current Granite ONNX → NNAPI/TPU path without materially different graph/runtime support
- known-broken `llama-server` Granite path without evidence of an upstream fix

### Success criterion

A replacement runtime must demonstrate a substantial real-world improvement on the same fixtures, not merely theoretical hardware acceleration.

---

## Experiment 9 — Faster Host Hardware

Use the same benchmark suite on future hardware such as a Pi 5 or dedicated inference accelerator.

Separate:

```text
Docling host improvement
from
VLM inference improvement
```

This lets us determine whether faster hardware improves:

- standard PDF parsing/layout/OCR
- VLM enrichment
- both

### Decision Framework

Prioritize changes by:

```text
expected latency reduction
× confidence
÷ implementation/maintenance cost
```

The likely experiment order is:

1. instrumentation
2. crop resolution
3. formula-specific preprocessing
4. skip low-value enrichment
5. concurrency
6. llama.cpp runtime tuning
7. model quantization
8. persistent worker
9. alternative runtimes/hardware

The goal is not to make every component faster. The goal is to identify which few changes materially reduce end-to-end document latency while keeping the existing production architecture boring and reliable.