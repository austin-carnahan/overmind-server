"""Box-prompted, fully GPU-clean SAM 2.1 Hiera-Tiny mask decoder, fp32 weights.

Re-authoring adapted from litert-community/SAM2.1-Hiera-Tiny-Mask-Decoder's
convert_sam2_decoder.py (revision 049c2500, Apache-2.0): ZeroStuffConvT for the
transposed convs, baked positional/dense constants, <=4-D mask head, static
multimask slice. Changes here, both following that repository's own notes:
rank-4 attention [1, heads, N, d] (their v2 fix for wrong rank-3 results on a
Pixel 8a GPU), and plain LayerNorm for the decoder (their note: scale-before-
square LayerNorm hurt GPU fp16 in the decoder). Box prompts give 3 sparse
tokens (two corners + padding), computed host-side by the original prompt
encoder. Stage 1 (vs original on 8 samples) and stage 2 (converted vs eager)."""
import sys, math
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import litert_torch
from transformers import Sam2Model

SAMDEC, OUT = sys.argv[1], sys.argv[2]

def plain_ln(x, weight, bias, eps):
    xc = x - x.mean(-1, keepdim=True)
    var = (xc * xc).mean(-1, keepdim=True)
    return xc * torch.rsqrt(var + eps) * weight + bias

class ZeroStuffConvT(nn.Module):
    """ConvTranspose2d(k=s, stride=s) == zero-stuff + Conv2d(flipped weights). (litert-community)"""
    def __init__(self, ct, H, W):
        super().__init__()
        self.s = ct.stride[0]; self.k = ct.kernel_size[0]
        self.register_buffer("w", ct.weight.flip(2, 3).transpose(0, 1).contiguous())
        self.register_buffer("b", ct.bias.detach().clone() if ct.bias is not None else torch.zeros(ct.out_channels))
        mk = torch.zeros(H * self.s, W * self.s); mk[::self.s, ::self.s] = 1.0
        self.register_buffer("mask", mk[None, None])
    def forward(self, x):
        H, W = x.shape[-2], x.shape[-1]
        xn = F.interpolate(x, size=(H * self.s, W * self.s), mode="nearest")
        y = F.conv2d(xn * self.mask, self.w, bias=self.b, padding=self.k - 1)
        return y[:, :, :H * self.s, :W * self.s]

class BoxMaskDecoder(nn.Module):
    """Static SAM 2.1 mask decoder, batch == point_batch == 1. (adapted from litert-community)"""
    def __init__(self, model):
        super().__init__()
        dec = model.mask_decoder
        self.layers = dec.transformer.layers
        self.final_attn = dec.transformer.final_attn_token_to_image
        self.ln_final = dec.transformer.layer_norm_final_attn
        self.mlps = dec.output_hypernetworks_mlps
        self.iou_head = dec.iou_prediction_head
        self.act = dec.activation
        self.upscale_ln = dec.upscale_layer_norm
        self.upscale_conv1 = ZeroStuffConvT(dec.upscale_conv1, 64, 64)
        self.upscale_conv2 = ZeroStuffConvT(dec.upscale_conv2, 128, 128)
        with torch.no_grad():
            image_pos = model.get_image_wide_positional_embeddings()
            self.register_buffer("image_pos_flat", image_pos.flatten(2).transpose(1, 2)[0].contiguous())
            dense = model.prompt_encoder.no_mask_embed.weight.reshape(1, -1, 1, 1).expand(1, 256, 64, 64).contiguous()
            self.register_buffer("dense", dense)
            out_tokens = torch.cat([dec.obj_score_token.weight, dec.iou_token.weight, dec.mask_tokens.weight], 0)
            self.register_buffer("output_tokens", out_tokens.contiguous())
    def _ln(self, m, x):
        return plain_ln(x, m.weight, m.bias, m.eps)
    def _attn(self, mod, query, key, value):
        """Rank-4 attention [1, heads, N, d] -- written out (no SDPA op)."""
        Nq, Nk = query.shape[0], key.shape[0]
        H, hd = mod.num_attention_heads, mod.head_dim
        q = mod.q_proj(query).reshape(1, Nq, H, hd).transpose(1, 2)
        k = mod.k_proj(key).reshape(1, Nk, H, hd).transpose(1, 2)
        v = mod.v_proj(value).reshape(1, Nk, H, hd).transpose(1, 2)
        a = torch.softmax(torch.matmul(q, k.transpose(-1, -2)) * mod.scaling, dim=-1)
        o = torch.matmul(a, v).transpose(1, 2).reshape(Nq, H * hd)
        return mod.o_proj(o)
    def _block(self, layer, queries, keys, qpe, kpe, skip):
        if skip:
            queries = self._attn(layer.self_attn, queries, queries, queries)
        else:
            qq = queries + qpe
            queries = queries + self._attn(layer.self_attn, qq, qq, queries)
        queries = self._ln(layer.layer_norm1, queries)
        qq = queries + qpe; kk = keys + kpe
        queries = queries + self._attn(layer.cross_attn_token_to_image, qq, kk, keys)
        queries = self._ln(layer.layer_norm2, queries)
        queries = queries + layer.mlp(queries)
        queries = self._ln(layer.layer_norm3, queries)
        qq = queries + qpe; kk = keys + kpe
        keys = keys + self._attn(layer.cross_attn_image_to_token, kk, qq, queries)
        keys = self._ln(layer.layer_norm4, keys)
        return queries, keys
    def forward(self, image_embeddings, sparse, feat_s1, feat_s0):
        keys = (image_embeddings + self.dense).flatten(2).transpose(1, 2)[0]
        kpe = self.image_pos_flat
        queries = torch.cat([self.output_tokens, sparse[0]], 0)
        qpe = queries
        q, k = self._block(self.layers[0], queries, keys, qpe, kpe, skip=True)
        q, k = self._block(self.layers[1], q, k, qpe, kpe, skip=False)
        q = q + self._attn(self.final_attn, q + qpe, k + kpe, k)
        q = self._ln(self.ln_final, q)
        iou_tok, mask_toks = q[1:2], q[2:6]
        img = k.transpose(0, 1).reshape(1, 256, 64, 64)
        u = self.upscale_conv1(img) + feat_s1
        u = plain_ln(u.permute(0, 2, 3, 1), self.upscale_ln.weight, self.upscale_ln.bias, self.upscale_ln.eps).permute(0, 3, 1, 2)
        u = self.act(u)
        u = self.act(self.upscale_conv2(u) + feat_s0)
        hyper = torch.cat([self.mlps[j](mask_toks[j:j + 1]) for j in range(4)], 0)
        masks = (hyper @ u.reshape(32, 256 * 256)).reshape(4, 256, 256)[1:].unsqueeze(0)
        return masks, self.iou_head(iou_tok)[:, 1:]

m = Sam2Model.from_pretrained("facebook/sam2.1-hiera-tiny", revision="de431c4043854a71d8101e17995dfe596bf101a5").eval()
net = BoxMaskDecoder(m).eval()
ref_masks, ref_iou = np.load(f"{SAMDEC}/ref_masks.npy"), np.load(f"{SAMDEC}/ref_iou.npy")
boxes = [[0.25, 0.35, 0.75, 0.95], [0.05, 0.05, 0.55, 0.60]]
shapes = ((1, 32, 256, 256), (1, 64, 128, 128), (1, 256, 64, 64))
lines, worst, example = [], 1.0, None
for i in range(4):
    emb = [torch.from_numpy(np.fromfile(f"{SAMDEC}/inputs/img{i}_emb{k}.bin", np.float32).reshape(s)) for k, s in enumerate(shapes)]
    for j, b in enumerate(boxes):
        box = torch.from_numpy((np.array(b, np.float32) * 1024).reshape(1, 1, 4))
        with torch.no_grad():
            sparse, _ = m.prompt_encoder(input_points=None, input_labels=None, input_boxes=box, input_masks=None)
            sparse = sparse.reshape(1, -1, 256)
            masks, iou = net(emb[2], sparse, emb[1], emb[0])
        sparse.numpy().astype(np.float32).tofile(f"{OUT}/inputs/img{i}_box{j}_sparse.bin")
        ref = ref_masks[i * 2 + j]; got = masks.numpy()[0]
        ious = [((got[k] > 0) & (ref[k] > 0)).sum() / max(1, ((got[k] > 0) | (ref[k] > 0)).sum()) for k in range(3)]
        worst = min(worst, min(ious))
        if example is None: example = (emb[2], sparse, emb[1], emb[0])
        lines.append(",".join([f"/data/local/tmp/samdec/img{i}_emb2.bin", f"/data/local/tmp/boxdec/img{i}_box{j}_sparse.bin",
                               f"/data/local/tmp/samdec/img{i}_emb1.bin", f"/data/local/tmp/samdec/img{i}_emb0.bin"]))
print(f"stage 1 (eager re-authored vs original, 8 samples x 3 masks): worst mask IoU {worst:.6f}, sparse tokens {tuple(sparse.shape)}", flush=True)
open(f"{OUT}/inputs.txt", "w").write("\n".join(lines) + "\n")
edge = litert_torch.convert(net, example)
path = f"{OUT}/sam21t-box-decoder-gpuclean-fp32.tflite"
edge.export(path)
with torch.no_grad():
    em, ei = net(*example)
gm, gi = (np.asarray(t) for t in edge(*example))
c = float(gm.ravel() @ em.numpy().ravel() / (np.linalg.norm(gm) * np.linalg.norm(em.numpy())))
print(f"stage 2 (converted vs eager): masks cosine {c:.6f} max_abs {np.abs(gm - em.numpy()).max():.3g} | path {path}", flush=True)
