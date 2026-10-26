"""Is the fusion encoder's first self-attention prompt-independent?
(1) Original model, one photo, three prompts: layer 0's state after norm1 +
self-attention + residual (the cacheable candidate) must be bit-identical
across prompts; layer 0's full output (after cross-attention to the prompt)
must differ (control). (2) Exports that block alone -- prepared exactly as in
the grounding graph -- for timing on the device, with its input.
usage: <repo> <ckpt> <dev dir> <out dir>"""
import sys, glob
import numpy as np, torch
from PIL import Image
REPO, CKPT, DEV, OUT = sys.argv[1:5]
sys.path.insert(0, f"{REPO}/sam3")
from sam3.model_builder import build_efficientsam3_image_model
from sam3.model.sam3_image_processor import Sam3Processor
torch.set_grad_enabled(False)
model = build_efficientsam3_image_model(checkpoint_path=CKPT, backbone_type="repvit", model_name="m1.1", text_encoder_type="MobileCLIP-S0",
                                        text_encoder_context_length=16, device="cpu", load_from_HF=False).eval()
proc = Sam3Processor(model, device="cpu")
l0 = model.transformer.encoder.layers[0]
cap = {}
l0.register_forward_pre_hook(lambda m, a, kw: cap.update(tgt=kw["tgt"].clone(), pos=kw["query_pos"].clone()), with_kwargs=True)
l0.self_attn.register_forward_hook(lambda m, i, o: cap.update(sa=o[0].clone()))
l0.register_forward_hook(lambda m, i, o: cap.update(out=o.clone()))
img = Image.open(sorted(glob.glob("/Users/dev/Code/browser-perception/demos/object-selection/samples/*.jpg"))[0]).convert("RGB")
st = proc.set_image(img); runs = {}
for q in ("laptop", "bed", "person"):
    proc.set_text_prompt(q, st); runs[q] = {k: v.clone() for k, v in cap.items()}
after = {q: r["tgt"] + r["sa"] for q, r in runs.items()}          # residual after self-attention
base = "laptop"
for q in ("bed", "person"):
    print(f"'{base}' vs '{q}': layer-0 input max diff {float((runs[q]['tgt'] - runs[base]['tgt']).abs().max()):.1e}, "
          f"after self-attention {float((after[q] - after[base]).abs().max()):.1e} (bit-identical: {torch.equal(after[q], after[base])}), "
          f"layer-0 output (after cross-attention) {float((runs[q]['out'] - runs[base]['out']).abs().max()):.2e}")

# (2) the cacheable block alone, prepared like the grounding graph, for device timing
from esam3_prepare import Prepared
import litert_torch
Prepared(model)
class Block(torch.nn.Module):
    def __init__(s): super().__init__(); s.l = l0
    def forward(s, tgt, pos):
        t2 = s.l.norm1(tgt)
        return tgt + s.l.self_attn(t2 + pos, t2 + pos, value=t2)[0]
B = Block().eval(); tgt, pos = runs[base]["tgt"], runs[base]["pos"]
ref = after[base]; got = B(tgt, pos)
print(f"prepared block vs original: max abs {float((got - ref).abs().max()):.1e}; shapes tgt {tuple(tgt.shape)} pos {tuple(pos.shape)}")
tgt.numpy().tofile(f"{DEV}/c_tgt.bin"); pos.numpy().tofile(f"{DEV}/c_pos.bin"); np.save(f"{DEV}/c_ref.npy", ref.numpy())
open(f"{DEV}/cache.txt", "w").write("/data/local/tmp/esam3/c_tgt.bin,/data/local/tmp/esam3/c_pos.bin\n")
litert_torch.convert(B, (tgt, pos)).export(f"{OUT}/esam3-rvm-enc-l0-selfattn-fp32.tflite"); print("ok")
