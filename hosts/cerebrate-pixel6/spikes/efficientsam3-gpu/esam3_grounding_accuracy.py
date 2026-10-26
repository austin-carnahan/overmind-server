"""Grounding graph on the device vs the original model, per sample: raw
differences (kept queries and all 200), the kept set (score = sigmoid(logit) * sigmoid(presence) > 0.5),
score differences, box differences, and mask IoU of kept queries after
thresholding mask logits at 0 (288x288, before upsampling).
usage: <dev dir> <out subdir> [ref prefix (gref) [count (3)]]"""
import sys
import numpy as np
D, O = sys.argv[1], sys.argv[2]
REF = sys.argv[3] if len(sys.argv) > 3 else "gref"; N = int(sys.argv[4]) if len(sys.argv) > 4 else 3
sig = lambda x: 1 / (1 + np.exp(-x))
for s in range(N):
    r = np.load(f"{D}/{REF}{s}.npz")
    g = [np.fromfile(f"{D}/{O}/{s}_o{k}.bin", np.float32) for k in range(4)]
    lg, bx, pr, mk = g[0].reshape(200), g[1].reshape(200, 4), g[2].reshape(1), g[3].reshape(200, 288, 288)
    rl, rb, rp, rm = r["logits"].reshape(200), r["boxes"].reshape(200, 4), r["presence"].reshape(1), r["masks"].reshape(200, 288, 288)
    sc, rs = sig(lg) * sig(pr), sig(rl) * sig(rp)
    keep_r, keep_g = set(np.where(rs > 0.5)[0]), set(np.where(sc > 0.5)[0])
    ious = []
    for q in sorted(keep_r):
        a, b = mk[q] > 0, rm[q] > 0
        ious.append((a & b).sum() / max((a | b).sum(), 1))
    kr = sorted(keep_r)
    print(f"sample {s} '{r['prompt']}': kept ref {[int(q) for q in kr]} dev {[int(q) for q in sorted(keep_g)]} | kept score diff {np.abs(sc[kr] - rs[kr]).max():.1e} "
          f"kept box diff {np.abs(bx[kr] - rb[kr]).max():.1e} | all-query score maxdiff {np.abs(sc - rs).max():.1e} | "
          f"box maxdiff {np.abs(bx - rb).max():.1e} | mask logit maxdiff {np.abs(mk - rm).max():.2g} relL2 {np.linalg.norm(mk - rm) / np.linalg.norm(rm):.1e} | "
          f"kept mask IoU {', '.join(f'{v:.4f}' for v in ious)} | flipped px {sum(int(((mk[q] > 0) != (rm[q] > 0)).sum()) for q in keep_r)}")
