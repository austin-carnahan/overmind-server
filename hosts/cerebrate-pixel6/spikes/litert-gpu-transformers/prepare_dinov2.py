"""DINOv2-small prepared for the LiteRT GPU accelerator on the Pixel 6:
  1. embeddings frozen for 224x224 (no BROADCAST_TO / GATHER_ND);
  2. every LayerScale folded into the linear layer before it (o_proj, fc2):
     LiteRT's GPU computes the [1,257,384] x [384] broadcast multiply wrongly
     on this Mali GPU, and scaling a Linear's output channels by lambda is
     exactly scaling its weight rows and bias by lambda.
Checked against the unmodified PyTorch model before and after conversion."""
import sys
import numpy as np
import torch
import litert_torch
from transformers import AutoModel

OUT = sys.argv[1]
REPO, REV = "facebook/dinov2-small", "ed25f3a31f01632728cabb09d1542f84ab7b0056"
base = AutoModel.from_pretrained(REPO, revision=REV).eval()
x = torch.from_numpy(((np.arange(3 * 224 * 224) * 7 % 256) / 127.5 - 1.0).astype(np.float32).reshape(1, 3, 224, 224))
with torch.no_grad():
    ref = base(pixel_values=x).last_hidden_state.numpy()
    emb = base.embeddings
    pos = emb.interpolate_pos_encoding(torch.cat([emb.cls_token, emb.patch_embeddings(x)], 1), 224, 224).detach().clone()
    for layer in base.encoder.layer:
        for scale, linear in ((layer.layer_scale1, layer.attention.o_proj), (layer.layer_scale2, layer.mlp.fc2)):
            lam = scale.lambda1.detach()
            linear.weight.mul_(lam[:, None])
            linear.bias.mul_(lam)
        layer.layer_scale1 = torch.nn.Identity()
        layer.layer_scale2 = torch.nn.Identity()

class Prepared(torch.nn.Module):
    def __init__(self, m, pos):
        super().__init__()
        self.patch = m.embeddings.patch_embeddings
        self.cls = torch.nn.Parameter(m.embeddings.cls_token.detach().clone(), requires_grad=False)
        self.register_buffer("pos", pos)
        self.encoder = m.encoder
        self.norm = m.layernorm
    def forward(self, pixel_values):
        h = torch.cat([self.cls, self.patch(pixel_values)], dim=1) + self.pos
        return self.norm(self.encoder(h).last_hidden_state)

m = Prepared(base, pos).eval()
with torch.no_grad():
    mine = m(x).numpy()
print("prepared vs original PyTorch: max_abs_diff", float(np.abs(mine - ref).max()), flush=True)
edge = litert_torch.convert(m, (x,))
path = f"{OUT}/dinov2-small-prepared-fp32.tflite"
edge.export(path)
got = np.asarray(edge(x))
cos = float((got.ravel() @ ref.ravel()) / (np.linalg.norm(got) * np.linalg.norm(ref)))
print("EXPORTED", path, f"vs original PyTorch: cosine={cos:.6f} max_abs_diff={np.abs(got - ref).max():.3g}", flush=True)
