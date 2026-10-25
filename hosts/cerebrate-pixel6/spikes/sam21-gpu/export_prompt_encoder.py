"""SAM 2.1 Hiera-Tiny's box prompt encoder constants for the guest adapter
(model_hooks.Sam2Hooks): the Gaussian positional-encoding matrix [2,128], the
two box-corner embeddings and the not-a-point embedding (all float32), from
the original checkpoint; then the numpy box path checked against
transformers' Sam2PromptEncoder and the sparse embeddings the validated
decoder runs used (boxdec/inputs/img*_box*_sparse.bin).
usage: export_prompt_encoder.py <out .npz> [<boxdec dir>]"""
import sys, glob
import numpy as np, torch
from transformers import Sam2Model
OUT = sys.argv[1]
m = Sam2Model.from_pretrained("facebook/sam2.1-hiera-tiny", revision="de431c4043854a71d8101e17995dfe596bf101a5").eval()
pe = m.prompt_encoder
c = {"gauss": pe.shared_embedding.positional_embedding.detach().numpy().astype(np.float32),
     "corner0": pe.point_embed.weight[2].detach().numpy().astype(np.float32),
     "corner1": pe.point_embed.weight[3].detach().numpy().astype(np.float32),
     "not_a_point": pe.not_a_point_embed.weight[0].detach().numpy().astype(np.float32),
     "input_size": np.array(pe.input_image_size, np.int64)}
np.savez(OUT, **c)

def sparse(box):   # box: float32 [4] xyxy in the 1024 frame -> [3, 256]
    pts = (box.reshape(2, 2) + np.float32(0.5)) / np.float32(c["input_size"])
    coords = (np.float32(2) * pts - np.float32(1)) @ c["gauss"]
    coords = np.float32(2 * np.pi) * coords
    emb = np.concatenate([np.sin(coords), np.cos(coords)], -1).astype(np.float32)
    return np.stack([emb[0] + c["corner0"], emb[1] + c["corner1"], c["not_a_point"]])

worst = 0.0
rng = np.random.default_rng(0)
for _ in range(64):
    b = np.sort(rng.uniform(0, 1024, (2, 2)), axis=0).T.reshape(4).astype(np.float32)
    with torch.no_grad():
        ref = pe(input_points=None, input_labels=None, input_boxes=torch.from_numpy(b.reshape(1, 1, 4).copy()), input_masks=None)[0].numpy().reshape(3, 256)   # copy: transformers shifts boxes in place
    worst = max(worst, float(np.abs(sparse(b) - ref).max()))
print(f"numpy box path vs Sam2PromptEncoder, 64 random boxes: max |diff| {worst:.2e}")
if len(sys.argv) > 2:
    boxes = [[0.25, 0.35, 0.75, 0.95], [0.05, 0.05, 0.55, 0.60]]
    w2 = 0.0
    for f in sorted(glob.glob(f"{sys.argv[2]}/inputs/img*_box*_sparse.bin")):
        j = int(f.split("_box")[1].split("_")[0])
        got = sparse((np.array(boxes[j], np.float32) * 1024))
        w2 = max(w2, float(np.abs(got - np.fromfile(f, np.float32).reshape(3, 256)).max()))
    print(f"numpy box path vs the validated decoder inputs (8 files): max |diff| {w2:.2e}")
