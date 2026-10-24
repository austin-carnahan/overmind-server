"""Segmentation quality against ground truth: EdgeSAM-3x vs SAM 2.1
Hiera-Tiny on browser-perception's object-selection set (126 LVIS objects in
118 photos, 18 indoor kinds incl. people; exact masks), box prompts = each
object's ground-truth bounding box (as browser-perception's box prompt,
margin 0). Original models in fp32 on the desktop -- the Pixel's default
configurations reproduce them exactly (gpu-fp32 encoders and decoders), so
these numbers are also the device defaults' quality. Two mask choices per
model: its single box mask (EdgeSAM's official box mode,
num_multimask_outputs=1; SAM 2.1 multimask_output=False) and the
best-scoring of its three multimask outputs (browser-perception's "best").
Per object: IoU, coverage (share of the object inside the mask), spill
(share of the mask outside the object); missed = coverage < 50%.
Also writes EdgeSAM encoder inputs (NHWC) and box prompts for the device run.
usage: lvis_compare.py <dl-edgesam dir> <selection dir> <out dir>"""
import sys, os, json
import numpy as np, cv2, torch
from transformers import Sam2Model, Sam2Processor
from edgesam_common import load_edgesam, encoder_input

D, SEL, OUT = sys.argv[1:4]
os.makedirs(OUT, exist_ok=True)
man = json.load(open(f"{SEL}/manifest.json"))
images = {im["id"]: im for im in man["images"]}
by_image = {}
for inst in man["instances"]:
    by_image.setdefault(inst["image"], []).append(inst)

sam, pred = load_edgesam(D, "bicubic")
REV = "de431c4043854a71d8101e17995dfe596bf101a5"   # as sam21-gpu
s2 = Sam2Model.from_pretrained("facebook/sam2.1-hiera-tiny", revision=REV).eval()
s2p = Sam2Processor.from_pretrained("facebook/sam2.1-hiera-tiny", revision=REV)


def stats(m, g):
    inter = (m & g).sum(); union = (m | g).sum()
    return dict(iou=inter / max(union, 1), coverage=inter / max(g.sum(), 1), spill=(m & ~g).sum() / max(m.sum(), 1))


rows = []
for n, (img_id, insts) in enumerate(by_image.items()):
    im = images[img_id]
    rgb = cv2.cvtColor(cv2.imread(f"{SEL}/{im['file']}"), cv2.COLOR_BGR2RGB); H, W = rgb.shape[:2]
    boxes = np.array([[b["x"] * W, b["y"] * H, (b["x"] + b["width"]) * W, (b["y"] + b["height"]) * H]
                      for b in (i["box"] for i in insts)], np.float32)
    # EdgeSAM (original, bicubic)
    x, input_size = encoder_input(pred, rgb)
    with torch.no_grad():
        emb = sam.image_encoder(x)
    pred.original_size, pred.input_size, pred.features, pred.is_image_set = (H, W), input_size, emb, True
    np.savez(f"{OUT}/edgesam_in_{n}.npz", image_nhwc=np.ascontiguousarray(x.numpy().transpose(0, 2, 3, 1)), boxes=boxes,
             input_size=np.array(input_size), original_size=np.array((H, W)), emb=emb.numpy())
    # SAM 2.1 (original)
    with torch.no_grad():
        s2_inputs = s2p(images=rgb, input_boxes=[boxes.tolist()], return_tensors="pt")
        s2_emb = s2.get_image_embeddings(s2_inputs["pixel_values"])
    for k, inst in enumerate(insts):
        g = cv2.imread(f"{SEL}/{inst['mask']}", cv2.IMREAD_GRAYSCALE) > 127
        row = dict(id=inst["id"], kind=inst["kind"], stratum=inst["stratum"], image=n, box_index=k)
        m1, _, _ = pred.predict(box=boxes[k], num_multimask_outputs=1)
        m3, s3, _ = pred.predict(box=boxes[k], num_multimask_outputs=3)
        row["edgesam_single"] = stats(m1[0], g); row["edgesam_best3"] = stats(m3[int(np.argmax(s3))], g)
        with torch.no_grad():
            for mode, multi in (("single", False), ("best3", True)):
                out = s2(image_embeddings=s2_emb, input_boxes=s2_inputs["input_boxes"][:, k:k + 1], multimask_output=multi)
                masks = s2p.post_process_masks(out.pred_masks, s2_inputs["original_sizes"])[0][0].numpy()
                sc = out.iou_scores[0, 0].numpy()
                row[f"sam21_{mode}"] = stats(masks[int(np.argmax(sc))] if multi else masks[0], g)
        rows.append(row)
    if n % 20 == 0: print(f"  {n + 1}/{len(by_image)} photos", flush=True)
json.dump(rows, open(f"{OUT}/lvis_rows.json", "w"), indent=0, default=float)

configs = ["sam21_single", "sam21_best3", "edgesam_single", "edgesam_best3"]
def summ(cfg, sel=lambda r: True):
    v = [r[cfg] for r in rows if sel(r)]
    iou = np.array([x["iou"] for x in v])
    return dict(n=len(v), mean=iou.mean(), median=np.median(iou), missed=np.mean([x["coverage"] < 0.5 for x in v]), spill=np.mean([x["spill"] for x in v]))
print(f"\n{len(rows)} objects, ground-truth box prompts")
print("| Model / mask | Mean IoU | Median IoU | Missed | Mean spill |\n| --- | --- | --- | --- | --- |")
for c in configs:
    s = summ(c); print(f"| {c} | {s['mean']:.1%} | {s['median']:.1%} | {s['missed']:.1%} | {s['spill']:.1%} |")
for stratum in sorted({r["stratum"] for r in rows}):
    print(f"stratum {stratum}: " + ", ".join(f"{c} {summ(c, lambda r: r['stratum'] == stratum)['mean']:.1%}" for c in configs) +
          f" (n={summ(configs[0], lambda r: r['stratum'] == stratum)['n']})")
print("\nper kind (mean IoU): " + "; ".join(f"{k}: " + "/".join(f"{summ(c, lambda r: r['kind'] == k)['mean']:.0%}" for c in configs)
                                         for k in sorted({r['kind'] for r in rows})))
for a, b in (("edgesam_single", "sam21_single"), ("edgesam_best3", "sam21_best3"), ("edgesam_single", "sam21_best3")):
    d = np.array([r[a]["iou"] - r[b]["iou"] for r in rows])
    print(f"paired {a} - {b}: mean {d.mean():+.1%}; {a} better by > 5 pts on {(d > 0.05).sum()}, worse by > 5 pts on {(d < -0.05).sum()}, "
          f"worst {d.min():+.1%} ({rows[int(d.argmin())]['kind']}), best {d.max():+.1%} ({rows[int(d.argmax())]['kind']})")
