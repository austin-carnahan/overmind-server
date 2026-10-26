"""YOLOE device outputs (litert-e2e .bin files: boxes, score, cls, coef,
protos in some order, identified by size and value range) through the task
evaluator (Ultralytics' NMS + masks, YOLOE predictor settings) vs
Ultralytics' predictions from the original .pt on the same letterboxed
photos: detections matched one-to-one by class and box IoU >= 0.5 ("any-class":
reference detections with any detection at IoU >= 0.5, label ignored); score
differences; mask IoU of matched detections.
usage: <yoloe dir> <model tag (v8s|11s)> <out dir>..."""
import sys, glob, os
import numpy as np
sys.argv, args = sys.argv[:1] + ["-", "-"], sys.argv[1:]
import yoloe_prep as yp
Y, tag, outs = args[0], args[1], args[2:]
v = {"v8s": "yoloe-v8s-seg-pf", "11s": "yoloe-11s-seg-pf"}[tag]

def load(d, i):
    o = {}
    for f in glob.glob(f"{d}/{i}_o*.bin"):
        a = np.fromfile(f, np.float32); n = a.size
        if n == 4 * 8400: o["boxes"] = a.reshape(1, 4, 8400)
        elif n == 32 * 8400: o["coef"] = a.reshape(1, 32, 8400)
        elif n == 32 * 160 * 160: o["protos"] = a.reshape(1, 32, 160, 160)
        elif n == 8400: o["cls" if a.max() > 1.5 else "score"] = a.reshape(1, 8400)
    return o

def iou(a, b):
    lt = np.maximum(a[:, None, :2], b[None, :, :2]); rb = np.minimum(a[:, None, 2:], b[None, :, 2:])
    inter = np.clip(rb - lt, 0, None).prod(-1); ar = lambda x: (x[:, 2] - x[:, 0]) * (x[:, 3] - x[:, 1])
    return inter / (ar(a)[:, None] + ar(b)[None] - inter + 1e-9)

print(f"{'config':26} {'ref dets':>8} {'got':>4} {'matched':>7} {'any-class':>9} {'box IoU min':>11} {'score maxdiff':>13} {'mask IoU min':>12} {'mask IoU mean':>13}")
for d in outs:
    tot = dict(ref=0, got=0, m=0, a=0); bmin, smax, mmin, mmean = [], [], [], []
    for i in range(8):
        o = load(d, i); t = np.load(f"{Y}/{v}-task{i}.npz")
        det, m = yp.detections(o["boxes"], o["score"], o["cls"].astype(np.int64), o["coef"], o["protos"])
        tm = np.unpackbits(t["masks"], axis=-1)[..., :640].astype(bool)
        tot["ref"] += len(t["conf"]); tot["got"] += len(det)
        if not len(det) or not len(t["conf"]): continue
        A = iou(t["xyxy"], det[:, :4])                                  # class-agnostic: any detection at IoU >= 0.5
        tot["a"] += int((A.max(1) >= 0.5).sum())
        U = A.copy(); U[t["cls"][:, None] != det[None, :, 5]] = 0
        used = set()
        for r in np.argsort(-t["conf"]):
            j = int(np.argmax(np.where([k in used for k in range(len(det))], -1, U[r])))
            if U[r, j] >= 0.5 and j not in used:
                used.add(j); tot["m"] += 1; bmin.append(U[r, j]); smax.append(abs(det[j, 4] - t["conf"][r]))
                inter = (m[j] & tm[r]).sum(); uni = (m[j] | tm[r]).sum(); mi = inter / max(uni, 1); mmin.append(mi); mmean.append(mi)
    print(f"{os.path.basename(d):26} {tot['ref']:>8} {tot['got']:>4} {tot['m']:>7} {tot['a']:>9} {min(bmin):11.4f} {max(smax):13.4f} {min(mmin):12.4f} {np.mean(mmean):13.4f}")
