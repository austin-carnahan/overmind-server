"""Depth Anything V2 Small evaluation: eight photos stretched to 518x686
(the published fixed shape), references from the original Transformers
checkpoint, and a desktop LiteRT CPU check of both published files."""
import sys, glob
import numpy as np
import torch
from PIL import Image
from transformers import AutoModelForDepthEstimation
from ai_edge_litert.interpreter import Interpreter
P, OUT = sys.argv[1], sys.argv[2]
REPO, REV = "depth-anything/Depth-Anything-V2-Small-hf", "5426e4f0f36572d16453bbda7a8389317b1bef99"
model = AutoModelForDepthEstimation.from_pretrained(REPO, revision=REV).eval()
BP = "/Users/dev/Code/browser-perception/demos"
imgs = sorted(glob.glob(f"{BP}/object-selection/samples/*.jpg"))[:5] + sorted(glob.glob(f"{BP}/segmentation/samples/*.jpg"))[:3]
mean = np.array([0.485, 0.456, 0.406], np.float32); std = np.array([0.229, 0.224, 0.225], np.float32)
xs, refs, lines = [], [], []
for i, p in enumerate(imgs):
    x = np.asarray(Image.open(p).convert("RGB").resize((686, 518), Image.BICUBIC), np.float32) / 255.0
    x = ((x - mean) / std).transpose(2, 0, 1)[None].astype(np.float32).copy()
    x.tofile(f"{OUT}/inputs/{i}.bin"); lines.append(f"/data/local/tmp/depth/{i}.bin"); xs.append(x)
    with torch.no_grad():
        refs.append(model(pixel_values=torch.from_numpy(x)).predicted_depth[0].numpy())
open(f"{OUT}/inputs.txt", "w").write("\n".join(lines) + "\n")
ref = np.stack(refs); np.save(f"{OUT}/reference.npy", ref); print("reference", ref.shape, flush=True)
for f in ("depth_anything_v2_small.tflite", "depth_anything_v2_small_wi8_afp32.tflite"):
    it = Interpreter(model_path=f"{P}/{f}"); it.allocate_tensors(); got = []
    for x in xs:
        it.set_tensor(it.get_input_details()[0]["index"], x); it.invoke(); got.append(it.get_tensor(it.get_output_details()[0]["index"])[0])
    got = np.stack(got)
    print(f"{f}: desktop CPU vs original: rel L2 {np.linalg.norm(got - ref) / np.linalg.norm(ref):.3g}, max abs {np.abs(got - ref).max():.3g}", flush=True)
