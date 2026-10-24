"""EfficientSAM3 RV-M (fine-tuned full model) as three LiteRT graphs, FP32:
vision (pixels -> FPN levels), text (token ids -> token features), grounding
(FPN levels + text -> logits, boxes, presence, masks for all 200 queries).
Host: tokenizer, padding mask (ids == 0), the constant 72x72 positional
encoding (fed as an input: large constant), score/threshold post-processing.
Stage 1: wrappers vs the original Sam3Processor path on photo 0, prompt
"laptop"; stage 2: converted vs eager.  usage: <repo> <ckpt> <out> [vision,text,grounding]"""
import sys, glob, time
import numpy as np, torch
from PIL import Image
REPO, CKPT, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
WHICH = (sys.argv[4] if len(sys.argv) > 4 else "vision,text,grounding").split(",")
sys.path.insert(0, f"{REPO}/sam3")
from sam3.model_builder import build_efficientsam3_image_model
from sam3.model.sam3_image_processor import Sam3Processor
import litert_torch
torch.set_grad_enabled(False)
model = build_efficientsam3_image_model(checkpoint_path=CKPT, backbone_type="repvit", model_name="m1.1", text_encoder_type="MobileCLIP-S0",
                                        text_encoder_context_length=16, device="cpu", load_from_HF=False).eval()
proc = Sam3Processor(model, device="cpu", confidence_threshold=0.0)
lang = model.backbone.language_backbone
# Export preparation (exact for the fixed 1008x1008 input): the decoder's box
# relative-position bias receives the 72x72 feature size as tensors from the
# encoder and branches on them; pin it to Python ints.
_rpb = model.transformer.decoder._get_rpb_matrix
model.transformer.decoder._get_rpb_matrix = lambda reference_boxes, feat_size: _rpb(reference_boxes, (72, 72))

class Vision(torch.nn.Module):
    def __init__(s): super().__init__(); s.m = model
    def forward(s, px):
        o = s.m.backbone.forward_image(px)
        return tuple(o["backbone_fpn"])

class Text(torch.nn.Module):
    def __init__(s): super().__init__(); s.enc, s.proj = lang.encoder, lang.projector
    def forward(s, ids):
        e = s.enc.forward_embedding(ids)
        return s.proj(s.enc(e, return_all_tokens=True, input_is_embeddings=True)).transpose(0, 1)

class Grounding(torch.nn.Module):
    def __init__(s): super().__init__(); s.m = model
    def forward(s, f0, f1, f2, pos, txt, pad):      # pad: [1,16] float, 1 = padding token
        f0, f1, f2, pos, txt = (x.clone() for x in (f0, f1, f2, pos, txt))   # export: no aliasing of inputs
        bo = {"backbone_fpn": [f0, f1, f2], "vision_pos_enc": [pos, pos, pos],
              "language_features": txt, "language_mask": pad > 0.5}
        o = s.m.forward_grounding(backbone_out=bo, find_input=proc.find_stage, geometric_prompt=s.m._get_dummy_prompt(), find_target=None)
        return tuple(o[k].clone() for k in ("pred_logits", "pred_boxes", "presence_logit_dec", "pred_masks"))

def ids_of(q): return lang.tokenizer([q], context_length=16).to(torch.int32)

# Reference: the original processor path
img = Image.open(sorted(glob.glob("/Users/dev/Code/browser-perception/demos/object-selection/samples/*.jpg"))[0]).convert("RGB")
st = proc.set_image(img); bo = st["backbone_out"]
txt_ref = model.backbone.forward_text(["laptop"], device="cpu")
ref = model.forward_grounding(backbone_out={**bo, **txt_ref}, find_input=proc.find_stage, geometric_prompt=model._get_dummy_prompt(), find_target=None)
ref = [ref[k] for k in ("pred_logits", "pred_boxes", "presence_logit_dec", "pred_masks")]
# The exact pixel tensor set_image fed the backbone
from torchvision.transforms import v2
px = proc.transform(v2.functional.to_image(img)).unsqueeze(0)
pos = bo["vision_pos_enc"][-1]
ids = ids_of("laptop"); pad = (ids == 0).float()
V, T, G = Vision().eval(), Text().eval(), Grounding().eval()
fp = V(px) if px is not None else tuple(bo["backbone_fpn"])
d = lambda a, b: float((a - b).abs().max())
print("stage 1: vision vs set_image FPN:", [f"{d(a, b):.1e}" for a, b in zip(fp, bo["backbone_fpn"])] if px is not None else "no transform found",
      "| text vs forward_text:", f"{d(T(ids), txt_ref['language_features']):.1e}", "| mask same:", bool(((pad > 0.5) == txt_ref["language_mask"]).all()), flush=True)
g = G(*bo["backbone_fpn"], pos, txt_ref["language_features"], pad)
print("stage 1: grounding vs forward_grounding:", [f"{d(a, b):.1e}" for a, b in zip(g, ref)], flush=True)
np.save(f"{OUT}/pos.npy", pos.numpy())

def stage2(name, mod, args, ref_out):
    t = time.perf_counter(); edge = litert_torch.convert(mod, args); path = f"{OUT}/esam3-rvm-{name}-fp32.tflite"; edge.export(path)
    got = edge(*args); got = got if isinstance(got, (list, tuple)) else [got]
    ref_out = ref_out if isinstance(ref_out, (list, tuple)) else [ref_out]
    for k, (a, b) in enumerate(zip(got, ref_out)):
        a = np.asarray(a, np.float32).ravel(); b = b.numpy().astype(np.float32).ravel()
        c = float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))
        print(f"stage 2 {name} out{k} {tuple(ref_out[k].shape)}: cosine {c:.6f} max abs {np.abs(a - b).max():.3g}", flush=True)
    print(f"  {path} ({time.perf_counter() - t:.0f} s)", flush=True)

if "vision" in WHICH and px is not None: stage2("vision", V, (px,), V(px))
if "text" in WHICH: stage2("text", T, (ids,), T(ids))
if "grounding" in WHICH:
    gargs = (*bo["backbone_fpn"], pos, txt_ref["language_features"], pad)
    stage2("grounding", G, gargs, G(*gargs))
