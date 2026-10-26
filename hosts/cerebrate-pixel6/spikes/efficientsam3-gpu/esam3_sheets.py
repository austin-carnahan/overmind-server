"""Review sheets from the reference run: one sheet per photo, one panel per
prompt that found something (masks + score), so overlapping labels stay
readable."""
import sys, glob
import numpy as np
from PIL import Image, ImageDraw
OUT = sys.argv[1]
PROMPTS = ["bed", "pillow", "lamp", "wall sconce", "suitcase", "backpack", "handbag", "towel", "chair", "sofa",
           "table", "curtain", "window", "picture frame", "mirror", "television", "person", "dog", "potted plant",
           "rug", "laptop", "blanket", "door", "cabinet"]
BP = "/Users/dev/Code/browser-perception/demos"
imgs = sorted(glob.glob(f"{BP}/object-selection/samples/*.jpg"))[:5] + sorted(glob.glob(f"{BP}/segmentation/samples/*.jpg"))[:3]
COLS, PW = 4, 300
for i, p in enumerate(imgs):
    im = Image.open(p).convert("RGB"); r = np.load(f"{OUT}/ref/photo{i}.npz"); h, w = r["shape"]
    hits = [k for k in range(len(PROMPTS)) if len(r[f"{k}_scores"])]
    ph = int(PW * h / w); rows = max(1, -(-len(hits) // COLS))
    sheet = Image.new("RGB", (COLS * PW, rows * (ph + 18)), (24, 24, 24)); d = ImageDraw.Draw(sheet)
    for n, k in enumerate(hits):
        masks = np.unpackbits(r[f"{k}_masks"], axis=-1)[..., :w].astype(bool)
        pan = np.asarray(im).astype(np.float32) * 0.45
        for m, c in zip(masks, [(255, 80, 80), (80, 200, 255), (120, 255, 120), (255, 220, 60), (220, 120, 255)] * 4):
            pan[m] = np.asarray(im)[m] * 0.4 + np.array(c) * 0.6
        x, y = (n % COLS) * PW, (n // COLS) * (ph + 18)
        sheet.paste(Image.fromarray(pan.astype(np.uint8)).resize((PW, ph)), (x, y + 18))
        d.text((x + 4, y + 3), f"{PROMPTS[k]}: " + ", ".join(f"{s:.2f}" for s in r[f"{k}_scores"]), fill=(240, 240, 240))
    sheet.save(f"{OUT}/overlays/sheet{i}.jpg", quality=88)
    print(f"sheet{i}: {len(hits)} prompts")
