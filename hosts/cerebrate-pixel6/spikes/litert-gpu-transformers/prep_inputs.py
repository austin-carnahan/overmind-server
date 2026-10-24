"""Eight different real photos -> DINOv2 inputs (224x224, ImageNet norm, NCHW
float32 .bin) and reference outputs from the *unmodified* PyTorch model."""
import sys, glob, os
import numpy as np
import torch
from PIL import Image
from transformers import AutoModel

OUT = sys.argv[1]
BP = "/Users/dev/Code/browser-perception/demos"
imgs = sorted(glob.glob(f"{BP}/object-selection/samples/*.jpg"))[:5] + sorted(glob.glob(f"{BP}/segmentation/samples/*.jpg"))[:3]
model = AutoModel.from_pretrained("facebook/dinov2-small", revision="ed25f3a31f01632728cabb09d1542f84ab7b0056").eval()
mean = np.array([0.485, 0.456, 0.406], np.float32); std = np.array([0.229, 0.224, 0.225], np.float32)
refs = []
with open(f"{OUT}/inputs.txt", "w") as lst:
    for i, path in enumerate(imgs):
        x = np.asarray(Image.open(path).convert("RGB").resize((224, 224), Image.BICUBIC), np.float32) / 255.0
        x = ((x - mean) / std).transpose(2, 0, 1)[None].copy()
        x.tofile(f"{OUT}/inputs/{i}.bin")
        lst.write(f"/data/local/tmp/e2e/{i}.bin\n")
        with torch.no_grad():
            refs.append(model(pixel_values=torch.from_numpy(x)).last_hidden_state.numpy()[0])
        print(i, os.path.basename(path))
np.save(f"{OUT}/reference.npy", np.stack(refs))
print("reference", np.stack(refs).shape)
