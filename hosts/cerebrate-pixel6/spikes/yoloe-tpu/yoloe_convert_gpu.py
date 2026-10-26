"""YOLOE prompt-free (v8s, 11s) as float LiteRT graphs for the Pixel GPU.
Wrapper over the fused Ultralytics model in export mode with the head's
_inference returning (decoded boxes, sigmoid class scores, mask coefficients)
separately instead of concatenating them (no 155 MB output0), then the best
score and class per anchor -- the same outputs as the reduced ONNX
(yoloe_prep.py), with the class index as float (GPU: float I/O).
Stage 1: wrapper vs the reduced-ONNX references; stage 2: converted vs eager.
usage: <dl-yoloe dir> <yoloe dir (inputs, refs)> <out dir>"""
import sys
import numpy as np, torch
import litert_torch
from ultralytics import YOLOE
D, Y, OUT = sys.argv[1:4]
torch.set_grad_enabled(False)

class Reduced(torch.nn.Module):
    def __init__(s, dm):
        super().__init__(); s.m = dm
    def forward(s, x):
        (boxes, scores, coef), protos = s.m(x)
        score, cls = scores.max(1)
        return boxes, score, cls.float(), coef, protos

for v in ("yoloe-v8s-seg-pf", "yoloe-11s-seg-pf"):
    dm = YOLOE(f"{D}/{v}.pt").model.fuse().eval()
    head = dm.model[-1]
    head.export = True; head.dynamic = False; head.format = "litert"
    assert not getattr(head, "end2end", False)
    head._inference = lambda x, h=head: (h._get_decode_boxes(x), x["scores"].sigmoid(), x["mask_coefficient"])
    R = Reduced(dm).eval()
    worst = []
    for i in range(8):
        x = torch.from_numpy(np.load(f"{Y}/in{i}.npz")["images"])
        r = np.load(f"{Y}/{v}-ref{i}.npz"); o = [t.numpy() for t in R(x)]
        worst.append((np.abs(o[0] - r["boxes"]).max(), np.abs(o[1] - r["score"]).max(), (o[2] != r["cls"]).sum(), np.abs(o[3] - r["coef"]).max(), np.abs(o[4] - r["output1"]).max()))
    w = np.max(np.array(worst, dtype=float), axis=0)
    print(f"{v} stage 1 (wrapper vs reduced ONNX, 8 photos): boxes {w[0]:.1e}, score {w[1]:.1e}, cls differs on up to {int(w[2])} anchors, coef {w[3]:.1e}, protos {w[4]:.1e}", flush=True)
    x0 = torch.from_numpy(np.load(f"{Y}/in0.npz")["images"])
    edge = litert_torch.convert(R, (x0,)); path = f"{OUT}/{v}-fp32.tflite"; edge.export(path)
    got = edge(x0); eag = R(x0)
    for n, a, b in zip(("boxes", "score", "cls", "coef", "protos"), got, eag):
        a = np.asarray(a, np.float32).ravel(); b = b.numpy().ravel()
        print(f"  stage 2 {n}: cosine {a @ b / (np.linalg.norm(a) * np.linalg.norm(b)):.6f} max abs {np.abs(a - b).max():.3g}", flush=True)
    print("  ", path, flush=True)
