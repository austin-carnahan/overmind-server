"""OWLv2 (google/owlv2-base-patch16-ensemble) image tower as its own graph,
vocabulary kept as data. The tower outputs, per patch: box logits, objectness,
normalized class embeddings, logit shift and scale; the host computes
logits = (class_embeds @ queries_normalized + shift) * scale for any
vocabulary, and boxes = sigmoid(box_logits + box_bias). Preparation:
position-embedding table fed as an input (large constant), class-token
broadcast_to rewritten as a broadcast multiply, and the [3600,4] box-bias add
moved to the host (on the Mali-G78 the GPU computed box_head + baked bias with
box_head broadcast from patch 0).
Stage 1: wrapper + host logits vs the original model's forward; stage 2:
converted vs eager."""
import sys, glob
import numpy as np
import torch
import litert_torch
from PIL import Image
from transformers import Owlv2ForObjectDetection, Owlv2Processor
from huggingface_hub import model_info
OUT = sys.argv[1]
REPO = "google/owlv2-base-patch16-ensemble"; REV = model_info(REPO).sha
print("model", REPO, "revision", REV, flush=True)
model = Owlv2ForObjectDetection.from_pretrained(REPO, revision=REV).eval()
proc = Owlv2Processor.from_pretrained(REPO, revision=REV)
VOCAB = ["a bed", "a pillow", "a lamp", "a wall sconce", "a suitcase", "a backpack", "a handbag", "a towel",
         "a chair", "a sofa", "a table", "a curtain", "a window", "a picture frame", "a mirror", "a television",
         "a person", "a dog", "a potted plant", "a rug", "a laptop", "a blanket", "a door", "a cabinet"]

class ImageTower(torch.nn.Module):
    def __init__(self, m):
        super().__init__()
        vm = m.owlv2.vision_model
        self.patch = vm.embeddings.patch_embedding
        self.cls = torch.nn.Parameter(vm.embeddings.class_embedding.detach().clone().reshape(1, 1, -1), requires_grad=False)
        self.pre, self.encoder, self.post = vm.pre_layernorm, vm.encoder, vm.post_layernorm
        self.ln, self.box_head, self.class_head, self.obj_head = m.layer_norm, m.box_head, m.class_head, m.objectness_head
        self.register_buffer("box_bias", m.box_bias.detach().clone())
    def forward(self, pixel_values, pos):                       # pos: [1, 3601, 768], fed as an input
        x = self.patch(pixel_values).flatten(2).transpose(1, 2)  # [1, 3600, 768]
        x = torch.cat([self.cls, x], dim=1) + pos
        x = self.encoder(inputs_embeds=self.pre(x)).last_hidden_state
        x = self.post(x)
        feats = self.ln(x[:, 1:, :] * x[:, :1, :])               # class-token merge as a broadcast multiply
        ce = self.class_head.dense0(feats)
        ce = ce / (torch.linalg.norm(ce, dim=-1, keepdim=True) + 1e-6)
        shift = self.class_head.logit_shift(feats)
        scale = torch.nn.functional.elu(self.class_head.logit_scale(feats)) + 1
        obj = self.obj_head(feats)
        return self.box_head(feats), obj, ce, shift, scale   # box logits; host adds box_bias

def host_boxes(box_logits, bias):
    return 1 / (1 + np.exp(-(box_logits + bias)))

def host_logits(ce, shift, scale, q):
    q = q / (np.linalg.norm(q, axis=-1, keepdims=True) + 1e-6)
    return (ce @ q.T + shift) * scale

tower = ImageTower(model).eval()
pos = model.owlv2.vision_model.embeddings.position_embedding.weight.detach().clone()[None]
BP = "/Users/dev/Code/browser-perception/demos"
imgs = sorted(glob.glob(f"{BP}/object-selection/samples/*.jpg"))[:5] + sorted(glob.glob(f"{BP}/segmentation/samples/*.jpg"))[:3]
text = proc(text=[VOCAB], return_tensors="pt")
with torch.no_grad():
    qemb = model.owlv2.get_text_features(input_ids=text["input_ids"], attention_mask=text["attention_mask"])
    qemb = (qemb.pooler_output if hasattr(qemb, "pooler_output") else qemb).numpy()
np.save(f"{OUT}/query_embeds.npy", qemb); np.save(f"{OUT}/box_bias.npy", tower.box_bias.numpy()); pos.numpy().astype(np.float32).tofile(f"{OUT}/inputs/pos.bin")
lines, worst = [], []
for i, p in enumerate(imgs):
    enc = proc(text=[VOCAB], images=Image.open(p).convert("RGB"), return_tensors="pt")
    px = enc["pixel_values"]; px.numpy().astype(np.float32).tofile(f"{OUT}/inputs/img{i}.bin")
    lines.append(f"/data/local/tmp/owlv2/img{i}.bin,/data/local/tmp/owlv2/pos.bin")
    with torch.no_grad():
        ref = model(**enc)
        bl, obj, ce, shift, scale = tower(px, pos)
    lg = host_logits(ce[0].numpy(), shift[0].numpy(), scale[0].numpy(), qemb)
    boxes = host_boxes(bl[0].numpy(), tower.box_bias.numpy())
    np.savez(f"{OUT}/ref{i}.npz", logits=ref.logits[0].numpy(), boxes=ref.pred_boxes[0].numpy(), objectness=ref.objectness_logits[0].numpy())
    worst.append((float(np.abs(lg - ref.logits[0].numpy()).max()), float(np.abs(boxes - ref.pred_boxes[0].numpy()).max()), float(np.abs(obj[0, :, 0].numpy() - ref.objectness_logits[0].numpy()).max())))
print("stage 1 (tower + host logits vs original forward): max abs diff logits / boxes / objectness per image:", [tuple(f"{v:.1e}" for v in w) for w in worst], flush=True)
open(f"{OUT}/inputs.txt", "w").write("\n".join(lines) + "\n")
px0 = torch.from_numpy(np.fromfile(f"{OUT}/inputs/img0.bin", np.float32).reshape(1, 3, 960, 960))
edge = litert_torch.convert(tower, (px0, pos))
path = f"{OUT}/owlv2-b16-image-tower-fp32.tflite"; edge.export(path)
with torch.no_grad():
    eager = [t.numpy() for t in tower(px0, pos)]
got = [np.asarray(t) for t in edge(px0, pos)]
for name, g, e in zip(("box_logits", "objectness", "class_embeds", "shift", "scale"), got, eager):
    c = float(g.ravel() @ e.ravel() / (np.linalg.norm(g) * np.linalg.norm(e)))
    print(f"stage 2 {name} {g.shape}: cosine {c:.6f} max abs {np.abs(g - e).max():.3g}", flush=True)
print("path", path)
