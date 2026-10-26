"""Setup sanity probe: raw per-query scores (logit sigmoid, presence) for a few
prompts, and the text tokens actually fed (context 16)."""
import sys, glob
import numpy as np, torch
from PIL import Image
REPO, CKPT = sys.argv[1], sys.argv[2]
sys.path.insert(0, f"{REPO}/sam3")
from sam3.model_builder import build_efficientsam3_image_model
from sam3.model.sam3_image_processor import Sam3Processor
model = build_efficientsam3_image_model(checkpoint_path=CKPT, backbone_type="repvit", model_name="m1.1", text_encoder_type="MobileCLIP-S0",
                                        text_encoder_context_length=16, device="cpu", load_from_HF=False)
proc = Sam3Processor(model, device="cpu", confidence_threshold=0.0)
BP = "/Users/dev/Code/browser-perception/demos"
imgs = sorted(glob.glob(f"{BP}/object-selection/samples/*.jpg"))[:5] + sorted(glob.glob(f"{BP}/segmentation/samples/*.jpg"))[:3]
for i, prompts in ((5, ["dog", "puppy", "person", "a dog", "cat"]), (0, ["backpack", "suitcase", "person", "laptop", "giraffe"])):
    torch.set_grad_enabled(False); st = proc.set_image(Image.open(imgs[i]).convert("RGB"))
    for q in prompts:
        out = model.forward_grounding(backbone_out={**st["backbone_out"], **model.backbone.forward_text([q], device="cpu")},
                                      find_input=proc.find_stage, geometric_prompt=model._get_dummy_prompt(), find_target=None)
        pr = out["pred_logits"].sigmoid()[0, :, 0]; pres = out["presence_logit_dec"].sigmoid().item()
        top = torch.topk(pr, 3).values.numpy()
        print(f"photo {i} '{q}': presence {pres:.3f}  top query probs {np.round(top, 3)}  -> top final {np.round(top * pres, 3)}")
tok = model.backbone.language_backbone
print(type(tok).__name__, [a for a in dir(tok) if "context" in a.lower()][:5])
