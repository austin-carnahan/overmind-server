"""Where a text prompt's time goes on the desktop CPU: text encoder, fusion
encoder, decoder, segmentation heads (torch.profiler record_function labels
the model already carries)."""
import sys, glob, time
import torch
from PIL import Image
REPO, CKPT = sys.argv[1], sys.argv[2]
sys.path.insert(0, f"{REPO}/sam3")
from sam3.model_builder import build_efficientsam3_image_model
from sam3.model.sam3_image_processor import Sam3Processor
torch.set_grad_enabled(False)
model = build_efficientsam3_image_model(checkpoint_path=CKPT, backbone_type="repvit", model_name="m1.1", text_encoder_type="MobileCLIP-S0",
                                        text_encoder_context_length=16, device="cpu", load_from_HF=False)
proc = Sam3Processor(model, device="cpu")
im = Image.open(sorted(glob.glob("/Users/dev/Code/browser-perception/demos/object-selection/samples/*.jpg"))[0]).convert("RGB")
st = proc.set_image(im); proc.set_text_prompt("chair", st)          # warm-up
t = time.perf_counter(); txt = model.backbone.forward_text(["lamp"], device="cpu"); print(f"text encoder: {1000 * (time.perf_counter() - t):.0f} ms")
with torch.profiler.profile(activities=[torch.profiler.ProfilerActivity.CPU]) as prof:
    proc.set_text_prompt("lamp", st)
for e in prof.key_averages():
    if e.key.startswith("SAM3Image.") or e.key.startswith("Sam3Processor") :
        print(f"{e.key:40} {e.cpu_time_total / 1000:8.0f} ms")
vf = st["backbone_out"]["backbone_fpn"]
print("cached image features:", [tuple(x.shape) for x in vf])
