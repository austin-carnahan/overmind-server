"""OWLv2 image tower on device (box logits; host adds box_bias + sigmoid) vs the original Owlv2ForObjectDetection forward,
at task level. Device outputs (boxes, objectness, class_embeds, shift, scale)
-> host logits for the 24-query vocabulary -> detections (sigmoid score >=
threshold, per-query NMS at IoU 0.3, as in OWLv2's post-processing), matched
to the reference's detections by query and box IoU; summed over 8 photos."""
import sys, glob, os
import numpy as np
R = sys.argv[1]; configs = sys.argv[2:]
TH = 0.2; P = 3600; Q = np.load(f"{R}/query_embeds.npy").reshape(-1, 512); BIAS = np.load(f"{R}/box_bias.npy").reshape(P, 4)

def logits(ce, shift, scale):
    q = Q / (np.linalg.norm(Q, axis=-1, keepdims=True) + 1e-6)
    return (ce @ q.T + shift) * scale

def iou(a, b):  # cxcywh -> pairwise IoU
    def xy(x): return np.stack([x[:, 0] - x[:, 2] / 2, x[:, 1] - x[:, 3] / 2, x[:, 0] + x[:, 2] / 2, x[:, 1] + x[:, 3] / 2], 1)
    a, b = xy(a), xy(b)
    lt = np.maximum(a[:, None, :2], b[None, :, :2]); rb = np.minimum(a[:, None, 2:], b[None, :, 2:])
    inter = np.clip(rb - lt, 0, None).prod(-1)
    area = lambda x: (x[:, 2] - x[:, 0]) * (x[:, 3] - x[:, 1])
    return inter / (area(a)[:, None] + area(b)[None, :] - inter + 1e-9)

def detections(lg, boxes):
    s = 1 / (1 + np.exp(-lg)); out = []
    for q in range(lg.shape[1]):
        idx = np.where(s[:, q] >= TH)[0]; idx = idx[np.argsort(-s[idx, q])]; keep = []
        while len(idx):
            keep.append(idx[0]); idx = idx[1:][iou(boxes[idx[:1]], boxes[idx[1:]])[0] < 0.3] if len(idx) > 1 else []
        out += [(q, k, s[k, q]) for k in keep]
    return out

print(f"{'config':12} {'logit maxdiff':>13} {'ref dets':>8} {'got':>4} {'matched':>7} {'box IoU min':>11} {'score maxdiff':>13} {'top-1/query same':>16} {'obj top-100 overlap':>19}")
for c in configs:
    lmax = 0; ref_n = got_n = matched = 0; bmin, smax = [], []; top1 = top1n = 0; ov = []
    for i in range(8):
        r = np.load(f"{R}/ref{i}.npz")
        o = [np.fromfile(f"{R}/out-{c}/{i}_o{k}.bin", np.float32) for k in range(5)]
        boxes, obj, ce, shift, scale = 1 / (1 + np.exp(-(o[0].reshape(P, 4) + BIAS))), o[1].reshape(P), o[2].reshape(P, 512), o[3].reshape(P, 1), o[4].reshape(P, 1)
        lg = logits(ce, shift, scale); rl = r["logits"].reshape(P, -1); rb = r["boxes"].reshape(P, 4)
        lmax = max(lmax, np.abs(lg - rl).max())
        top1 += (lg.argmax(0) == rl.argmax(0)).sum(); top1n += lg.shape[1]
        ov.append(len(set(np.argsort(-obj)[:100]) & set(np.argsort(-r["objectness"].reshape(P))[:100])) / 100)
        rd, gd = detections(rl, rb), detections(lg, boxes); ref_n += len(rd); got_n += len(gd)
        for q, k, s in rd:
            cand = [(kk, ss) for qq, kk, ss in gd if qq == q]
            if not cand: continue
            ious = iou(rb[[k]], boxes[[kk for kk, _ in cand]])[0]; j = ious.argmax()
            if ious[j] >= 0.5: matched += 1; bmin.append(ious[j]); smax.append(abs(cand[j][1] - s))
    print(f"{c:12} {lmax:13.4g} {ref_n:>8} {got_n:>4} {matched:>7} {min(bmin) if bmin else float('nan'):11.4f} {max(smax) if smax else float('nan'):13.4f} {top1:>9}/{top1n:<6} {np.mean(ov):19.3f}")
