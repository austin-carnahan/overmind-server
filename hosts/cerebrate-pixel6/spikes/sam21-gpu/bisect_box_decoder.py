"""Bisect the G1 GPU defect in the GPU-clean box decoder: variants with the
large constants fed as inputs, and truncations after each stage. Sample 0
only; writes each variant's inputs and eager reference outputs as .bin."""
import sys, os
import numpy as np
import torch
import litert_torch
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "build_box_decoder.py")).read().split("m = Sam2Model.from_pretrained")[0]
sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2]]
exec(src)
from transformers import Sam2Model
SAMDEC, OUT = sys.argv[1], sys.argv[2]
m = Sam2Model.from_pretrained("facebook/sam2.1-hiera-tiny", revision="de431c4043854a71d8101e17995dfe596bf101a5").eval()

class Variant(BoxMaskDecoder):
    def __init__(self, model, stop):
        super().__init__(model); self.stop = stop
    def body(self, image_embeddings, sparse, feat_s1, feat_s0, dense, kpe, out_tokens):
        keys = (image_embeddings + dense).flatten(2).transpose(1, 2)[0]
        queries = torch.cat([out_tokens, sparse[0]], 0)
        qpe = queries
        q, k = self._block(self.layers[0], queries, keys, qpe, kpe, skip=True)
        if self.stop == "block0": return q, k
        q, k = self._block(self.layers[1], q, k, qpe, kpe, skip=False)
        if self.stop == "block1": return q, k
        q = q + self._attn(self.final_attn, q + qpe, k + kpe, k)
        q = self._ln(self.ln_final, q)
        if self.stop == "final": return q, k
        mask_toks = q[2:6]
        img = k.transpose(0, 1).reshape(1, 256, 64, 64)
        u = self.upscale_conv1(img) + feat_s1
        u = plain_ln(u.permute(0, 2, 3, 1), self.upscale_ln.weight, self.upscale_ln.bias, self.upscale_ln.eps).permute(0, 3, 1, 2)
        u = self.act(u)
        u = self.act(self.upscale_conv2(u) + feat_s0)
        if self.stop == "upscale": return (u,)
        hyper = torch.cat([self.mlps[j](mask_toks[j:j + 1]) for j in range(4)], 0)
        masks = (hyper @ u.reshape(32, 256 * 256)).reshape(4, 256, 256)[1:].unsqueeze(0)
        return masks, self.iou_head(q[1:2])[:, 1:]

class Baked(Variant):
    def forward(self, image_embeddings, sparse, feat_s1, feat_s0):
        return self.body(image_embeddings, sparse, feat_s1, feat_s0, self.dense, self.image_pos_flat, self.output_tokens)

class ConstIn(Variant):
    def forward(self, image_embeddings, sparse, feat_s1, feat_s0, dense, kpe, out_tokens):
        return self.body(image_embeddings, sparse, feat_s1, feat_s0, dense, kpe, out_tokens)

shapes = ((1, 32, 256, 256), (1, 64, 128, 128), (1, 256, 64, 64))
emb = [torch.from_numpy(np.fromfile(f"{SAMDEC}/inputs/img0_emb{k}.bin", np.float32).reshape(s)) for k, s in enumerate(shapes)]
box = torch.from_numpy((np.array([0.25, 0.35, 0.75, 0.95], np.float32) * 1024).reshape(1, 1, 4))
with torch.no_grad():
    sparse = m.prompt_encoder(input_points=None, input_labels=None, input_boxes=box, input_masks=None)[0].reshape(1, -1, 256)
variants = [("baked-block0", Baked(m, "block0")), ("baked-block1", Baked(m, "block1")), ("baked-final", Baked(m, "final")),
            ("baked-upscale", Baked(m, "upscale")), ("constin-full", ConstIn(m, "full")), ("constin-block0", ConstIn(m, "block0"))]
for name, net in variants:
    net.eval()
    args = [emb[2], sparse, emb[1], emb[0]]
    if isinstance(net, ConstIn):
        args += [net.dense.clone(), net.image_pos_flat.clone(), net.output_tokens.clone()]
    with torch.no_grad():
        ref = net(*args)
    d = f"{OUT}/{name}"; os.makedirs(d, exist_ok=True)
    for k, a in enumerate(args): a.numpy().astype(np.float32).tofile(f"{d}/in{k}.bin")
    for k, r in enumerate(ref): r.numpy().astype(np.float32).tofile(f"{d}/ref{k}.bin")
    open(f"{d}/inputs.txt", "w").write(",".join(f"/data/local/tmp/boxbisect/{name}/in{k}.bin" for k in range(len(args))) + "\n")
    litert_torch.convert(net, tuple(args)).export(f"{d}/model.tflite")
    print("built", name, "inputs", len(args), "outputs", [tuple(r.shape) for r in ref], flush=True)
