"""EV-M (EfficientViT-B1) vision backbone only, for operator inspection."""
import sys
import torch
REPO, CKPT, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, f"{REPO}/sam3")
from sam3.model_builder import build_efficientsam3_image_model
import litert_torch
torch.set_grad_enabled(False)
m = build_efficientsam3_image_model(checkpoint_path=CKPT, backbone_type="efficientvit", model_name="b1", text_encoder_type="MobileCLIP-S0",
                                    text_encoder_context_length=16, device="cpu", load_from_HF=False).eval()
class Vision(torch.nn.Module):
    def __init__(s): super().__init__(); s.m = m
    def forward(s, px): return tuple(x.clone() for x in s.m.backbone.forward_image(px)["backbone_fpn"])
px = torch.randn(1, 3, 1008, 1008)
litert_torch.convert(Vision().eval(), (px,)).export(f"{OUT}/esam3-evm-vision-fp32.tflite"); print("ok")
