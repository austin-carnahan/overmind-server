"""Wider grounding validation set: one (photo, prompt) per photo, chosen from
prompts the original found something for (several multi-instance), as device
inputs (FPN levels shared per photo, text features, padding mask) with
references from the unmodified model path (esam3_convert.py wrappers)."""
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
SAMPLES = [(0, "backpack"), (1, "person"), (2, "door"), (3, "pillow"), (4, "curtain"), (5, "person"), (6, "person"), (7, "laptop")]
tail = ",".join(f"{D}/{n}.bin" for n in ("ref0", "geo0", "query0", "presence0"))
lines = []
for j, (i, q) in enumerate(SAMPLES):
    px = conv.proc.transform(v2.functional.to_image(Image.open(imgs[i]).convert("RGB"))).unsqueeze(0)
    f = conv.V(px)
    for k, x in enumerate(f): x.numpy().tofile(f"{OUT}/p{i}_f{k}.bin")
    ids = conv.ids_of(q); txt = conv.T(ids); pad = (ids == 0).float()
    txt.numpy().tofile(f"{OUT}/w{j}_txt.bin"); pad.numpy().tofile(f"{OUT}/w{j}_pad.bin")
    o = conv.G(*f, conv.pos, txt, pad)
    np.savez(f"{OUT}/wref{j}.npz", logits=o[0].numpy(), boxes=o[1].numpy(), presence=o[2].numpy(), masks=o[3].numpy(), photo=i, prompt=q)
    lines.append(",".join([f"{D}/p{i}_f0.bin", f"{D}/p{i}_f1.bin", f"{D}/p{i}_f2.bin", f"{D}/pos.bin", f"{D}/w{j}_txt.bin", f"{D}/w{j}_pad.bin", tail]))
    s = torch.sigmoid(o[0]).squeeze() * torch.sigmoid(o[2]).squeeze()
    print(f"w{j}: photo {i} '{q}': {(s > 0.5).sum().item()} kept, scores {[round(v, 3) for v in sorted(s[s > 0.3].tolist(), reverse=True)]}", flush=True)
open(f"{OUT}/wide.txt", "w").write("\n".join(lines) + "\n")
