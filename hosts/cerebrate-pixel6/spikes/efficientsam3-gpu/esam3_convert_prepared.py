"""Prepared EfficientSAM3 RV-M grounding graph (esam3_prepare.py rewrites).
Inputs: FPN levels, positional encoding, text features, float padding mask,
plus four host constants -- layer-0 reference boxes [200,1,4], learned
queries [200,256], presence token [1,256], and the geometry token start
[1,1,256]. Stage 1: prepared eager vs the original model's outputs
for the three device samples (gref*.npz, from the unmodified path); stage 2:
converted vs eager.  usage: <repo> <ckpt> <dev dir> <out dir>"""
import sys
import numpy as np, torch
REPO, CKPT, DEV, OUT = sys.argv[1:5]
VARIANT = sys.argv[5] if len(sys.argv) > 5 else "full"   # "nomask": detection outputs only (prunes the mask head); "encoder": fusion encoder memory only (profiling)
sys.path.insert(0, f"{REPO}/sam3")
from sam3.model_builder import build_efficientsam3_image_model
from sam3.model.sam3_image_processor import Sam3Processor
from esam3_prepare import Prepared
import litert_torch
torch.set_grad_enabled(False)
model = build_efficientsam3_image_model(checkpoint_path=CKPT, backbone_type="repvit", model_name="m1.1", text_encoder_type="MobileCLIP-S0",
                                        text_encoder_context_length=16, device="cpu", load_from_HF=False).eval()
proc = Sam3Processor(model, device="cpu")
prep = Prepared(model)
for n in ("ref0", "geo0", "query0", "presence0"): getattr(prep, n).numpy().tofile(f"{DEV}/{n}.bin")

class Grounding(torch.nn.Module):
    def __init__(s): super().__init__(); s.m = model
    def forward(s, f0, f1, f2, pos, txt, pad, ref0, geo0, query0, presence0):
        f0, f1, f2, pos, txt, pad = (x.clone() for x in (f0, f1, f2, pos, txt, pad))
        prep.ref0_in, prep.geo0_in, prep.query0_in, prep.presence0_in = ref0, geo0, query0, presence0
        bo = {"backbone_fpn": [f0, f1, f2], "vision_pos_enc": [pos, pos, pos], "language_features": txt, "language_mask": pad}
        if VARIANT == "encoder":
            prompt, prompt_mask, bo = s.m._encode_prompt(bo, proc.find_stage, s.m._get_dummy_prompt())
            _, enc, _ = s.m._run_encoder(bo, proc.find_stage, prompt, prompt_mask)
            return (enc["encoder_hidden_states"].clone(),)
        o = s.m.forward_grounding(backbone_out=bo, find_input=proc.find_stage, geometric_prompt=s.m._get_dummy_prompt(), find_target=None)
        keys = ("pred_logits", "pred_boxes", "presence_logit_dec") + (("pred_masks",) if VARIANT == "full" else ())
        return tuple(o[k].clone() for k in keys)

G = Grounding().eval()
ld = lambda p, shape: torch.from_numpy(np.fromfile(p, np.float32).reshape(shape))
def sample(s):
    return (ld(f"{DEV}/g{s}_f0.bin", (1, 256, 288, 288)), ld(f"{DEV}/g{s}_f1.bin", (1, 256, 144, 144)), ld(f"{DEV}/g{s}_f2.bin", (1, 256, 72, 72)),
            ld(f"{DEV}/pos.bin", (1, 256, 72, 72)), ld(f"{DEV}/g{s}_txt.bin", (16, 1, 256)), ld(f"{DEV}/g{s}_pad.bin", (1, 16)), prep.ref0, prep.geo0, prep.query0, prep.presence0)
names = ("logits", "boxes", "presence", "masks")
for s in range(3 if VARIANT != "encoder" else 0):
    r = np.load(f"{DEV}/gref{s}.npz"); g = G(*sample(s))
    print(f"stage 1 sample {s} ({r['prompt']}): max abs diff " + ", ".join(f"{n} {np.abs(x.numpy() - r[n]).max():.1e}" for n, x in zip(names, g)), flush=True)
args = sample(0)
edge = litert_torch.convert(G, args); path = f"{OUT}/esam3-rvm-grounding-prepared{'' if VARIANT == 'full' else '-' + VARIANT}-fp32.tflite"; edge.export(path)
eager = G(*args); got = edge(*args)
got = got if isinstance(got, (list, tuple)) else [got]
for n, a, b in zip(names if VARIANT != "encoder" else ("memory",), got, eager):
    a = np.asarray(a, np.float32).ravel(); b = b.numpy().ravel()
    print(f"stage 2 {n}: cosine {a @ b / (np.linalg.norm(a) * np.linalg.norm(b)):.6f} max abs {np.abs(a - b).max():.3g}", flush=True)
print("path", path)
