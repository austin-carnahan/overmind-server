"""SAM decoder outputs vs the unmodified PyTorch reference: logit errors plus
task-level mask agreement (binary IoU at logit > 0, boundary-pixel agreement,
and whether the best mask by predicted IoU is the same)."""
import sys
import numpy as np
D = sys.argv[1]; configs = sys.argv[2:]
ref = np.load(f"{D}/ref_masks.npy").astype(np.float64); ref_iou = np.load(f"{D}/ref_iou.npy")
n = len(ref)
def edges(b):
    e = np.zeros_like(b)
    e[:, 1:] |= b[:, 1:] != b[:, :-1]; e[1:, :] |= b[1:, :] != b[:-1, :]
    return e
print(f"{'config':12} {'max abs':>8} {'rel L2':>8} {'mask IoU min':>12} {'mean':>7} {'boundary agree':>14} {'pixels flipped':>14} {'best-mask same':>14} {'score maxdiff':>13}")
for c in configs:
    got = np.stack([np.fromfile(f"{D}/pulled/out-{c}/{i}_o0.bin", np.float32).reshape(3, 256, 256) for i in range(n)]).astype(np.float64)
    gi = np.stack([np.fromfile(f"{D}/pulled/out-{c}/{i}_o1.bin", np.float32).reshape(3) for i in range(n)])
    d = np.abs(got - ref); rel = np.linalg.norm(got - ref) / np.linalg.norm(ref)
    ious, bnd, flips = [], [], 0
    for i in range(n):
        for k in range(3):
            a, b = got[i, k] > 0, ref[i, k] > 0
            u = (a | b).sum(); ious.append((a & b).sum() / u if u else 1.0)
            ea, eb = edges(a), edges(b)
            bnd.append((ea & eb).sum() / max(1, (ea | eb).sum()))
            flips += int((a != b).sum())
    same = sum(int(gi[i].argmax() == ref_iou[i].argmax()) for i in range(n))
    print(f"{c:12} {d.max():8.3g} {rel:8.3g} {min(ious):12.5f} {np.mean(ious):7.5f} {np.mean(bnd):14.4f} {flips:>14} {same:>11}/{n} {np.abs(gi - ref_iou).max():13.3g}")
