"""Task-level accuracy of device encoder outputs: embeddings (raw NHWC float32,
one file per photo, <photo>_o0.bin as tflite-nnapi-bench writes them) decoded
by the original prompt encoder + mask decoder with YOLOE's 132 boxes, masks
compared with the original model's. Also embedding cosine / rel L2.
usage: edgesam_task_accuracy.py <dl-edgesam dir> <out dir (ref*.npz)> <device output dir> [label]"""
import sys
import numpy as np
from edgesam_common import load_edgesam, decode, mask_stats, summarize
D, OUT, DEV = sys.argv[1:4]
label = sys.argv[4] if len(sys.argv) > 4 else DEV
_, pred = load_edgesam(D, "bicubic")
acc = ([], [], []); cosines = []; rels = []
for i in range(8):
    ref = np.load(f"{OUT}/ref{i}.npz")
    emb = np.fromfile(f"{DEV}/{i}_o0.bin", np.float32).reshape(1, 64, 64, 256).transpose(0, 3, 1, 2)
    e, r = emb.ravel().astype(np.float64), ref["emb"].ravel().astype(np.float64)
    cosines.append(e @ r / np.linalg.norm(e) / np.linalg.norm(r)); rels.append(np.linalg.norm(e - r) / np.linalg.norm(r))
    masks, _ = decode(pred, emb, ref["boxes"], tuple(ref["original_size"]), tuple(ref["input_size"]))
    refm = np.unpackbits(ref["masks"], axis=-1)[..., :ref["mask_shape"][-1]].astype(bool)
    iou, fl = mask_stats(masks, refm)
    for lst, v in zip(acc, (iou, fl, refm.sum((1, 2)))): lst.append(v)
print(f"{label}: embeddings cosine min {min(cosines):.6f}, rel L2 max {max(rels):.2e}")
ious = summarize(f"{label} task level", *acc)
