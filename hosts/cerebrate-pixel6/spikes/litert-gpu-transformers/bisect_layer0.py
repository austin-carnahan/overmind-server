"""Sub-blocks of DINOv2-small layer 0, each fed the (GPU-correct) frozen
embedding output, for bisecting which op the LiteRT GPU gets wrong."""
import math, sys
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
L = base.encoder.layer[0]

heads = base.config.num_attention_heads

class Block(torch.nn.Module):
    def __init__(self, part):
        super().__init__()
        self.part = part
        self.patch = emb.patch_embeddings
        self.cls = torch.nn.Parameter(emb.cls_token.detach().clone(), requires_grad=False)
        self.register_buffer("pos", pos)
        self.L = L
    def forward(self, pixel_values):
        h = torch.cat([self.cls, self.patch(pixel_values)], dim=1) + self.pos
        n = self.L.norm1(h)
        if self.part == "norm1":
            return n
        sa = self.L.attention
        q = sa.q_proj(n)
        if self.part == "query":
            return q
        k = sa.k_proj(n)
        B, T, C = q.shape
        d = C // heads
        qh = q.view(B, T, heads, d).transpose(1, 2)
        kh = k.view(B, T, heads, d).transpose(1, 2)
        scores = torch.matmul(qh, kh.transpose(-1, -2)) / math.sqrt(d)
        if self.part == "scores":
            return scores
        probs = torch.softmax(scores, dim=-1)
        if self.part == "softmax":
            return probs
        v = sa.v_proj(n).view(B, T, heads, d).transpose(1, 2)
        ctx = torch.matmul(probs, v).transpose(1, 2).reshape(B, T, C)
        if self.part == "context":
            return ctx
        a = sa.o_proj(ctx)
        if self.part == "oproj":
            return a
        scaled = self.L.layer_scale1(a)
        if self.part == "layerscale":
            return scaled
        if self.part == "residual_unscaled":
            return h + a
        h2 = h + scaled
        if self.part == "attn_residual":
            return h2
        m = self.L.mlp(self.L.norm2(h2))
        if self.part == "mlp":
            return m
        return h2 + self.L.layer_scale2(m)

with torch.no_grad():
    full = Block("full")(x).numpy()
    ref_layer = L(torch.cat([emb.cls_token, emb.patch_embeddings(x)], 1) + pos)
    ref_layer = (ref_layer[0] if isinstance(ref_layer, (tuple, list)) else ref_layer).numpy()
print("manual layer vs HF layer: max_abs_diff", float(np.abs(full - ref_layer).max()), flush=True)
for part in sys.argv[2:]:
    m = Block(part).eval()
    with torch.no_grad():
        ref = m(x).numpy()
    edge = litert_torch.convert(m, (x,))
    path = f"{OUT}/dinov2-L0-{part}.tflite"
    edge.export(path)
    got = np.asarray(edge(x))
    cos = float((got.ravel() @ ref.ravel()) / (np.linalg.norm(got) * np.linalg.norm(ref)))
    print("EXPORTED", path, got.shape, f"vs PyTorch cosine={cos:.6f}", flush=True)
