"""OWLv2 Step 5 references from the original model (no conversion):
(a) large vocabulary -- the original forward with all 4,585 YOLOE class names
as text queries, per photo: per-patch best label and its logit; (b) image-
exemplar queries -- three crops of the top original-model detections (distinct
24-query classes) as query images, processed like any image, and the original
image_guided_detection logits for every (exemplar, photo) pair."""
import sys, glob, os
import numpy as np
import torch
from PIL import Image
from transformers import Owlv2ForObjectDetection, Owlv2Processor
R = sys.argv[1]
REPO = "google/owlv2-base-patch16-ensemble"; REV = "cfd3195ba4ea9592eec887ded089f4c08eff231d"
model = Owlv2ForObjectDetection.from_pretrained(REPO, revision=REV).eval()
proc = Owlv2Processor.from_pretrained(REPO, revision=REV)
BP = "/Users/dev/Code/browser-perception/demos"
imgs = sorted(glob.glob(f"{BP}/object-selection/samples/*.jpg"))[:5] + sorted(glob.glob(f"{BP}/segmentation/samples/*.jpg"))[:3]
names = open(f"{R}/text/vocab_names.txt").read().splitlines()
px = [torch.from_numpy(np.fromfile(f"{R}/inputs/img{i}.bin", np.float32).reshape(1, 3, 960, 960)) for i in range(8)]

# (a) large vocabulary
t = proc.tokenizer(names, padding="max_length", max_length=16, truncation=True, return_tensors="pt")
for i in range(8):
    if os.path.exists(f"{R}/ex/large{i}.npz"): continue
    with torch.no_grad():
        lg = model(input_ids=t["input_ids"], attention_mask=t["attention_mask"], pixel_values=px[i]).logits[0].numpy()
    np.savez(f"{R}/ex/large{i}.npz", best=lg.argmax(1), best_logit=lg.max(1))
print("large-vocabulary references written", flush=True)

# (b) image exemplars: crops of the top original detections, distinct classes
cands = []
for i in range(8):
    r = np.load(f"{R}/ref{i}.npz"); s = 1 / (1 + np.exp(-r["logits"]))
    p, q = np.unravel_index(s.argmax(), s.shape); cands.append((s[p, q], i, q, r["boxes"][p]))
chosen, used = [], set()
for sc, i, q, b in sorted(cands, key=lambda c: -c[0]):
    if q not in used and len(chosen) < 3: chosen.append((i, q, b)); used.add(q)
lines = []
for j, (i, q, (cx, cy, w, h)) in enumerate(chosen):
    im = Image.open(imgs[i]).convert("RGB"); S_ = max(im.size)          # boxes are relative to the padded square
    box = [max(0, (cx - w * 0.6) * S_), max(0, (cy - h * 0.6) * S_), min(im.size[0], (cx + w * 0.6) * S_), min(im.size[1], (cy + h * 0.6) * S_)]
    crop = im.crop(box); crop.save(f"{R}/ex/exemplar{j}.jpg")
    qpx = proc(images=crop, return_tensors="pt")["pixel_values"]
    qpx.numpy().astype(np.float32).tofile(f"{R}/ex/exq{j}.bin"); lines.append(f"/data/local/tmp/owlv2/ex/exq{j}.bin,/data/local/tmp/owlv2/pos.bin")
    print(f"exemplar {j}: query class {q} from photo {i}, crop {[int(v) for v in box]}", flush=True)
    for k in range(8):
        with torch.no_grad():
            o = model.image_guided_detection(pixel_values=px[k], query_pixel_values=qpx)
        np.savez(f"{R}/ex/guided{j}_{k}.npz", logits=o.logits[0, :, 0].numpy(), boxes=o.target_pred_boxes[0].numpy())
open(f"{R}/ex/inputs.txt", "w").write("\n".join(lines) + "\n")
