"""SAM 2.1 decoder test set: 4 photos x 2 boxes. Embeddings from the
unmodified PyTorch encoder; reference masks/scores from the unmodified PyTorch
model's box-prompted decode."""
import sys, glob, os
import numpy as np
import torch
from PIL import Image
from transformers import Sam2Model

OUT = sys.argv[1]
m = Sam2Model.from_pretrained("facebook/sam2.1-hiera-tiny", revision="de431c4043854a71d8101e17995dfe596bf101a5").eval()
imgs = sorted(glob.glob("/Users/dev/Code/browser-perception/demos/object-selection/samples/*.jpg"))[4:8]
mean = np.array([0.485, 0.456, 0.406], np.float32); std = np.array([0.229, 0.224, 0.225], np.float32)
boxes = [[0.25, 0.35, 0.75, 0.95], [0.05, 0.05, 0.55, 0.60]]   # fractions of the image
ref_masks, ref_iou, lines = [], [], []
for i, path in enumerate(imgs):
    x = np.asarray(Image.open(path).convert("RGB").resize((1024, 1024), Image.BILINEAR), np.float32) / 255.0
    x = ((x - mean) / std).transpose(2, 0, 1)[None].copy()
    with torch.no_grad():
        emb = m.get_image_embeddings(torch.from_numpy(x))
    for k, e in enumerate(emb):
        e.numpy().astype(np.float32).tofile(f"{OUT}/inputs/img{i}_emb{k}.bin")
    for j, b in enumerate(boxes):
        box = (np.array(b, np.float32) * 1024).reshape(1, 1, 4)
        box.tofile(f"{OUT}/inputs/img{i}_box{j}.bin")
        with torch.no_grad():
            out = m(image_embeddings=list(emb), input_boxes=torch.from_numpy(box), multimask_output=True)
        ref_masks.append(out.pred_masks.numpy()[0, 0]); ref_iou.append(out.iou_scores.numpy()[0, 0])
        lines.append(",".join(f"/data/local/tmp/samdec/img{i}_{n}.bin" for n in ("emb0", "emb1", "emb2", f"box{j}")))
    print(i, os.path.basename(path))
open(f"{OUT}/inputs.txt", "w").write("\n".join(lines) + "\n")
np.save(f"{OUT}/ref_masks.npy", np.stack(ref_masks)); np.save(f"{OUT}/ref_iou.npy", np.stack(ref_iou))
print("samples", len(lines), "ref masks", np.stack(ref_masks).shape)
