"""Published DINOv2-S/14 (448x448, patch tokens) evaluation inputs: eight photos,
references from the original timm model (vit_small_patch14_dinov2.lvd142m at
448), and a desktop LiteRT CPU check of both published files."""
import sys, glob
import numpy as np
import torch, timm
from PIL import Image
from ai_edge_litert.interpreter import Interpreter
P, OUT = sys.argv[1], sys.argv[2]
BP = "/Users/dev/Code/browser-perception/demos"
imgs = sorted(glob.glob(f"{BP}/object-selection/samples/*.jpg"))[:5] + sorted(glob.glob(f"{BP}/segmentation/samples/*.jpg"))[:3]
model = timm.create_model("vit_small_patch14_dinov2.lvd142m", pretrained=True, img_size=448).eval()
print("timm", timm.__version__, "| model", model.default_cfg.get("hf_hub_id"), flush=True)
mean = np.array([0.485, 0.456, 0.406], np.float32); std = np.array([0.229, 0.224, 0.225], np.float32)
xs, refs_norm, refs_raw, lines = [], [], [], []
for i, p in enumerate(imgs):
    x = np.asarray(Image.open(p).convert("RGB").resize((448, 448), Image.BICUBIC), np.float32) / 255.0
    x = ((x - mean) / std).transpose(2, 0, 1)[None].astype(np.float32).copy()
    x.tofile(f"{OUT}/inputs/{i}.bin"); lines.append(f"/data/local/tmp/dino448/{i}.bin"); xs.append(x)
    with torch.no_grad():
        t = model.forward_features(torch.from_numpy(x))            # [1, 1025, 384], final norm applied
    refs_norm.append(t[0, 1:].numpy())
open(f"{OUT}/inputs.txt", "w").write("\n".join(lines) + "\n")
ref = np.stack(refs_norm); np.save(f"{OUT}/reference.npy", ref)
def cos(a, b): a, b = a.ravel().astype(np.float64), b.ravel().astype(np.float64); return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))
for f in ("dinov2_s_fp16.tflite", "dinov2_s_erf_fp16.tflite"):
    it = Interpreter(model_path=f"{P}/{f}"); it.allocate_tensors()
    od = it.get_output_details()[0]
    got = []
    for x in xs:
        it.set_tensor(it.get_input_details()[0]["index"], x); it.invoke(); got.append(it.get_tensor(od["index"])[0])
    got = np.stack(got)
    print(f"{f}: out {od['shape']} | desktop CPU vs timm(normed): worst-image cos {min(cos(g, r) for g, r in zip(got, ref)):.6f}, relL2 {np.linalg.norm(got - ref) / np.linalg.norm(ref):.3g}", flush=True)
