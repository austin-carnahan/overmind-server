"""Published RF-DETR pipeline (device graph A -> host step -> device graph B)
vs the original rfdetr model, at task level: detections matched by box IoU,
classes, scores, and mask IoU of matched instances; summed over 8 photos."""
import sys, os, glob
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rfdetr_host import detections, compare, NQ, NC, M
R = sys.argv[1]; configs = sys.argv[2:]
print(f"{'config':14} {'ref dets':>8} {'got':>4} {'matched':>7} {'same class':>10} {'box IoU min':>11} {'mask IoU min':>12} {'mask IoU mean':>13} {'score maxdiff':>13}")
for c in configs:
    tot = dict(ref=0, got=0, matched=0, same_cls=0); bmin, mmin, mmean, smax = [], [], [], []
    for i in range(8):
        r = np.load(f"{R}/ref{i}.npz")
        outs = {os.path.getsize(f) // 4: np.fromfile(f, np.float32) for f in glob.glob(f"{R}/pulledB/outB-{c}/{i}_o*.bin")}
        got = (outs[NQ * NC].reshape(NQ, NC), outs[NQ * 4].reshape(NQ, 4), outs[NQ * M * M].reshape(NQ, M, M))
        res = compare(detections(r["logits"], r["boxes"], r["masks"]), detections(*got))
        for k in tot: tot[k] += res[k]
        if res["box_iou_min"] is not None:
            bmin.append(res["box_iou_min"]); mmin.append(res["mask_iou_min"]); mmean.append(res["mask_iou_mean"]); smax.append(res["score_maxdiff"])
    print(f"{c:14} {tot['ref']:>8} {tot['got']:>4} {tot['matched']:>7} {tot['same_cls']:>10} {min(bmin):11.4f} {min(mmin):12.4f} {np.mean(mmean):13.4f} {max(smax):13.4f}")
