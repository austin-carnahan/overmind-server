"""Truncated frozen-DINOv2-small models for bisecting the LiteRT GPU error:
embeddings only, then +1, +6, +12 encoder layers (no final norm). Each is
checked against PyTorch on CPU after conversion."""
import sys
import numpy as np
import torch
import litert_torch
from transformers import AutoModel

OUT = sys.argv[1]
REPO, REV = "facebook/dinov2-small", "ed25f3a31f01632728cabb09d1542f84ab7b0056"
base = AutoModel.from_pretrained(REPO, revision=REV).eval()
x = torch.from_numpy(((np.arange(3 * 224 * 224) * 7 % 256) / 127.5 - 1.0).astype(np.float32).reshape(1, 3, 224, 224))
emb = base.embeddings
with torch.no_grad():
    pos = emb.interpolate_pos_encoding(torch.cat([emb.cls_token, emb.patch_embeddings(x)], 1), 224, 224).detach().clone()

class Truncated(torch.nn.Module):
    def __init__(self, m, pos, n_layers):
        super().__init__()
        self.patch = m.embeddings.patch_embeddings
        self.cls = torch.nn.Parameter(m.embeddings.cls_token.detach().clone(), requires_grad=False)
        self.register_buffer("pos", pos)
        self.layers = torch.nn.ModuleList(m.encoder.layer[:n_layers])
    def forward(self, pixel_values):
        h = torch.cat([self.cls, self.patch(pixel_values)], dim=1) + self.pos
        for layer in self.layers:
            out = layer(h)
            h = out[0] if isinstance(out, (tuple, list)) else out
        return h

for n in (0, 1, 6, 12):
    m = Truncated(base, pos, n).eval()
    with torch.no_grad():
        ref = m(x).numpy()
    edge = litert_torch.convert(m, (x,))
    path = f"{OUT}/dinov2-trunc-L{n}.tflite"
    edge.export(path)
    got = np.asarray(edge(x))
    cos = float((got.ravel() @ ref.ravel()) / (np.linalg.norm(got) * np.linalg.norm(ref)))
    print("EXPORTED", path, got.shape, f"vs PyTorch cosine={cos:.6f}", flush=True)
