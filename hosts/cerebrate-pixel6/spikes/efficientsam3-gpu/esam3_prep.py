"""Device inputs + desktop references for the three EfficientSAM3 graphs.
vision: eight photos as [1,3,1008,1008]; text: token ids for the 24 prompts
(+ 'puppy'); grounding: three (photo, prompt) samples fed with the desktop
FPN features, the constant positional encoding, text features and padding
mask; references from the eager wrappers (identical to the original path,
stage 1)."""
import sys, glob, importlib.util
import numpy as np, torch
from PIL import Image
from torchvision.transforms import v2
REPO, CKPT, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
sys.argv = [sys.argv[0], REPO, CKPT, f"{OUT}/../conv", "none"]
spec = importlib.util.spec_from_file_location("conv", sys.path[0] + "/esam3_convert.py"); conv = importlib.util.module_from_spec(spec); spec.loader.exec_module(conv)
D = "/data/local/tmp/esam3"
BP = "/Users/dev/Code/browser-perception/demos"
imgs = sorted(glob.glob(f"{BP}/object-selection/samples/*.jpg"))[:5] + sorted(glob.glob(f"{BP}/segmentation/samples/*.jpg"))[:3]
PROMPTS = ["bed", "pillow", "lamp", "wall sconce", "suitcase", "backpack", "handbag", "towel", "chair", "sofa", "table", "curtain", "window",
           "picture frame", "mirror", "television", "person", "dog", "potted plant", "rug", "laptop", "blanket", "door", "cabinet", "puppy"]
V, T, G = conv.V, conv.T, conv.G
pos = conv.pos; pos.numpy().tofile(f"{OUT}/pos.bin")
vl, tl, gl, fpn = [], [], [], {}
for i, p in enumerate(imgs):
    px = conv.proc.transform(v2.functional.to_image(Image.open(p).convert("RGB"))).unsqueeze(0)
    px.numpy().tofile(f"{OUT}/px{i}.bin"); vl.append(f"{D}/px{i}.bin")
    f = V(px); fpn[i] = f
    np.savez(f"{OUT}/vref{i}.npz", *[x.numpy() for x in f])
for k, q in enumerate(PROMPTS):
    ids = conv.ids_of(q); ids.numpy().tofile(f"{OUT}/ids{k}.bin"); tl.append(f"{D}/ids{k}.bin")
    np.save(f"{OUT}/tref{k}.npy", T(ids).numpy()); np.save(f"{OUT}/pad{k}.npy", (ids == 0).float().numpy())
for s, (i, q) in enumerate([(0, "laptop"), (3, "bed"), (5, "puppy")]):
    k = PROMPTS.index(q); ids = conv.ids_of(q); txt = T(ids); pad = (ids == 0).float()
    for j, x in enumerate(fpn[i]): x.numpy().tofile(f"{OUT}/g{s}_f{j}.bin")
    txt.numpy().tofile(f"{OUT}/g{s}_txt.bin"); pad.numpy().tofile(f"{OUT}/g{s}_pad.bin")
    gl.append(",".join([f"{D}/g{s}_f0.bin", f"{D}/g{s}_f1.bin", f"{D}/g{s}_f2.bin", f"{D}/pos.bin", f"{D}/g{s}_txt.bin", f"{D}/g{s}_pad.bin"]))
    o = G(*fpn[i], pos, txt, pad)
    np.savez(f"{OUT}/gref{s}.npz", logits=o[0].numpy(), boxes=o[1].numpy(), presence=o[2].numpy(), masks=o[3].numpy(), photo=i, prompt=q)
    print(f"grounding sample {s}: photo {i} '{q}': presence {torch.sigmoid(o[2]).item():.3f}, top score {(torch.sigmoid(o[0]) * torch.sigmoid(o[2])).max().item():.3f}", flush=True)
open(f"{OUT}/vision.txt", "w").write("\n".join(vl) + "\n"); open(f"{OUT}/text.txt", "w").write("\n".join(tl) + "\n"); open(f"{OUT}/grounding.txt", "w").write("\n".join(gl) + "\n")
