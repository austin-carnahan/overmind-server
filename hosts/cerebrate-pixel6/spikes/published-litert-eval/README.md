# published-litert-eval

Evaluation of `litert-community`'s published LiteRT conversions on the Pixel 6,
per the [lane's validation policy](../../../../design-notes/Cerebrate%20Pixel%206%20%E2%80%94%20Segmentation%20and%20Labeling%20Lane.md)
(stages 3–4: device vs CPU, and task level vs the **original** model, since
the published rewritten source isn't available). Results:
[experiments/pixel6/results.md](../../../../experiments/pixel6/results.md).
SAM 2.1's published conversions are evaluated in [sam21-gpu](../sam21-gpu/README.md).

## DINOv2-ViT-S14-LiteRT (revision `f3be8d98`)

Built from timm's `vit_small_patch14_dinov2.lvd142m` at a fixed 448×448
input; outputs the final-normalized patch tokens `[1, 1024, 384]`. Reference:
the original timm model at 448 ([`dinov2_prep.py`](dinov2_prep.py)); task
metric: image similarity ranking from mean-pooled patch features
([`dinov2_accuracy.py`](dinov2_accuracy.py)). Two files: tanh-GELU and
erf-GELU (the activation the official model uses).

## RF-DETR-Seg-Nano-LiteRT (revision `8fee237c`)

Two GPU graphs (A: backbone + encoder + proposals; B: decoder + heads + masks)
with a host step between them and three constants fed as inputs.
[`rfdetr_host.py`](rfdetr_host.py) holds the host step verbatim from the model
card and the task-level comparison (detections matched one-to-one by box IoU
≥ 0.5; class, score, box IoU, and mask IoU of matched instances). Reference:
Roboflow's original `rfdetr` 1.9.3 PyTorch model ([`rfdetr_prep.py`](rfdetr_prep.py)).
On the device graph A runs, the host step runs on graph A's actual device
outputs ([`rfdetr_make_b.py`](rfdetr_make_b.py)), then graph B runs
([`rfdetr_accuracy.py`](rfdetr_accuracy.py) scores the result).

## depth-anything-v2-small (revision `178427e4`)

FP32 weights (plus a dynamic int8-weight variant), fixed `[1,3,518,686]` input
(stretched), relative depth `[1,518,686]`. Reference: the original
Transformers checkpoint `depth-anything/Depth-Anything-V2-Small-hf` at revision
`5426e4f0` ([`depth_prep.py`](depth_prep.py)). Metrics
([`depth_accuracy.py`](depth_accuracy.py)): each device map aligned to the
reference by least-squares scale and shift, then AbsRel, δ<1.25, rank
correlation, and pairwise depth-order agreement on random pixel pairs.

## MI-GAN-512-Places2-LiteRT (revision `179a35d8`)

FP16 weights; input `concat(mask − 0.5, rgb·mask)` `[1,4,512,512]`, output
`[1,3,512,512]` in [−1, 1]. Reference: the fp32 generator **extracted** (tensor
`222` → `1299`) from the pipeline `migan.onnx` hosted by MI-GAN co-author
Andranik Sargsyan (`andraniksargsyan/migan`, revision `406830d0`, MIT) — the
pipeline wraps the generator in resize/composite steps
([`migan_prep.py`](migan_prep.py)). Masks: the top RF-DETR reference instance
per photo, scaled to 512 and dilated (realistic object-removal masks, 1.7–62%
of the image). Metrics ([`migan_accuracy.py`](migan_accuracy.py)): PSNR, SSIM
and relative L2 inside the removed region of the composited result only.
