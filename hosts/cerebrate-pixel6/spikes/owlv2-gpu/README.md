# owlv2-gpu

OWLv2 (`google/owlv2-base-patch16-ensemble`, revision `cfd3195b`) on the
Pixel 6 — Step 5 of the
[Segmentation and Labeling Lane](../../../../design-notes/Cerebrate%20Pixel%206%20%E2%80%94%20Segmentation%20and%20Labeling%20Lane.md).
No published LiteRT/TFLite conversion of OWLv2 or OWL-ViT existed (only ONNX
builds), so these are our own `litert-torch` 0.10.0 conversions. Results:
[experiments/pixel6/results.md](../../../../experiments/pixel6/results.md).

The model is split so that **the vocabulary is data**, never part of a graph:

| Graph | Input | Output | Where it runs |
| --- | --- | --- | --- |
| Image tower ([`convert_owlv2.py`](convert_owlv2.py)), 354 MB fp32 | `pixel_values [1,3,960,960]`, position table `[1,3601,768]` | per patch (3,600): box logits, objectness, normalized class embedding, logit shift, logit scale | GPU, fp32 |
| Text tower ([`convert_owlv2_text.py`](convert_owlv2_text.py)), 254 MB fp32 | token ids `[32,16]` int32 | text embeddings `[32,512]` | CPU, or GPU+CPU split |
| Host step (numpy) | tower outputs + query embeddings | `logits = (class_embeds · q̂ + shift) · scale`; `boxes = sigmoid(box_logits + box_bias)` | wherever the service runs |

Preparation of the image tower (each a mathematically identical rewrite,
verified against the original forward):

- the position-embedding table is fed as an input (large constant, rule 3);
- the class-token merge is a broadcast multiply rather than `broadcast_to`;
- **the box-bias add is on the host.** On the Mali-G78 the GPU computed
  `box_head(feats) + box_bias` (a baked `[1,3600,4]` constant) with the box
  head's output broadcast from patch 0 — boxes collapsed to the patch grid.
  Scores and objectness were unaffected. Not bisected further.

The text tower takes no attention mask: CLIP's text transformer is causal and
pools at the EOS token, so padding after EOS is inert (identical to
`get_text_features` with the mask, max diff 0).

Image-exemplar queries need no extra graph: run the exemplar image through the
image tower and use the class embedding of its highest-objectness box as the
query — the rule transformers' `Owlv2ForObjectDetection.embed_image_query`
uses (OWL-ViT's older IoU heuristic gives different selections).

## Scripts

- [`convert_owlv2.py`](convert_owlv2.py) `<out>` — image tower; writes eight
  photo inputs, the position table, the 24-query embeddings, the box bias, and
  the original forward's logits/boxes/objectness (stages 1–2).
- [`owlv2_accuracy.py`](owlv2_accuracy.py) `<out> <config…>` — device outputs
  vs the original at task level: detections (score ≥ 0.2, per-query NMS 0.3)
  matched by query and box IoU, top patch per query, objectness top-100.
- [`convert_owlv2_text.py`](convert_owlv2_text.py) `<out> <yoloe.onnx>` — text
  tower; reference embeddings for YOLOE prompt-free's 4,585 class names (read
  from the ONNX export's metadata) and three device batches.
- [`owlv2_step5_refs.py`](owlv2_step5_refs.py) `<out>` — from the original
  model: best label per patch over all 4,585 names, and three exemplar crops
  with `image_guided_detection` results on every photo.
- [`owlv2_step5_eval.py`](owlv2_step5_eval.py) `<out>` — large-vocabulary and
  exemplar checks on the device outputs.

Device runs use `litert-e2e` from
[litert-gpu-transformers](../litert-gpu-transformers/README.md).
