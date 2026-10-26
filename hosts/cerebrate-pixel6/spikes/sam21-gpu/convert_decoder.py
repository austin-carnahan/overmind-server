"""SAM 2.1 Hiera Tiny box-prompted decoder -> fp32 .tflite.
Step 1 validates the PyTorch reference itself against browser-perception's
ONNX outputs (same image, same box); step 2 converts and checks the result."""
import sys
import numpy as np
import torch
import litert_torch
from transformers import Sam2Model
from huggingface_hub import model_info

OUT, GPU = sys.argv[1], sys.argv[2]   # GPU = dir with samenc32_* / samdec32_* npz from the WebGPU work
REPO = "facebook/sam2.1-hiera-tiny"
REV = model_info(REPO).sha
print("model", REPO, "revision", REV, flush=True)
m = Sam2Model.from_pretrained(REPO, revision=REV).eval()

def cos(a, b): a, b = np.ravel(a).astype(np.float64), np.ravel(b).astype(np.float64); return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))

px = torch.from_numpy(np.load(f"{GPU}/samenc32_in.npz")["pixel_values"])
enc_ref = np.load(f"{GPU}/samenc32_ref.npz")
with torch.no_grad():
    emb = m.get_image_embeddings(px)
for i, e in enumerate(emb):
    r = enc_ref[f"image_embeddings.{i}"]
    print(f"encoder emb{i} {tuple(e.shape)} vs ONNX: cosine={cos(e.numpy(), r):.6f} max_abs={np.abs(e.numpy() - r).max():.3g}", flush=True)

class BoxDecoder(torch.nn.Module):
    def __init__(self, m):
        super().__init__(); self.m = m
    def forward(self, emb0, emb1, emb2, boxes):
        out = self.m(image_embeddings=[emb0, emb1, emb2], input_boxes=boxes, multimask_output=True)
        return out.pred_masks, out.iou_scores

dec = BoxDecoder(m).eval()
dec_in = np.load(f"{GPU}/samdec32_in.npz"); dec_ref = np.load(f"{GPU}/samdec32_ref.npz")
args = tuple(torch.from_numpy(dec_in[k]) for k in ("image_embeddings.0", "image_embeddings.1", "image_embeddings.2", "input_boxes"))
with torch.no_grad():
    masks, iou = dec(*args)
print("decoder pred_masks", tuple(masks.shape), "vs ONNX: cosine=%.6f max_abs=%.3g" % (cos(masks.numpy(), dec_ref["pred_masks"]), np.abs(masks.numpy() - dec_ref["pred_masks"]).max()), flush=True)
print("decoder iou", iou.numpy().ravel(), "ONNX", dec_ref["iou_scores"].ravel(), flush=True)

edge = litert_torch.convert(dec, args)
path = f"{OUT}/sam21t-box-decoder-fp32.tflite"
edge.export(path)
gm, gi = (np.asarray(t) for t in edge(*args))
print("EXPORTED", path, "masks cosine vs PyTorch=%.6f max_abs=%.3g | iou %s" % (cos(gm, masks.numpy()), np.abs(gm - masks.numpy()).max(), np.round(gi.ravel(), 4)), flush=True)
