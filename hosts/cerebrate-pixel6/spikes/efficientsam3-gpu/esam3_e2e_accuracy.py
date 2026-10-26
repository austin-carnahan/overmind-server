"""Phone-native chain (vision GPU -> text CPU -> grounding GPU, each stage fed
the phone's own outputs) vs the original model on the desktop CPU, for the 11
validation samples. Two levels: (a) raw -- kept set (score > 0.5), kept score
and box differences, mask IoU at 288x288; (b) final -- Sam3Processor's own
post-processing (bilinear upsample to the photo, sigmoid > 0.5) applied to the
device outputs, compared with the same post-processing of the original's raw
outputs; and that host post-processing checked against the processor's saved
masks from the baseline run (10 samples; 'puppy' was not in that run).
usage: <dev dir> <ref dir (baseline photo*.npz)> <out subdir>"""
import sys
import numpy as np, torch
import torch.nn.functional as F
D, REFD, O = sys.argv[1:4]
PROMPTS = ["bed", "pillow", "lamp", "wall sconce", "suitcase", "backpack", "handbag", "towel", "chair", "sofa", "table", "curtain", "window",
           "picture frame", "mirror", "television", "person", "dog", "potted plant", "rug", "laptop", "blanket", "door", "cabinet", "puppy"]
REFS = [f"gref{s}" for s in range(3)] + [f"wref{j}" for j in range(8)]
sig = lambda x: 1 / (1 + np.exp(-x))

def final(logits, presence, masks, hw):
    keep = np.where(sig(logits) * sig(presence) > 0.5)[0]
    m = F.interpolate(torch.from_numpy(masks[keep][:, None]), hw, mode="bilinear", align_corners=False).sigmoid().numpy()[:, 0] > 0.5
    return keep, m

tot = dict(det=0, matched=0, flipped=0, px=0); worst_iou = 1.0; worst_final = 1.0; proc_check = []
for n, rn in enumerate(REFS):
    r = np.load(f"{D}/{rn}.npz"); i, q = int(r["photo"]), str(r["prompt"])
    base = np.load(f"{REFD}/photo{i}.npz"); hw = tuple(int(v) for v in base["shape"])
    g = [np.fromfile(f"{D}/{O}/{n}_o{k}.bin", np.float32) for k in range(4)]
    lg, bx, pr, mk = g[0].reshape(200), g[1].reshape(200, 4), g[2].reshape(1), g[3].reshape(200, 288, 288)
    rl, rb, rp, rm = r["logits"].reshape(200), r["boxes"].reshape(200, 4), r["presence"].reshape(1), r["masks"].reshape(200, 288, 288)
    sc, rs = sig(lg) * sig(pr), sig(rl) * sig(rp)
    kr, kg = np.where(rs > 0.5)[0], np.where(sc > 0.5)[0]
    same = np.array_equal(kr, kg); tot["det"] += len(kr); tot["matched"] += len(set(kr) & set(kg))
    ious = [((mk[k] > 0) & (rm[k] > 0)).sum() / max(((mk[k] > 0) | (rm[k] > 0)).sum(), 1) for k in kr]
    worst_iou = min([worst_iou] + ious)
    # final level
    _, fm_g = final(lg, pr, mk, hw); _, fm_r = final(rl, rp, rm, hw)
    fl = int((fm_g != fm_r).sum()) if same else -1; tot["flipped"] += max(fl, 0); tot["px"] += fm_r.size
    fi = [(a & b).sum() / max((a | b).sum(), 1) for a, b in zip(fm_g, fm_r)] if same else [0.0]
    worst_final = min([worst_final] + fi)
    if q != "puppy":   # host post-processing == processor's saved masks?
        k = PROMPTS.index(q); pm = np.unpackbits(base[f"{k}_masks"], axis=-1)[..., :hw[1]].astype(bool)
        proc_check.append(pm.shape == fm_r.shape and bool((pm == fm_r).all()))
    print(f"{n:2} photo {i} '{q}': kept {[int(v) for v in kr]} {'same' if same else 'DIFFERENT ' + str([int(v) for v in kg])} | "
          f"min score {rs[kr].min() if len(kr) else float('nan'):.3f} | kept score diff {np.abs(sc[kr] - rs[kr]).max():.1e} box diff {np.abs(bx[kr] - rb[kr]).max():.1e} | "
          f"mask IoU@288 {min(ious):.4f} | final {hw[0]}x{hw[1]}: IoU {min(fi):.4f}, flipped px {fl}")
print(f"TOTAL: detections {tot['matched']}/{tot['det']} retained; worst mask IoU@288 {worst_iou:.4f}; worst final-mask IoU {worst_final:.4f}; "
      f"final flipped px {tot['flipped']} of {tot['px']}; host post-processing == processor's saved masks: {sum(proc_check)}/{len(proc_check)}")
