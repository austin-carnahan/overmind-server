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
