"""EdgeSAM box decoder for the Pixel 6 GPU/CPU (LiteRT), our litert-torch
conversion of the original prompt-encoder + mask-decoder path for one box,
one mask (the official demo's box prompting). GPU-clean structure from
sam21-gpu/build_box_decoder.py (itself adapted from litert-community's
SAM 2.1 decoder, Apache-2.0): rank-4 attention written out, plain
LayerNorm, transposed convs as zero-stuff + conv, and every constant
activation fed as an input (lane §4.5 rule 3: the dense no-mask embedding,
the image positional encoding and the output tokens; host writes them once).
Inputs: embeddings [1,64,64,256] NHWC (the encoder's device layout, so
tokens are a plain reshape), sparse [1,2,256] (the box's two corner tokens,
computed on the host by the original prompt encoder), dense [4096,256],
image_pe [4096,256], output_tokens [5,256]. Outputs: low-res mask logits
[1,256,256] for mask token 0 and its IoU score [1,1]; the host upscales
with the original postprocess_masks.
Stage 1: eager re-authoring vs the original decoder on all 132 boxes (from
the reference embeddings). Stage 2: converted vs eager. Writes device inputs.
usage: edgesam_decoder.py <dl-edgesam dir> <out dir (ref*.npz)> <decoder dir>"""
import sys, os
import numpy as np, torch
import torch.nn as nn, torch.nn.functional as F
import litert_torch
from edgesam_common import load_edgesam

D, OUT, DEC = sys.argv[1:4]
os.makedirs(f"{DEC}/inputs", exist_ok=True)


def plain_ln(x, weight, bias, eps):
    xc = x - x.mean(-1, keepdim=True)
    return xc * torch.rsqrt((xc * xc).mean(-1, keepdim=True) + eps) * weight + bias


class ZeroStuffConvT(nn.Module):
    """ConvTranspose2d(k=s, stride=s) == zero-stuff + Conv2d(flipped weights). (litert-community)"""
    def __init__(self, ct, H, W):
        super().__init__()
        self.s = ct.stride[0]; self.k = ct.kernel_size[0]
        self.register_buffer("w", ct.weight.flip(2, 3).transpose(0, 1).contiguous())
        self.register_buffer("b", ct.bias.detach().clone())
        mk = torch.zeros(H * self.s, W * self.s); mk[::self.s, ::self.s] = 1.0
        self.register_buffer("mask", mk[None, None])
    def forward(self, x):
        H, W = x.shape[-2], x.shape[-1]
        y = F.conv2d(F.interpolate(x, size=(H * self.s, W * self.s), mode="nearest") * self.mask, self.w, bias=self.b, padding=self.k - 1)
        return y[:, :, :H * self.s, :W * self.s]


class EdgeBoxDecoder(nn.Module):
    def __init__(self, sam):
        super().__init__()
        dec = sam.mask_decoder; tr = dec.transformer
        self.layers, self.final_attn, self.norm_final = tr.layers, tr.final_attn_token_to_image, tr.norm_final_attn
        up = dec.output_upscaling
        self.ct1, self.ln_up, self.ct2 = ZeroStuffConvT(up[0], 64, 64), up[1], ZeroStuffConvT(up[3], 128, 128)
        self.mlp0, self.iou_head = dec.output_hypernetworks_mlps[0], dec.iou_prediction_head
    def _ln(self, m, x):
        return plain_ln(x, m.weight, m.bias, m.eps)
    def _attn(self, mod, q, k, v):
        """Rank-4 attention [1, heads, N, d], written out."""
        H = mod.num_heads; d = mod.internal_dim // H
        q = mod.q_proj(q).reshape(1, q.shape[0], H, d).transpose(1, 2)
        k = mod.k_proj(k).reshape(1, k.shape[0], H, d).transpose(1, 2)
        v = mod.v_proj(v).reshape(1, v.shape[0], H, d).transpose(1, 2)
        a = torch.softmax(torch.matmul(q, k.transpose(-1, -2)) / float(np.sqrt(d)), dim=-1)
        return mod.out_proj(torch.matmul(a, v).transpose(1, 2).reshape(-1, mod.internal_dim))
    def _block(self, layer, queries, keys, qpe, kpe):
        if layer.skip_first_layer_pe:
            queries = self._attn(layer.self_attn, queries, queries, queries)
        else:
            qq = queries + qpe; queries = queries + self._attn(layer.self_attn, qq, qq, queries)
        queries = self._ln(layer.norm1, queries)
        queries = self._ln(layer.norm2, queries + self._attn(layer.cross_attn_token_to_image, queries + qpe, keys + kpe, keys))
        queries = self._ln(layer.norm3, queries + layer.mlp(queries))
        keys = self._ln(layer.norm4, keys + self._attn(layer.cross_attn_image_to_token, keys + kpe, queries + qpe, queries))
        return queries, keys
    def forward(self, emb_nhwc, sparse, dense, image_pe, output_tokens):
        keys = emb_nhwc.reshape(4096, 256) + dense
        queries = torch.cat([output_tokens, sparse[0]], 0); qpe = queries
        for layer in self.layers:
            queries, keys = self._block(layer, queries, keys, qpe, image_pe)
        queries = self._ln(self.norm_final, queries + self._attn(self.final_attn, queries + qpe, keys + image_pe, keys))
        img = keys.transpose(0, 1).reshape(1, 256, 64, 64)
        u = self.ct1(img)
        u = plain_ln(u.permute(0, 2, 3, 1), self.ln_up.weight, self.ln_up.bias, self.ln_up.eps).permute(0, 3, 1, 2)
        u = F.gelu(self.ct2(F.gelu(u)))
        mask = (self.mlp0(queries[1:2]) @ u.reshape(32, 256 * 256)).reshape(1, 256, 256)
        return mask, self.iou_head(queries[0:1])[:, 0:1]


sam, pred = load_edgesam(D, "bicubic")
net = EdgeBoxDecoder(sam).eval()
with torch.no_grad():
    pe = sam.prompt_encoder
    dense = pe.no_mask_embed.weight.reshape(1, 256).expand(4096, 256).contiguous()
    image_pe = pe.get_dense_pe()[0].flatten(1).transpose(0, 1).contiguous()
    out_tokens = torch.cat([sam.mask_decoder.iou_token.weight, sam.mask_decoder.mask_tokens.weight], 0).contiguous()
for name, t in (("dense", dense), ("image_pe", image_pe), ("output_tokens", out_tokens)):
    t.numpy().astype(np.float32).tofile(f"{DEC}/inputs/{name}.bin")
worst_iou, worst_logit, worst_score, n, lines, example = 1.0, 0.0, 0.0, 0, [], None
index = []
for i in range(8):
    ref = np.load(f"{OUT}/ref{i}.npz")
    emb = torch.from_numpy(ref["emb"]); emb_nhwc = emb.permute(0, 2, 3, 1).contiguous()
    emb_nhwc.numpy().tofile(f"{DEC}/inputs/emb{i}.bin")
    pred.original_size, pred.input_size, pred.is_image_set = tuple(ref["original_size"]), tuple(ref["input_size"]), True
    for j, b in enumerate(ref["boxes"]):
        box = torch.as_tensor(pred.transform.apply_boxes(b, pred.original_size), dtype=torch.float)[None]
        with torch.no_grad():
            sparse, _ = pe(points=None, boxes=box, masks=None)
            _, iou_ref, low_ref = pred.predict_torch(emb, None, None, box, None, 1, return_logits=True, use_stability_score=False)
            mask, iou = net(emb_nhwc, sparse, dense, image_pe, out_tokens)
        a, r = mask.numpy()[0] > 0, low_ref.numpy()[0, 0] > 0
        worst_iou = min(worst_iou, (a & r).sum() / max(1, (a | r).sum()))
        worst_logit = max(worst_logit, float(np.abs(mask.numpy()[0] - low_ref.numpy()[0, 0]).max()))
        worst_score = max(worst_score, float(abs(iou.item() - iou_ref.item())))
        sparse.numpy().astype(np.float32).tofile(f"{DEC}/inputs/sparse{i}_{j}.bin")
        lines.append(",".join(f"/data/local/tmp/edgesam/dec/inputs/{f}.bin" for f in (f"emb{i}", f"sparse{i}_{j}", "dense", "image_pe", "output_tokens")))
        index.append((i, j)); n += 1
        if example is None: example = (emb_nhwc, sparse, dense, image_pe, out_tokens)
print(f"stage 1 ({n} boxes, eager re-authoring vs original, low-res logits): worst thresholded IoU {worst_iou:.6f}, "
      f"max |logit diff| {worst_logit:.2e}, max |score diff| {worst_score:.2e}", flush=True)
open(f"{DEC}/inputs.txt", "w").write("\n".join(lines) + "\n")
np.save(f"{DEC}/index.npy", np.array(index))
edge = litert_torch.convert(net, example)
path = f"{DEC}/edgesam3x-box-decoder-fp32.tflite"; edge.export(path)
with torch.no_grad():
    em, ei = net(*example)
gm, gi = (np.asarray(t) for t in edge(*example))
print(f"stage 2 (converted vs eager, box 0): mask max |diff| {np.abs(gm - em.numpy()).max():.2e}, score diff {abs(float(gi.ravel()[0]) - ei.item()):.2e} | {path}", flush=True)
