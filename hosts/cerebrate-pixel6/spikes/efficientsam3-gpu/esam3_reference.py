"""EfficientSAM3 (fine-tuned full model, RepViT-M1.1 + MobileCLIP-S0, ctx 16)
original checkpoint on the desktop CPU: text-prompted masks for the eight
lane photos and 24 household prompts. Writes per-photo references (scores,
boxes, masks) and mask overlays for review, plus timings."""
import sys, glob, time, colorsys
import numpy as np
import torch
from PIL import Image, ImageDraw
REPO, CKPT, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, f"{REPO}/sam3")
from sam3.model_builder import build_efficientsam3_image_model
from sam3.model.sam3_image_processor import Sam3Processor
torch.manual_seed(0)
PROMPTS = ["bed", "pillow", "lamp", "wall sconce", "suitcase", "backpack", "handbag", "towel", "chair", "sofa",
           "table", "curtain", "window", "picture frame", "mirror", "television", "person", "dog", "potted plant",
           "rug", "laptop", "blanket", "door", "cabinet"]
BP = "/Users/dev/Code/browser-perception/demos"
imgs = sorted(glob.glob(f"{BP}/object-selection/samples/*.jpg"))[:5] + sorted(glob.glob(f"{BP}/segmentation/samples/*.jpg"))[:3]
t0 = time.perf_counter()
model = build_efficientsam3_image_model(checkpoint_path=CKPT, backbone_type="repvit", model_name="m1.1",
                                        text_encoder_type="MobileCLIP-S0", text_encoder_context_length=16,
                                        device="cpu", load_from_HF=False)
print(f"built in {time.perf_counter() - t0:.1f} s; params {sum(p.numel() for p in model.parameters()) / 1e6:.1f}M", flush=True)
proc = Sam3Processor(model, device="cpu", confidence_threshold=0.5)
t_img, t_txt = [], []
for i, p in enumerate(imgs):
    im = Image.open(p).convert("RGB")
    t = time.perf_counter(); state = proc.set_image(im); t_img.append(time.perf_counter() - t)
    rec, ov = {}, im.copy().convert("RGBA")
    layer = Image.new("RGBA", im.size, (0, 0, 0, 0)); d = ImageDraw.Draw(layer); labels = []
    for k, q in enumerate(PROMPTS):
        t = time.perf_counter(); state = proc.set_text_prompt(q, state); t_txt.append(time.perf_counter() - t)
        m = state["masks"].squeeze(1).cpu().numpy().astype(bool); s = state["scores"].cpu().numpy(); b = state["boxes"].cpu().numpy()
        rec[f"{k}_scores"], rec[f"{k}_boxes"], rec[f"{k}_masks"] = s, b, np.packbits(m, axis=-1)
        r, g, bl = [int(255 * c) for c in colorsys.hsv_to_rgb(k / len(PROMPTS), 0.85, 1.0)]
        for mm, ss, bb in zip(m, s, b):
            layer.paste(Image.new("RGBA", im.size, (r, g, bl, 110)), (0, 0), Image.fromarray(mm.astype(np.uint8) * 255))
            d.rectangle([float(v) for v in bb], outline=(r, g, bl, 255), width=2)
            labels.append(((float(bb[0]) + 3, float(bb[1]) + 2), f"{q} {ss:.2f}", (r, g, bl)))
    for xy, txt, col in labels:
        tw = d.textlength(txt); d.rectangle([xy[0] - 2, xy[1] - 1, xy[0] + tw + 2, xy[1] + 11], fill=(0, 0, 0, 170)); d.text(xy, txt, fill=col + (255,))
    Image.alpha_composite(ov, layer).convert("RGB").save(f"{OUT}/overlays/photo{i}.jpg", quality=90)
    np.savez_compressed(f"{OUT}/ref/photo{i}.npz", shape=np.array(im.size[::-1]), **rec)
    found = [f"{PROMPTS[k]}×{len(rec[f'{k}_scores'])}" for k in range(len(PROMPTS)) if len(rec[f"{k}_scores"])]
    print(f"photo {i} {im.size}: {', '.join(found) or 'nothing'}", flush=True)
print(f"CPU: image encode median {np.median(t_img):.2f} s; per text prompt (text encoder + transformer + heads) median {np.median(t_txt):.2f} s")
