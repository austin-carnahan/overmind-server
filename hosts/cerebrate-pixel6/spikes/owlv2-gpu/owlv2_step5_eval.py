"""OWLv2 Step 5 task checks on Pixel GPU outputs (FP32 image tower; host adds
box_bias + sigmoid and computes logits):
(a) large vocabulary -- 4,585 text embeddings against each photo's patches:
per-patch best label vs the original forward with the same vocabulary;
(b) image exemplars -- transformers' embed_image_query reproduced on the host
from the exemplar's tower outputs (OWLv2 rule: the query is the class
embedding of the exemplar's highest-objectness box), then logits on every
photo, vs the
original image_guided_detection: detections (score >= 0.9, NMS 0.3, as in the
transformers example) matched by box IoU."""
import sys, time
import numpy as np
R = sys.argv[1]; P = 3600; OUT = f"{R}/out-gpu-fp32"
BIAS = np.load(f"{R}/box_bias.npy").reshape(P, 4)
V = np.load(f"{R}/text/vocab_embeds.npy"); names = open(f"{R}/text/vocab_names.txt").read().splitlines()
sig = lambda x: 1 / (1 + np.exp(-x))

def tower(d, i):
    o = [np.fromfile(f"{d}/{i}_o{k}.bin", np.float32) for k in range(5)]
    return sig(o[0].reshape(P, 4) + BIAS), o[1], o[2].reshape(P, 512), o[3].reshape(P, 1), o[4].reshape(P, 1)

def logits(ce, shift, scale, q):
    q = q / (np.linalg.norm(q, axis=-1, keepdims=True) + 1e-6)
    return (ce @ q.T + shift) * scale

def corners(b): return np.stack([b[:, 0] - b[:, 2] / 2, b[:, 1] - b[:, 3] / 2, b[:, 0] + b[:, 2] / 2, b[:, 1] + b[:, 3] / 2], 1)

def iou(a, b):
    a, b = corners(a), corners(b)
    lt = np.maximum(a[:, None, :2], b[None, :, :2]); rb = np.minimum(a[:, None, 2:], b[None, :, 2:])
    inter = np.clip(rb - lt, 0, None).prod(-1); area = lambda x: (x[:, 2] - x[:, 0]) * (x[:, 3] - x[:, 1])
    return inter / (area(a)[:, None] + area(b)[None, :] - inter + 1e-9)

def nms(s, boxes, th):
    idx = np.where(s >= th)[0]; idx = idx[np.argsort(-s[idx])]; keep = []
    while len(idx):
        keep.append(idx[0]); idx = idx[1:][iou(boxes[idx[:1]], boxes[idx[1:]])[0] < 0.3] if len(idx) > 1 else []
    return keep

# (a) large vocabulary
agree = cand = 0; lmax = 0; t_host = []
for i in range(8):
    boxes, obj, ce, shift, scale = tower(OUT, i); r = np.load(f"{R}/ex/large{i}.npz")
    t0 = time.perf_counter(); lg = logits(ce, shift, scale, V); t_host.append(time.perf_counter() - t0)
    best, bl = lg.argmax(1), lg.max(1)
    m = sig(r["best_logit"]) >= 0.2; cand += m.sum(); agree += (best[m] == r["best"][m]).sum()
    lmax = max(lmax, np.abs(bl - r["best_logit"]).max())
    if i < 3:
        top = nms(sig(bl), boxes, 0.2)[:5]
        print(f"  photo {i} top labels (device): " + ", ".join(f"{names[best[k]]} {sig(bl[k]):.2f}" for k in top))
print(f"(a) 4,585-name vocabulary: best-logit max diff {lmax:.4g}; patches scoring >= 0.2 in the original: {cand}, "
      f"same best label on device: {agree}/{cand}; host logits on this Mac {1000 * np.median(t_host):.0f} ms per photo")

# (b) image exemplars
print(f"(b) {'exemplar':>8} {'logit maxdiff':>13} {'ref dets':>8} {'got':>4} {'matched':>7} {'box IoU min':>11} {'score maxdiff':>13}")
for j in range(3):
    _, qobj, qce, _, _ = tower(f"{R}/ex/out", j)
    q = qce[qobj.argmax()][None]
    lm = 0; rn = gn = mt = 0; bmin, smax = [], []
    for k in range(8):
        boxes, _, ce, shift, scale = tower(OUT, k); r = np.load(f"{R}/ex/guided{j}_{k}.npz")
        lg = logits(ce, shift, scale, q)[:, 0]; lm = max(lm, np.abs(lg - r["logits"]).max())
        rd, gd = nms(sig(r["logits"]), r["boxes"], 0.9), nms(sig(lg), boxes, 0.9); rn += len(rd); gn += len(gd)
        for p in rd:
            if not gd: continue
            v = iou(r["boxes"][[p]], boxes[gd])[0]; a = v.argmax()
            if v[a] >= 0.5: mt += 1; bmin.append(v[a]); smax.append(abs(sig(lg[gd[a]]) - sig(r["logits"][p])))
    print(f"    {j:>8} {lm:13.4g} {rn:>8} {gn:>4} {mt:>7} {min(bmin) if bmin else float('nan'):11.4f} {max(smax) if smax else float('nan'):13.4f}")
