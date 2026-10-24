# efficientsam3-gpu

EfficientSAM3 RV-M on the Pixel 6 GPU — the bounded spike in the
[Segmentation and Labeling Lane](../../../../design-notes/Cerebrate%20Pixel%206%20%E2%80%94%20Segmentation%20and%20Labeling%20Lane.md).
Model: the fine-tuned full RV-M checkpoint (`efficientsam3_ft/efficientsam3_repvit.pt`,
`Simon7108528/EfficientSAM3` rev `85b05896`, Apache-2.0), RepViT-M1.1 +
MobileCLIP-S0 (context 16) + SAM 3's fusion transformer and heads, code from
[SimonZeng7108/efficientsam3](https://github.com/SimonZeng7108/efficientsam3)
at `bd0936c`. No LiteRT conversion was published; these are our own
`litert-torch` 0.10.0 conversions. Results:
[experiments/pixel6/results.md](../../../../experiments/pixel6/results.md).

## Graphs

| Graph | In | Out | Runs on | Prepared? |
| --- | --- | --- | --- | --- |
| Vision (99 MB) | pixels `[1,3,1008,1008]` | FPN levels 288², 144², 72² × 256 | GPU, 340/340 ops | no — converted as is |
| Text (169 MB) | token ids `[1,16]` int32 | token features `[16,1,256]` | CPU (17 ms; only 68/270 ops GPU-able) | no |
| Grounding (116 MB) | FPN levels, positional encoding, text features, float padding mask, 4 host constants | logits, boxes, presence, masks `[1,200,288,288]` | GPU, 2,490/2,490 ops | yes ([`esam3_prepare.py`](esam3_prepare.py)) |

Host: tokenizer, padding mask (`ids == 0`), the constant 72×72 positional
encoding and the four constants (layer-0 reference boxes, learned queries,
presence token, geometry-token start) — each written once per process — and
score thresholding (`sigmoid(logit) · sigmoid(presence) > 0.5`).

## Grounding preparation (each rewrite exact; verified against the original)

The unprepared graph split 1,056 GPU / 1,586 CPU ops (4.0 s). The GPU
delegate's rejections and the wrong values found by bisecting on the device
led to six rewrites, documented in [`esam3_prepare.py`](esam3_prepare.py):

1. **Constants as inputs** — any op computing only on constants was either
   rejected (`SIGN`, `MEAN`) or, worse, **accepted and computed wrongly**:
   layer 0's attention value projection of the 200×256 learned query
   embeddings (a model weight used as an activation) gave cosine 0.86.
2. Sine-embedding frequencies precomputed.
3. Float padding mask instead of bool (attention adds −1e4 to padded keys —
   exactly 0 weight after the fp32 softmax); single-key attention returns V.
4. Box relative-position bias in 4-D instead of 5-D.
5. `inverse_sigmoid` without its [0, 1] clamp (identity on sigmoid outputs).
6. **Scores for the last decoder layer only**, as a 2-D matmul: with all six
   layers the scores came out wrong although every input to them was exact —
   bisected to reshaping `[1200,1]` into `[6,1,200,1]` (batch 6, one channel).

Export-only fixes (no math change): the box-bias feature size pinned to
Python ints (it arrives as tensors and branches), and inputs/outputs cloned
(aliasing).

## Scripts

- Desktop baseline: [`esam3_reference.py`](esam3_reference.py) (eight photos ×
  24 prompts, overlays), [`esam3_sheets.py`](esam3_sheets.py) (per-prompt review
  sheets), [`esam3_probe.py`](esam3_probe.py) (raw scores, presence),
  [`esam3_profile.py`](esam3_profile.py) (per-stage CPU time),
  [`esam3_geo_check.py`](esam3_geo_check.py) (geometry token depends on the image).
- Conversion: [`esam3_convert.py`](esam3_convert.py) (the three unprepared
  graphs), [`esam3_prepare.py`](esam3_prepare.py) +
  [`esam3_convert_prepared.py`](esam3_convert_prepared.py) (`full`, `nomask`,
  `encoder` variants), [`esam3_evm_vision.py`](esam3_evm_vision.py) (EV-M
  backbone, inspection only), [`esam3_inspect.py`](esam3_inspect.py) (operator
  inspection against the lane's risk patterns).
- Device data and scoring: [`esam3_prep.py`](esam3_prep.py),
  [`esam3_prep_wide.py`](esam3_prep_wide.py),
  [`esam3_grounding_accuracy.py`](esam3_grounding_accuracy.py) (kept set,
  score/box differences, mask IoU, flipped pixels).
- Bisects on the device, in order: [`esam3_bisect.py`](esam3_bisect.py)
  (encoder vs decoder layers), [`esam3_bisect2.py`](esam3_bisect2.py)
  (decoder layer 0), [`esam3_bisect3.py`](esam3_bisect3.py) and
  [`esam3_bisect4.py`](esam3_bisect4.py) (scoring head).

Device runs use `litert-e2e` from
[litert-gpu-transformers](../litert-gpu-transformers/README.md) (output-lock
failures now reported per output instead of aborting).
