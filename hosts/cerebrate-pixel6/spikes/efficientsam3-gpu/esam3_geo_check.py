import sys, glob
import torch
from PIL import Image
REPO, CKPT = sys.argv[1], sys.argv[2]
sys.path.insert(0, f"{REPO}/sam3")
from sam3.model_builder import build_efficientsam3_image_model
from sam3.model.sam3_image_processor import Sam3Processor
torch.set_grad_enabled(False)
m = build_efficientsam3_image_model(checkpoint_path=CKPT, backbone_type="repvit", model_name="m1.1", text_encoder_type="MobileCLIP-S0", text_encoder_context_length=16, device="cpu", load_from_HF=False).eval()
proc = Sam3Processor(m, device="cpu"); outs = []
for p in sorted(glob.glob("/Users/dev/Code/browser-perception/demos/object-selection/samples/*.jpg"))[:2]:
    bo = proc.set_image(Image.open(p).convert("RGB"))["backbone_out"]
    _, feats, pos, sizes = m._get_img_feats(bo, proc.find_stage.img_ids)
    g, gm = m.geometry_encoder(geo_prompt=m._get_dummy_prompt(), img_feats=feats, img_sizes=sizes, img_pos_embeds=pos); outs.append((g, gm))
print("geo feats", tuple(outs[0][0].shape), "mask", tuple(outs[0][1].shape), outs[0][1].dtype, outs[0][1].tolist(), "| max diff between two photos:", float((outs[0][0] - outs[1][0]).abs().max()))
