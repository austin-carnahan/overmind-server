"""Bisect the prepared grounding graph on the GPU: same graph plus
intermediate outputs captured with forward hooks (geometry token, fusion
encoder memory, each decoder layer's queries and presence token, pixel
decoder output). Writes the .tflite and the eager intermediates for sample 0.
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
def keep(name, pick):
    def hook(mod, inp, out): cap.append((name, pick(out).clone()))
    return hook
model.geometry_encoder_hook = None
enc = model.transformer.encoder; dec = model.transformer.decoder
enc.register_forward_hook(keep("encoder_memory", lambda o: o["memory"]))
for i, lay in enumerate(dec.layers):
    lay.register_forward_hook(keep(f"dec{i}_queries", lambda o: o[0]))
    lay.register_forward_hook(keep(f"dec{i}_presence", lambda o: o[1]))
# model.segmentation_head.pixel_decoder.register_forward_hook(keep("pixel_decoder", lambda o: o))

class Grounding(torch.nn.Module):
    def __init__(s): super().__init__(); s.m = model
    def forward(s, f0, f1, f2, pos, txt, pad, ref0, geo0):
        cap.clear()
        f0, f1, f2, pos, txt, pad = (x.clone() for x in (f0, f1, f2, pos, txt, pad))
        prep.ref0_in, prep.geo0_in = ref0, geo0
        bo = {"backbone_fpn": [f0, f1, f2], "vision_pos_enc": [pos, pos, pos], "language_features": txt, "language_mask": pad}
        geo, _ = model.geometry_encoder(geo_prompt=model._get_dummy_prompt(), img_feats=[f2.flatten(2).permute(2, 0, 1)], img_sizes=[(72, 72)],
                                        img_pos_embeds=[pos.flatten(2).permute(2, 0, 1)])
        o = s.m.forward_grounding(backbone_out=bo, find_input=proc.find_stage, geometric_prompt=s.m._get_dummy_prompt(), find_target=None)
        return (o["pred_logits"].clone(), geo.clone()) + tuple(t for _, t in cap)

G = Grounding().eval()
ld = lambda p, shape: torch.from_numpy(np.fromfile(p, np.float32).reshape(shape))
args = (ld(f"{DEV}/g0_f0.bin", (1, 256, 288, 288)), ld(f"{DEV}/g0_f1.bin", (1, 256, 144, 144)), ld(f"{DEV}/g0_f2.bin", (1, 256, 72, 72)),
        ld(f"{DEV}/pos.bin", (1, 256, 72, 72)), ld(f"{DEV}/g0_txt.bin", (16, 1, 256)), ld(f"{DEV}/g0_pad.bin", (1, 16)), prep.ref0, prep.geo0)
outs = G(*args); names = ["logits", "geo_token"] + [n for n, _ in cap]
np.savez(f"{OUT}/bisect_eager.npz", **{n: t.numpy() for n, t in zip(names, outs)})
open(f"{OUT}/bisect_names.txt", "w").write("\n".join(names) + "\n")
print(len(names), "outputs:", ", ".join(f"{n}{tuple(t.shape)}" for n, t in zip(names, outs)))
litert_torch.convert(G, args).export(f"{OUT}/esam3-rvm-grounding-bisect.tflite"); print("ok")
