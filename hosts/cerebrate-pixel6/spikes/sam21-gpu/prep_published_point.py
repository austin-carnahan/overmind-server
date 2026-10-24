"""Point-prompt test set for the published v2 decoder (its native 2-token
prompt: one positive click + padding), with references from the unmodified
PyTorch model decoding the same clicks from the original embeddings."""
import sys
import numpy as np
import torch
from transformers import Sam2Model
SAMDEC, OUT = sys.argv[1], sys.argv[2]
m = Sam2Model.from_pretrained("facebook/sam2.1-hiera-tiny", revision="de431c4043854a71d8101e17995dfe596bf101a5").eval()
shapes = ((1, 32, 256, 256), (1, 64, 128, 128), (1, 256, 64, 64))
points = [[0.5, 0.65], [0.3, 0.33]]          # fractions; inside the two test boxes
masks, ious, lines = [], [], []
for i in range(4):
    emb = [torch.from_numpy(np.fromfile(f"{SAMDEC}/inputs/img{i}_emb{k}.bin", np.float32).reshape(s)) for k, s in enumerate(shapes)]
    for j, pt in enumerate(points):
        p = torch.tensor([[[[pt[0] * 1024, pt[1] * 1024]]]], dtype=torch.float32)
        lab = torch.tensor([[[1]]], dtype=torch.int64)
        with torch.no_grad():
            sparse, _ = m.prompt_encoder(input_points=(p, lab), input_labels=lab, input_boxes=None, input_masks=None) if False else m.prompt_encoder(input_points=p, input_labels=lab, input_boxes=None, input_masks=None)
            out = m(image_embeddings=emb, input_points=p, input_labels=lab, multimask_output=True)
        sp = sparse.reshape(1, -1, 256).numpy().astype(np.float32)
        assert sp.shape == (1, 2, 256), sp.shape
        sp.tofile(f"{OUT}/inputs/img{i}_pt{j}_sparse.bin")
        masks.append(out.pred_masks.numpy()[0, 0]); ious.append(out.iou_scores.numpy()[0, 0])
        lines.append(",".join([f"/data/local/tmp/samdec/img{i}_emb2.bin", f"/data/local/tmp/pubdec/img{i}_pt{j}_sparse.bin",
                               f"/data/local/tmp/samdec/img{i}_emb1.bin", f"/data/local/tmp/samdec/img{i}_emb0.bin"]))
np.save(f"{OUT}/ref_masks.npy", np.stack(masks)); np.save(f"{OUT}/ref_iou.npy", np.stack(ious))
open(f"{OUT}/inputs.txt", "w").write("\n".join(lines) + "\n")
print("samples", len(lines), "sparse tokens", sp.shape)
