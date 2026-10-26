"""OWLv2 text tower (google/owlv2-base-patch16-ensemble) as its own graph:
token ids [32, 16] int32 -> text embeddings [32, 512], for the host's
vocabulary step. No attention mask input: CLIP's text transformer is causal
and pools at the EOS token, so padding after EOS can't affect the result
(checked in stage 1 against get_text_features with the mask).
Also writes the reference embeddings for a large vocabulary (YOLOE
prompt-free's 4,585 class names) and three device input batches.
Stage 1: wrapper vs original get_text_features; stage 2: converted vs eager."""
import sys, ast
import numpy as np
import onnx
import torch
import litert_torch
from transformers import Owlv2ForObjectDetection, Owlv2Processor
OUT = sys.argv[1]; YOLOE_ONNX = sys.argv[2]
REPO = "google/owlv2-base-patch16-ensemble"; REV = "cfd3195ba4ea9592eec887ded089f4c08eff231d"
model = Owlv2ForObjectDetection.from_pretrained(REPO, revision=REV).eval()
tok = Owlv2Processor.from_pretrained(REPO, revision=REV).tokenizer
B, L = 32, 16
meta = {p.key: p.value for p in onnx.load(YOLOE_ONNX, load_external_data=False).metadata_props}
names = [v for _, v in sorted(ast.literal_eval(meta["names"]).items())]
print("large vocabulary:", len(names), "names, e.g.", names[:5], flush=True)
VOCAB = ["a bed", "a pillow", "a lamp", "a wall sconce", "a suitcase", "a backpack", "a handbag", "a towel",
         "a chair", "a sofa", "a table", "a curtain", "a window", "a picture frame", "a mirror", "a television",
         "a person", "a dog", "a potted plant", "a rug", "a laptop", "a blanket", "a door", "a cabinet"]

class TextTower(torch.nn.Module):
    def __init__(self, m):
        super().__init__()
        self.text, self.proj = m.owlv2.text_model, m.owlv2.text_projection
    def forward(self, input_ids):
        h = self.text(input_ids=input_ids).last_hidden_state                   # causal; padding after EOS is inert
        eos = input_ids.argmax(dim=-1)                                         # EOS has the largest token id
        return self.proj(h[torch.arange(h.shape[0]), eos])

def ids(texts):
    t = tok(texts, padding="max_length", max_length=L, truncation=True, return_tensors="pt")
    return t["input_ids"].to(torch.int32), t["attention_mask"]

def reference(texts):
    out = []
    for k in range(0, len(texts), 256):
        i, m = ids(texts[k:k + 256])
        with torch.no_grad():
            e = model.owlv2.get_text_features(input_ids=i.long(), attention_mask=m)
        out.append((e.pooler_output if hasattr(e, "pooler_output") else e).numpy())
    return np.concatenate(out)

tower = TextTower(model).eval()
ref_large = reference(names); np.save(f"{OUT}/vocab_embeds.npy", ref_large)
open(f"{OUT}/vocab_names.txt", "w").write("\n".join(names) + "\n")
batches = [VOCAB + names[:8], names[1000:1032], names[3000:3032]]
lines, worst = [], []
for b, texts in enumerate(batches):
    i, _ = ids(texts)
    i.numpy().tofile(f"{OUT}/ids{b}.bin"); lines.append(f"/data/local/tmp/owlv2/text/ids{b}.bin")
    ref = reference(texts); np.save(f"{OUT}/ref{b}.npy", ref)
    with torch.no_grad():
        got = tower(i).numpy()
    worst.append(float(np.abs(got - ref).max()))
print("stage 1 (wrapper, no mask, vs get_text_features with mask): max abs diff per batch:", [f"{w:.1e}" for w in worst], flush=True)
open(f"{OUT}/inputs.txt", "w").write("\n".join(lines) + "\n")
i0, _ = ids(batches[0])
edge = litert_torch.convert(tower, (i0,))
path = f"{OUT}/owlv2-b16-text-tower-fp32.tflite"; edge.export(path)
with torch.no_grad():
    e = tower(i0).numpy()
g = np.asarray(edge(i0))
cos = (g * e).sum(-1) / (np.linalg.norm(g, axis=-1) * np.linalg.norm(e, axis=-1))
print(f"stage 2 converted vs eager: worst row cosine {cos.min():.6f}, max abs {np.abs(g - e).max():.3g}", flush=True)
print("path", path)
