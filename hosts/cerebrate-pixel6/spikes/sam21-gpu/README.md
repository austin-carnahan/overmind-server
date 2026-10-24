# sam21-gpu

**Status:** in progress — Step 2A's SAM 2.1 sequence in the
[Segmentation and Labeling Lane](../../../../design-notes/Cerebrate%20Pixel%206%20%E2%80%94%20Segmentation%20and%20Labeling%20Lane.md).

SAM 2.1 Hiera-Tiny (`facebook/sam2.1-hiera-tiny`, revision `de431c40…`) on the
Pixel 6 GPU through LiteRT 2.3.0, measured with
[`litert_e2e`](../litert-gpu-transformers/bench.cc) (now multi-input /
multi-output) and judged against the **unmodified** PyTorch model.

The transformers implementation reproduces browser-perception's ONNX encoder
and decoder outputs exactly (cosine 1.000000; IoU scores equal to 6 decimals),
so it is a valid reference despite loading a `sam2_video` checkpoint into
`Sam2Model`.

## Results so far (2026-10-24)

**Box-prompted decoder** ([`convert_decoder.py`](convert_decoder.py), our own
conversion, 20.7 MB fp32): GPU-only compilation fails — 42 of 397 ops can't go
to the GPU (5-D reshapes and slices from the `[1,1,3,256,256]` mask tensor,
`SELECT_V2` from point-label masking). With GPU + CPU fallback (3 GPU
partitions), eight samples (4 photos × 2 boxes, [`prep_decoder_inputs.py`](prep_decoder_inputs.py)),
end to end, judged by [`accuracy.py`](accuracy.py):

| Path | End to end | Worst mask IoU | Pixels flipped | Same best mask |
| --- | --- | --- | --- | --- |
| CPU | 148 ms | 1.00000 | 0 | 8/8 |
| **GPU+CPU fp32** | **82 ms** | **1.00000** | **0** | 8/8 |
| GPU+CPU fp16 | 66 ms | 0.578 | 5,718 | 8/8 |

**Image encoder:** 10.2 s per image on CPU. As converted, only 69 of 931 ops
are GPU-eligible (6-/8-D window reshapes, 5-D q/k/v, `FULLY_CONNECTED` on 6-D
inputs, `BROADCAST_TO`/`GATHER_ND` from position-embedding interpolation).
[`prepare_encoder.py`](prepare_encoder.py) rewrites those exactly (≤4-D
windowing, q/k/v split, baked position embedding, unused neck position
encodings dropped, no-memory embedding folded into its level's conv bias) and
verifies at stage 1 (all four photos, max abs ≤ 9e-6) and stage 2 (cosine
1.000000). Not yet run on the device.

Then `litert-community` turned out to publish GPU-clean fp16 conversions of
both halves; per the lane's Section 4.7 policy they are evaluated next, with
these results as the FP32 comparison.

## Published conversions and the GPU-clean box decoder (2026-10-24)

Full numbers: [experiments/pixel6/results.md](../../../../experiments/pixel6/results.md#2026-10-24--sam-21-hiera-tiny).

- [`accuracy_encoder.py`](accuracy_encoder.py) scores encoder embeddings
  against the original encoder and, at task level, decodes the eight box
  prompts from the device embeddings with the original fp32 decoder.
- **Our prepared encoder is pixel-identical on the GPU at fp32 (1.38 s vs
  10.2 s CPU).** The published fp16 encoder carries a small fp16-weight error
  even at fp32 compute; pure fp16 compute fails task level on both.
- [`inspect_published.py`](inspect_published.py) found the published decoder
  takes a fixed 2-token prompt (click + padding), while the original encodes a
  box as 3 tokens — so it can't take box prompts as built.
- [`build_box_decoder.py`](build_box_decoder.py) adapts its GPU-clean
  re-authoring (Apache-2.0, attributed in the file) to 3-token boxes with
  rank-4 attention and plain LayerNorm: exact on CPU, **wrong on this GPU at
  every precision** (mask IoU ≈ 0) — a G1 kernel defect under bisection.

## The decoder defect, found, and the published decoder on this device (2026-10-24)

[`bisect_box_decoder.py`](bisect_box_decoder.py): the GPU-clean box decoder's
failure is **large baked constants** — fed as inputs, the fully GPU-resident
decoder is exact at fp32 (80 ms, 0 flipped pixels). The published v2 decoder,
unmodified, with its native point prompts
([`prep_published_point.py`](prep_published_point.py)), runs correctly at fp32
compute on this GPU (its remaining error is its fp16 weights) and fails at
fp16 (worst mask IoU 0.557). Numbers in the
[ledger](../../../../experiments/pixel6/results.md#2026-10-24--sam-21-hiera-tiny).

**Validated SAM 2.1 path on the Pixel 6 (fp32, exact vs the original):** our
prepared encoder (1.38 s/image) + the constants-as-inputs box decoder (80 ms
per box as benchmarked, less with persistent buffers) — vs 10.2 s + ~150–200 ms
per box on CPU.
