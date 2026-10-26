"""Bisect step 4 (inside the 2-D-matmul scoring): the dot-product scoring head of the prepared grounding graph
(detection outputs only). Captures the prompt MLP output, pooled prompt,
projected prompt, projected queries, and raw scores for sample 0.
usage: <repo> <ckpt> <dev dir> <out dir>"""
import sys
import numpy as np, torch
REPO, CKPT, DEV, OUT = sys.argv[1:5]
sys.path.insert(0, f"{REPO}/sam3")
from sam3.model_builder import build_efficientsam3_image_model
from sam3.model.sam3_image_processor import Sam3Processor
from esam3_prepare import Prepared
import litert_torch
torch.set_grad_enabled(False)
model = build_efficientsam3_image_model(checkpoint_path=CKPT, backbone_type="repvit", model_name="m1.1", text_encoder_type="MobileCLIP-S0",
                                        text_encoder_context_length=16, device="cpu", load_from_HF=False).eval()
proc = Sam3Processor(model, device="cpu"); prep = Prepared(model)
cap = []
def keep(name):
    def hook(mod, inp, out): cap.append((name, out.clone()))
    return hook
sc = model.dot_prod_scoring
def scoring_forward(hs, prompt, prompt_mask):
    if sc.prompt_mlp is not None: prompt = sc.prompt_mlp(prompt)
    pp = sc.prompt_proj(sc.mean_pool_text(prompt, prompt_mask)); cap.append(("proj_prompt", pp.clone()))
    ph = sc.hs_proj(hs); cap.append(("proj_hs", ph.clone()))
    raw = torch.matmul(ph.reshape(-1, ph.shape[-1]), pp.reshape(-1, 1)); cap.append(("matmul_raw", raw.clone()))
    sc_ = raw.reshape(*ph.shape[:-1], 1) * sc.scale; cap.append(("scaled", sc_.clone()))
    out = sc_.clamp(min=-sc.clamp_max_val, max=sc.clamp_max_val); cap.append(("clamped", out.clone()))
    return out
sc.forward = scoring_forward

class Grounding(torch.nn.Module):
    def __init__(s): super().__init__(); s.m = model
    def forward(s, f0, f1, f2, pos, txt, pad, ref0, geo0, query0, presence0):
        cap.clear()
        f0, f1, f2, pos, txt, pad = (x.clone() for x in (f0, f1, f2, pos, txt, pad))
        prep.ref0_in, prep.geo0_in, prep.query0_in, prep.presence0_in = ref0, geo0, query0, presence0
        bo = {"backbone_fpn": [f0, f1, f2], "vision_pos_enc": [pos, pos, pos], "language_features": txt, "language_mask": pad}
        o = s.m.forward_grounding(backbone_out=bo, find_input=proc.find_stage, geometric_prompt=s.m._get_dummy_prompt(), find_target=None)
        return (o["pred_logits"].clone(),) + tuple(t for _, t in cap)

G = Grounding().eval()
ld = lambda p, shape: torch.from_numpy(np.fromfile(p, np.float32).reshape(shape))
args = (ld(f"{DEV}/g0_f0.bin", (1, 256, 288, 288)), ld(f"{DEV}/g0_f1.bin", (1, 256, 144, 144)), ld(f"{DEV}/g0_f2.bin", (1, 256, 72, 72)),
        ld(f"{DEV}/pos.bin", (1, 256, 72, 72)), ld(f"{DEV}/g0_txt.bin", (16, 1, 256)), ld(f"{DEV}/g0_pad.bin", (1, 16)),
        prep.ref0, prep.geo0, prep.query0, prep.presence0)
outs = G(*args); names = ["logits"] + [n for n, _ in cap]
np.savez(f"{OUT}/bisect4_eager.npz", **{n: t.numpy() for n, t in zip(names, outs)})
open(f"{OUT}/bisect4_names.txt", "w").write("\n".join(names) + "\n")
print(len(names), "outputs:", ", ".join(f"{n}{tuple(t.shape)}" for n, t in zip(names, outs)))
litert_torch.convert(G, args).export(f"{OUT}/esam3-rvm-grounding-bisect4.tflite"); print("ok")
