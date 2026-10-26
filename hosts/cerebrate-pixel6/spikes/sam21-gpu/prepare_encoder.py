"""SAM 2.1 Hiera Tiny image encoder prepared for LiteRT's GPU path (batch 1,
1024x1024). Exact rewrites, each removing something the GPU can't take:
  1. position embedding (bicubic resize + 8-D tile) precomputed as a constant;
  2. window partition/unpartition (6-D view+permute) rewritten in 4-D by merging
     the trailing (window, C) dims, which stay adjacent;
  3. attention's 5-D [B, N, 3, heads, d] Q/K/V split rewritten as three
     contiguous slices of the last dim, then 4-D per tensor; eager attention;
  4. the neck's unused sine position encodings dropped (BROADCAST_TO);
  5. the per-channel no-memory embedding folded into its level's conv bias.
Checked against the unmodified model in PyTorch on every test photo, then
converted and checked again."""
import sys
import numpy as np
import torch
import torch.nn.functional as F
import litert_torch
from transformers import Sam2Model
from transformers.models.sam2.modeling_sam2 import do_pool

OUT, ENC_DIR = sys.argv[1], sys.argv[2]
m = Sam2Model.from_pretrained("facebook/sam2.1-hiera-tiny", revision="de431c4043854a71d8101e17995dfe596bf101a5").eval()
bb, neck = m.vision_encoder.backbone, m.vision_encoder.neck

def partition4d(x, ws):
    _, H, W, C = x.shape
    x = F.pad(x, (0, 0, 0, (-W) % ws, 0, (-H) % ws))
    Hp, Wp = x.shape[1], x.shape[2]
    nh, nw = Hp // ws, Wp // ws
    x = x.reshape(nh, ws, nw, ws * C).transpose(1, 2).reshape(nh * nw, ws, ws, C)
    return x, (Hp, Wp)

def unpartition4d(win, ws, pad_hw, hw):
    (Hp, Wp), (H, W) = pad_hw, hw
    nh, nw, C = Hp // ws, Wp // ws, win.shape[-1]
    x = win.reshape(nh, nw, ws, ws * C).transpose(1, 2).reshape(1, Hp, Wp, C)
    return x[:, :H, :W, :]

def attention4d(a, x):
    B, h, w, _ = x.shape
    heads, d = a.num_attention_heads, a.dim_out // a.num_attention_heads
    qkv = a.qkv(x).reshape(B, h * w, 3 * a.dim_out)
    q, k, v = (t.reshape(B, h * w, heads, d) for t in torch.split(qkv, a.dim_out, dim=-1))
    if a.query_stride:
        q = do_pool(q.reshape(B, h, w, heads * d), a.query_stride)
        h, w = q.shape[1:3]
        q = q.reshape(B, h * w, heads, d)
    q, k, v = q.transpose(1, 2), k.transpose(1, 2), v.transpose(1, 2)
    attn = torch.softmax(torch.matmul(q, k.transpose(-2, -1)) * a.scale, dim=-1)
    out = torch.matmul(attn, v).transpose(1, 2).reshape(B, h, w, a.dim_out)
    return a.proj(out)

def block4d(blk, hstate):
    residual = hstate
    x = blk.layer_norm1(hstate)
    if blk.dim != blk.dim_out:
        residual = do_pool(blk.proj(x), blk.query_stride)
    ws = blk.window_size
    if ws > 0:
        H, W = x.shape[1], x.shape[2]
        x, pad_hw = partition4d(x, ws)
    x = attention4d(blk.attn, x)
    if blk.query_stride:
        ws = blk.window_size // blk.query_stride[0]
        H, W = residual.shape[1:3]
        pad_hw = (H + (-H) % ws, W + (-W) % ws)
    if blk.window_size > 0:
        x = unpartition4d(x, ws, pad_hw, (H, W))
    hstate = residual + x
    return hstate + blk.mlp(blk.layer_norm2(hstate))

class PreparedEncoder(torch.nn.Module):
    def __init__(self, m):
        super().__init__()
        self.patch, self.blocks, self.stage_ends = bb.patch_embed, bb.blocks, list(bb.stage_ends)
        with torch.no_grad():
            self.register_buffer("pos", bb._get_pos_embed((256, 256)).detach().clone())
        self.convs, self.top_down = neck.convs, list(neck.fpn_top_down_levels)
        self.levels = m.vision_encoder.num_feature_levels
        self.conv_s0, self.conv_s1 = m.mask_decoder.conv_s0, m.mask_decoder.conv_s1
        # Fold no_memory_embedding (added to the lowest-resolution kept level) into that level's conv bias.
        # The neck emits levels from low to high resolution (stage index n..0) and
        # keeps the last `levels`, so the lowest-resolution kept level is stage
        # index levels - 1, produced by convs[n - (levels - 1)].
        n = len(self.convs) - 1
        low = self.levels - 1
        assert (low - 1) not in self.top_down, "folding would leak into a top-down consumer"
        with torch.no_grad():
            self.convs[n - low].bias.add_(m.no_memory_embedding.reshape(-1))
    def forward(self, pixel_values):
        h = self.patch(pixel_values) + self.pos
        inter = []
        for i, blk in enumerate(self.blocks):
            h = block4d(blk, h)
            if i in self.stage_ends:
                inter.append(h)
        n, fpn, prev = len(self.convs) - 1, [], None
        for i in range(n, -1, -1):
            lat = self.convs[n - i](inter[i].permute(0, 3, 1, 2))
            prev = lat if (i not in self.top_down or i == n) else lat + F.interpolate(prev, scale_factor=2.0, mode="nearest")
            fpn.append(prev)
        fpn = fpn[-self.levels:][::-1]
        return self.conv_s0(fpn[0]), self.conv_s1(fpn[1]), fpn[2]

ref_model = Sam2Model.from_pretrained("facebook/sam2.1-hiera-tiny", revision="de431c4043854a71d8101e17995dfe596bf101a5").eval()
prep = PreparedEncoder(m).eval()
xs = [torch.from_numpy(np.fromfile(f"{ENC_DIR}/inputs/img{i}_px.bin", np.float32).reshape(1, 3, 1024, 1024)) for i in range(4)]
with torch.no_grad():
    for i, x in enumerate(xs):
        ref = ref_model.get_image_embeddings(x); got = prep(x)
        print(f"img{i} prepared vs original PyTorch: max_abs per output", [f"{float((g - r).abs().max()):.2e}" for g, r in zip(got, ref)], flush=True)
edge = litert_torch.convert(prep, (xs[0],))
path = f"{OUT}/sam21t-encoder-prepared-fp32.tflite"
edge.export(path)
with torch.no_grad():
    ref = [t.numpy() for t in ref_model.get_image_embeddings(xs[0])]
got = [np.asarray(t) for t in edge(xs[0])]
for k, (g, r) in enumerate(zip(got, ref)):
    c = float(g.ravel() @ r.ravel() / (np.linalg.norm(g) * np.linalg.norm(r)))
    print(f"EXPORTED emb{k} {g.shape} vs original PyTorch cosine={c:.6f} max_abs={np.abs(g - r).max():.3g}", flush=True)
