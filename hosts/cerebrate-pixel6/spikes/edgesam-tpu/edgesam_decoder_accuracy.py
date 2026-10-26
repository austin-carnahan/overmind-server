"""Task-level accuracy of device decoder outputs (one sample per box, as
edgesam_decoder.py listed them: <k>_o0.bin low-res mask logits [256,256],
<k>_o1.bin IoU score): upscaled by the original postprocess_masks,
thresholded, compared with the original model's masks (ref*.npz).
usage: edgesam_decoder_accuracy.py <dl-edgesam dir> <out dir (ref*.npz)> <decoder dir (index.npy)> <device output dir> [label]"""
import sys
import numpy as np, torch
from edgesam_common import load_edgesam, mask_stats, summarize
D, OUT, DEC, DEV = sys.argv[1:5]
label = sys.argv[5] if len(sys.argv) > 5 else DEV
sam, _ = load_edgesam(D, "bicubic")
index = np.load(f"{DEC}/index.npy")
refs = {i: np.load(f"{OUT}/ref{i}.npz") for i in range(8)}
acc = ([], [], []); score_diff = 0.0
for k, (i, j) in enumerate(index):
    ref = refs[i]
    low = torch.from_numpy(np.fromfile(f"{DEV}/{k}_o0.bin", np.float32).reshape(1, 1, 256, 256))
    with torch.no_grad():
        m = (sam.postprocess_masks(low, tuple(ref["input_size"]), tuple(ref["original_size"])) > sam.mask_threshold).numpy()[0]
    refm = np.unpackbits(ref["masks"][j:j + 1], axis=-1)[..., :ref["mask_shape"][-1]].astype(bool)
    iou, fl = mask_stats(m, refm)
    for lst, v in zip(acc, (iou, fl, refm.sum((1, 2)))): lst.append(v)
    score_diff = max(score_diff, abs(float(np.fromfile(f"{DEV}/{k}_o1.bin", np.float32)[0]) - float(ref["scores"][j])))
summarize(f"{label} ({len(index)} boxes)", *acc)
print(f"  max |IoU-score diff| vs original {score_diff:.2e}")
