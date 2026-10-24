# yoloe-tpu

YOLOE prompt-free segmentation (Ultralytics 8.4.184 `yoloe-v8s-seg-pf`,
`yoloe-11s-seg-pf`; 4,585 built-in classes) toward the Pixel 6 Edge TPU —
Step 2B of the
[Segmentation and Labeling Lane](../../../../design-notes/Cerebrate%20Pixel%206%20%E2%80%94%20Segmentation%20and%20Labeling%20Lane.md).
No usable published int8/TPU conversion exists (Qualcomm AI Hub's
YOLOE-Segmentation card ships no files, for licensing reasons). Results:
[experiments/pixel6/results.md](../../../../experiments/pixel6/results.md).

## Model preparation ([`yoloe_prep.py`](yoloe_prep.py))

Graph surgery on the fp32 ONNX exports ([`export_yoloe.py`](export_yoloe.py)),
each step exact (reduced outputs = unmodified ONNX, max difference 0):

- **Reduced outputs.** `output0` `[1, 4+4585+32, 8400]` (~155 MB fp32, over
  `cerebrate-graph`'s 64 MB tensor limit) is a Concat of boxes, sigmoid class
  scores and mask coefficients; the three tensors are taken directly and the
  best score and class per anchor appended: `boxes [1,4,8400]`,
  `score [1,8400]`, `cls [1,8400]` (int64), `coef [1,32,8400]`, protos
  `[1,32,160,160]`.
- **Split → Slice.** ORT 1.30's NNAPI provider fails to build these Splits
  (equal channel halves): `AddNnapiSplit count [0] does not evenly divide
  dimension`.
- **DFL box decoding as a 2-D softmax.** The Edge TPU's converter rejected the
  box head's 4-D softmax (`RET_CHECK axis == -1 || axis == input_rank - 1`),
  even moved to the last axis; as `[33600,16]` softmax → matmul with the DFL
  weights it is accepted.

Inputs are the eight lane photos letterboxed to 640×640 (Ultralytics
`LetterBox(auto=False)`). Ultralytics' PyTorch predict otherwise letterboxes
to a minimal rectangle, so its predictions are only comparable to the
fixed-shape models on the same square input
([`yoloe_same_input_check.py`](yoloe_same_input_check.py): identical then).
The task-level evaluator (`detections()`) applies Ultralytics' own NMS and
mask functions with the YOLOE predictor's settings — conf 0.25, IoU 0.7,
**class-agnostic NMS** — and reproduces the `.pt` predictions on 8/8 photos
for both models.

## GPU path ([`yoloe_convert_gpu.py`](yoloe_convert_gpu.py))

Float LiteRT graphs via `litert-torch` from the fused Ultralytics model in
export mode, with the head's `_inference` returning boxes, sigmoid scores and
mask coefficients separately (no 155 MB concat) plus best score and class
(as float: GPU float I/O). Fully delegated on the GPU; scored by
[`yoloe_task_accuracy.py`](yoloe_task_accuracy.py) (detections matched by
class and box IoU, plus a label-agnostic count; mask IoU).

## TPU partition and int8

- [`yoloe_partition.py`](yoloe_partition.py) — splits each prepared model at
  the head: backbone + neck (images → feature maps 80²/40²/20²) for the Edge
  TPU, head (with the 4,585-class projection) for the CPU/GPU; the two halves
  chained equal the whole (difference 0).
- [`yoloe_calib_select.py`](yoloe_calib_select.py) — 300 indoor COCO val2017
  photos (room-object categories, at least one large indoor anchor),
  excluding every COCO image the test photos come from.
- [`yoloe_quantize.py`](yoloe_quantize.py) — ONNX Runtime static int8 (QDQ,
  uint8 activations, int8 per-channel weights; MinMax, percentile or entropy
  calibration). The histogram calibrators hold every activation in memory:
  percentile ran with 32 photos (100 was killed for memory on the Mac).
- [`yoloe_chain_desktop.py`](yoloe_chain_desktop.py) — backbone (fp32/int8) →
  fp32 head on the desktop, in the device output layout, for the task check.

## Device runs ([`yoloe_run.sh`](yoloe_run.sh))

Hand-launched `cerebrate-graph` worker per (model, backend) on a spare port,
the eight photos through `graph-client` from the guest, NNAPI partitioning
and Edge TPU driver lines from logcat.

**Caution:** Edge TPU compilation of these large graphs exhausted the phone's
memory once (2026-10-24): the low-memory killer took the Terminal app and the
Debian VM with it (MLServer down ~7 minutes; recovered with
`adb shell am start -n com.android.virtualization.terminal/.new2.ui.MainActivity`).
Don't run further TPU compiles of these graphs without a plan for that.
