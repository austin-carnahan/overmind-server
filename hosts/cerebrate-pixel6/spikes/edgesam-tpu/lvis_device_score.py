"""Scores EdgeSAM's fast pipeline run on the Pixel (lvis_device_run.sh) on
the LVIS selection set: decoder outputs upscaled by the original
postprocess_masks, then against the ground truth (quality, beside
lvis_compare.py's desktop originals) and against the original EdgeSAM's own
single-box masks (fidelity).
usage: lvis_device_score.py <dl-edgesam dir> <selection dir> <lvis dir> <device decout root (b*/decout)>"""
import sys, json
import numpy as np, cv2, torch
from edgesam_common import load_edgesam
D, SEL, L, DEV = sys.argv[1:5]
sam, pred = load_edgesam(D, "bicubic")
man = json.load(open(f"{SEL}/manifest.json")); inst = {i["id"]: i for i in man["instances"]}
rows = json.load(open(f"{L}/lvis_rows.json")); index = json.load(open(f"{L}/dev/index.json"))
row_of = {(r["image"], r["box_index"]): r for r in rows}
q, fid = [], []
for e in index:
    r = row_of[(e["image"], e["box"])]; z = np.load(f"{L}/edgesam_in_{e['image']}.npz")
    low = torch.from_numpy(np.fromfile(f"{DEV}/b{e['batch']}/decout/{e['sample']}_o0.bin", np.float32).reshape(1, 1, 256, 256))
    with torch.no_grad():
        m = (sam.postprocess_masks(low, tuple(z["input_size"]), tuple(z["original_size"])) > 0).numpy()[0, 0]
        pred.original_size, pred.input_size, pred.features, pred.is_image_set = tuple(z["original_size"]), tuple(z["input_size"]), torch.from_numpy(z["emb"]), True
        orig = pred.predict(box=z["boxes"][e["box"]], num_multimask_outputs=1)[0][0]
    g = cv2.imread(f"{SEL}/{inst[r['id']]['mask']}", cv2.IMREAD_GRAYSCALE) > 127
    iou = lambda a, b: (a & b).sum() / max((a | b).sum(), 1)
    q.append(dict(iou=iou(m, g), coverage=(m & g).sum() / max(g.sum(), 1), spill=(m & ~g).sum() / max(m.sum(), 1), kind=r["kind"], stratum=r["stratum"],
                  orig=r["edgesam_single"]["iou"], sam21=r["sam21_single"]["iou"]))
    fid.append(iou(m, orig))
iou_d = np.array([x["iou"] for x in q]); iou_o = np.array([x["orig"] for x in q]); iou_s = np.array([x["sam21"] for x in q]); fid = np.array(fid)
print(f"{len(q)} objects")
print(f"| EdgeSAM fast on the Pixel (TPU + GPU neck, GPU fp32 decoder) | {iou_d.mean():.1%} | {np.median(iou_d):.1%} | "
      f"{np.mean([x['coverage'] < 0.5 for x in q]):.1%} | {np.mean([x['spill'] for x in q]):.1%} |   (vs ground truth: mean, median IoU, missed, spill)")
for s in ("large", "medium", "small"):
    sel = np.array([x["stratum"] == s for x in q]); print(f"stratum {s}: device {iou_d[sel].mean():.1%}, original EdgeSAM {iou_o[sel].mean():.1%}, SAM 2.1 {iou_s[sel].mean():.1%}")
d = iou_d - iou_o
print(f"vs original EdgeSAM, ground-truth IoU: mean {d.mean():+.2%}, worst {d.min():+.1%}, best {d.max():+.1%}; lower by > 2 pts on {(d < -0.02).sum()}, higher by > 2 pts on {(d > 0.02).sum()}")
print(f"fidelity (mask IoU vs original EdgeSAM's mask): worst {fid.min():.4f}, mean {fid.mean():.5f}, < 0.95: {(fid < 0.95).sum()}")
d2 = iou_d - iou_s
print(f"vs SAM 2.1 (single): mean {d2.mean():+.1%}; better by > 5 pts on {(d2 > 0.05).sum()}, worse by > 5 pts on {(d2 < -0.05).sum()}")
