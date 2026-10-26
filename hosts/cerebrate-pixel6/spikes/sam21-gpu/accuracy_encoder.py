"""Encoder outputs vs the original encoder's embeddings, then task level: masks
decoded by the original fp32 PyTorch decoder from the device embeddings, for
the same 8 box prompts, vs the reference masks (decoded from original
embeddings). out_map gives, per encoder output index, which embedding it is."""
import sys, json
import numpy as np
import torch
from transformers import Sam2Model
SAMENC, SAMDEC, out_map = sys.argv[1], sys.argv[2], json.loads(sys.argv[3])
configs = sys.argv[4:]
shapes = {0: (1, 32, 256, 256), 1: (1, 64, 128, 128), 2: (1, 256, 64, 64)}
m = Sam2Model.from_pretrained("facebook/sam2.1-hiera-tiny", revision="de431c4043854a71d8101e17995dfe596bf101a5").eval()
ref_masks = np.load(f"{SAMDEC}/ref_masks.npy")
boxes = [[0.25, 0.35, 0.75, 0.95], [0.05, 0.05, 0.55, 0.60]]
def cos(a, b): a, b = a.ravel().astype(np.float64), b.ravel().astype(np.float64); return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))
for c in configs:
    embs, line = [], []
    for i in range(4):
        e = {}
        for o, k in out_map.items():
            e[k] = np.fromfile(f"{SAMENC}/pulled/out-{c}/{i}_o{o}.bin", np.float32).reshape(shapes[k])
        embs.append(e)
    for k in (0, 1, 2):
        cs, rel = [], []
        for i in range(4):
            r = np.fromfile(f"{SAMDEC}/inputs/img{i}_emb{k}.bin", np.float32).reshape(shapes[k])
            g = embs[i][k]
            cs.append(cos(g, r)); rel.append(np.linalg.norm(g - r) / np.linalg.norm(r))
            # per-channel worst cosine
        line.append(f"emb{k} cos min {min(cs):.5f} relL2 max {max(rel):.3g}")
    ious, flips = [], 0
    for i in range(4):
        e = [torch.from_numpy(embs[i][k]) for k in (0, 1, 2)]
        for j, b in enumerate(boxes):
            box = torch.from_numpy((np.array(b, np.float32) * 1024).reshape(1, 1, 4))
            with torch.no_grad():
                got = m(image_embeddings=e, input_boxes=box, multimask_output=True).pred_masks.numpy()[0, 0]
            ref = ref_masks[i * 2 + j]
            for k in range(3):
                a, r = got[k] > 0, ref[k] > 0
                u = (a | r).sum(); ious.append((a & r).sum() / u if u else 1.0); flips += int((a != r).sum())
    print(f"{c:16} | " + " | ".join(line) + f" | task: mask IoU min {min(ious):.4f} mean {np.mean(ious):.4f}, pixels flipped {flips}")
