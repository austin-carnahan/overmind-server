"""GPU preparation of EfficientSAM3's grounding path (fusion encoder, decoder,
heads) for LiteRT on the Mali-G78 -- mathematically equivalent rewrites for the
fixed 1008x1008 input, batch 1 and text-only prompts, each removing an op the
GPU delegate rejected (device log, 2026-10-24):

1. Constants become inputs (lane rule 3): the decoder's layer-0 reference
   boxes, learned queries and presence token, and the geometry token's
   constant start (norm(final_proj(cls))). Ops with only constant inputs were
   rejected (SIGN, MEAN) or, worse, accepted and computed wrongly (layer 0's
   attention value projection of the 200x256 learned queries).
2. Sine-embedding frequencies precomputed (FLOOR_DIV/POW on constants).
3. Float padding mask (1 = padding) instead of bool: attention adds -1e4 to
   padded keys' logits (exp underflows to exactly 0 in fp32, as with -inf);
   masked mean pools use 1 - mask as weights of a [1, seq] @ [seq, d]
   matmul (GREATER/SELECT_V2/BROADCAST_TO/LOGICAL_NOT/CAST). Attention over
   a single key returns V directly (softmax over one key is exactly 1; the
   decomposed softmax was DIV(x, x)).
4. Box relative-position bias computed in 4-D (batch 1), not 5-D.
5. inverse_sigmoid without its [0, 1] clamp: its inputs are sigmoid outputs,
   so the clamp is the identity (RELU_0_TO_1).
6. Dot-product scores for the last decoder layer only -- the only layer the
   eval-mode outputs read -- as a 2-D matmul ([queries, d] @ [d, 1]). With
   all six layers, the scores came out wrong on the GPU although every input
   was exact; bisected to the reshape of [1200, 1] into [6, 1, 200, 1]
   (batch 6, one channel), not the matmul.
"""
import math, sys
import torch
import torch.nn.functional as F

NEG = -1e4
H = W = 72


def _patch_everywhere(name, fn):
    for mod in list(sys.modules.values()):
        if getattr(mod, "__name__", "").startswith("sam3") and hasattr(mod, name):
            setattr(mod, name, fn)


def inverse_sigmoid(x, eps=1e-3):
    return torch.log(x.clamp(min=eps) / (1 - x).clamp(min=eps))


def make_gen_sineembed(orig):
    cache = {}

    def gen_sineembed_for_position(pos_tensor, num_feats=256):
        n = num_feats // 2
        if n not in cache:
            dim_t = torch.arange(n, dtype=torch.float32)
            cache[n] = (10000 ** (2 * torch.div(dim_t, 2, rounding_mode="floor") / n)).clone()
        dim_t = cache[n]
        scale = 2 * math.pi
        x_embed, y_embed = pos_tensor[:, :, 0] * scale, pos_tensor[:, :, 1] * scale
        pos_x = torch.stack((( x_embed[:, :, None] / dim_t)[:, :, 0::2].sin(), (x_embed[:, :, None] / dim_t)[:, :, 1::2].cos()), dim=3).flatten(2)
        pos_y = torch.stack(((y_embed[:, :, None] / dim_t)[:, :, 0::2].sin(), (y_embed[:, :, None] / dim_t)[:, :, 1::2].cos()), dim=3).flatten(2)
        if pos_tensor.size(-1) == 2:
            return torch.cat((pos_y, pos_x), dim=2)
        w_embed, h_embed = pos_tensor[:, :, 2] * scale, pos_tensor[:, :, 3] * scale
        pos_w = torch.stack(((w_embed[:, :, None] / dim_t)[:, :, 0::2].sin(), (w_embed[:, :, None] / dim_t)[:, :, 1::2].cos()), dim=3).flatten(2)
        pos_h = torch.stack(((h_embed[:, :, None] / dim_t)[:, :, 0::2].sin(), (h_embed[:, :, None] / dim_t)[:, :, 1::2].cos()), dim=3).flatten(2)
        return torch.cat((pos_y, pos_x, pos_w, pos_h), dim=2)

    return gen_sineembed_for_position


def mha_forward(self, query, key, value, key_padding_mask=None, need_weights=False, attn_mask=None,
                average_attn_weights=True, is_causal=False):
    """nn.MultiheadAttention forward (no dropout, no bias_k/v) with a float
    key_padding_mask (1 = padding) applied as an additive logit bias."""
    assert self.bias_k is None and self.bias_v is None and not is_causal
    if self.batch_first:
        query, key, value = (x.transpose(0, 1) for x in (query, key, value))
    L, B, E = query.shape
    S = key.shape[0]
    nh = self.num_heads
    hd = E // nh
    if self._qkv_same_embed_dim:
        wq, wk, wv = self.in_proj_weight.chunk(3)
    else:
        wq, wk, wv = self.q_proj_weight, self.k_proj_weight, self.v_proj_weight
    bq, bk, bv = self.in_proj_bias.chunk(3) if self.in_proj_bias is not None else (None, None, None)
    v = F.linear(value, wv, bv).reshape(S, B * nh, hd).transpose(0, 1)          # [B*nh, S, hd]
    if S == 1 and L == 1:
        o = v                                                                    # softmax over one key == 1
    else:
        q = F.linear(query, wq, bq).reshape(L, B * nh, hd).transpose(0, 1)
        k = F.linear(key, wk, bk).reshape(S, B * nh, hd).transpose(0, 1)
        logits = torch.bmm(q, k.transpose(1, 2)) * (1.0 / math.sqrt(hd))       # [B*nh, L, S]
        if attn_mask is not None:
            assert attn_mask.dtype != torch.bool
            logits = logits + attn_mask
        if key_padding_mask is not None:
            assert key_padding_mask.dtype != torch.bool, "prepared model expects a float padding mask"
            logits = (logits.reshape(B, nh, L, S) + key_padding_mask.reshape(B, 1, 1, S) * NEG).reshape(B * nh, L, S)
        o = torch.bmm(torch.softmax(logits, dim=-1), v)
    o = o.transpose(0, 1).reshape(L, B, E)
    o = F.linear(o, self.out_proj.weight, self.out_proj.bias)
    if self.batch_first:
        o = o.transpose(0, 1)
    return o, None


def _masked_mean(prompt, prompt_mask):
    # prompt [seq, 1, d], prompt_mask [1, seq] (1 = padding)
    is_valid = 1.0 - prompt_mask                                               # [1, seq]
    pooled = torch.matmul(is_valid, prompt[:, 0, :])                           # [1, d]
    return pooled / torch.clamp(is_valid.sum(dim=-1, keepdim=True), min=1.0)


def pool_text_feat(prompt, prompt_mask, pool_with_mask):
    if not pool_with_mask:
        return prompt.mean(dim=0)
    return _masked_mean(prompt, prompt_mask)


def mean_pool_text(self, prompt, prompt_mask):
    return _masked_mean(prompt, prompt_mask)


def scoring_forward(self, hs, prompt, prompt_mask):
    """DotProductScoring.forward for the last decoder layer only (the only one
    the eval-mode outputs use), scores as a 2-D matmul."""
    if self.prompt_mlp is not None:
        prompt = self.prompt_mlp(prompt)
    proj_prompt = self.prompt_proj(self.mean_pool_text(prompt, prompt_mask))    # [1, d_proj]
    proj_hs = self.hs_proj(hs[-1:])                                             # [1, 1, nq, d_proj]
    scores = torch.matmul(proj_hs.reshape(-1, proj_hs.shape[-1]), proj_prompt.reshape(-1, 1))
    scores = scores.reshape(*proj_hs.shape[:-1], 1) * self.scale
    if self.clamp_logits:
        scores = scores.clamp(min=-self.clamp_max_val, max=self.clamp_max_val)
    return scores


class Prepared:
    """Applies the rewrites to a built model; holds the host-side constants."""

    def __init__(self, model):
        self.model = model
        dec, geo = model.transformer.decoder, model.geometry_encoder
        from sam3.model import model_misc, encoder, decoder as decmod
        from sam3.model.box_ops import box_cxcywh_to_xyxy
        self._xyxy = box_cxcywh_to_xyxy
        # host constants (written once per process on the device)
        with torch.no_grad():
            self.ref0 = dec.reference_points.weight.unsqueeze(1).sigmoid().clone()          # [200, 1, 4]
            cls = geo.cls_embed.weight.view(1, 1, geo.d_model)
            self.geo0 = geo.norm(geo.final_proj(cls)).clone()                                   # [1, 1, 256]
            self.query0 = dec.query_embed.weight.clone()                                        # [200, 256]
            self.presence0 = dec.presence_token.weight.clone()                                  # [1, 256]
        self.coords_h = torch.arange(H, dtype=torch.float32) / H
        self.coords_w = torch.arange(W, dtype=torch.float32) / W
        self.ref0_in = None   # set per forward: the graph inputs carrying the constants
        self.geo0_in = None
        self.query0_in = None
        self.presence0_in = None
        # 1: the decoder's learned queries and presence token are activations
        # of layer 0 (V = linear(constant) computed wrongly on the GPU), so
        # they come from inputs too
        prep_ = self

        class FromInput(torch.nn.Module):
            def __init__(s, attr): super().__init__(); s.attr = attr

            @property
            def weight(s): return getattr(prep_, s.attr)
        dec.query_embed = FromInput("query0_in")
        dec.presence_token = FromInput("presence0_in")
        # 1/3: attention, pools, inverse_sigmoid, sine embedding
        for m in model.modules():
            if isinstance(m, torch.nn.MultiheadAttention):
                m.forward = mha_forward.__get__(m)
        model.dot_prod_scoring.mean_pool_text = mean_pool_text.__get__(model.dot_prod_scoring)
        model.dot_prod_scoring.forward = scoring_forward.__get__(model.dot_prod_scoring)
        _patch_everywhere("pool_text_feat", pool_text_feat)
        _patch_everywhere("inverse_sigmoid", inverse_sigmoid)
        _patch_everywhere("gen_sineembed_for_position", make_gen_sineembed(model_misc.gen_sineembed_for_position))
        # 1: decoder reference boxes from an input; 4: RPB in 4-D
        orig_dec_forward = dec.forward
        prep = self

        def dec_forward(*a, **kw):
            if kw.get("reference_boxes") is None and prep.ref0_in is not None:
                kw["reference_boxes"] = prep.ref0_in
            return orig_dec_forward(*a, **kw)
        dec.forward = dec_forward
        dec._get_rpb_matrix = lambda reference_boxes, feat_size: self._rpb4d(dec, reference_boxes, feat_size)
        # 1: geometry encoder for the empty prompt, constant start from an input
        geo.forward = self._geo_forward

    def _rpb4d(self, dec, reference_boxes, feat_size):
        b = self._xyxy(reference_boxes)[:, 0, :]                                   # [nq, 4], batch 1
        nq = b.shape[0]
        dy = self.coords_h.view(1, -1, 1) - b[:, None, 1:4:2]                     # [nq, H, 2]
        dx = self.coords_w.view(1, -1, 1) - b[:, None, 0:3:2]                     # [nq, W, 2]
        if dec.boxRPB in ("log", "both"):
            lg = lambda d: torch.sign(d * 8) * torch.log2(torch.abs(d * 8) + 1.0) / math.log2(8)
            if dec.boxRPB == "log":
                dx, dy = lg(dx), lg(dy)
            else:
                dx, dy = torch.cat([dx, lg(dx)], -1), torch.cat([dy, lg(dy)], -1)
        ex, ey = dec.boxRPB_embed_x(dx), dec.boxRPB_embed_y(dy)                    # [nq, W, nh], [nq, H, nh]
        Bm = ey[:, :, None, :] + ex[:, None, :, :]                                 # [nq, H, W, nh]
        return Bm.reshape(nq, H * W, -1).permute(2, 0, 1).unsqueeze(0)            # [1, nh, nq, H*W]

    def _geo_forward(self, geo_prompt, img_feats, img_sizes, img_pos_embeds=None):
        geo = self.model.geometry_encoder
        assert geo_prompt.box_embeddings.shape[0] == 0, "text-only prompts"
        x = self.geo0_in
        mask = torch.zeros(1, 1)
        for lay in geo.encode:
            x = lay(tgt=x, memory=img_feats[-1], tgt_key_padding_mask=mask, pos=img_pos_embeds[-1])
        return geo.encode_norm(x), mask
