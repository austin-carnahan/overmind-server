"""YOLOE-v8s head alone for the GPU, fed by the TPU backbone's NHWC feature
maps. litert-torch conversion of the original (fused) Ultralytics head in
export mode, with the class selection done on the logits by a native argmax
(int32 indices -- exact at any precision mode, unlike onnx2tf's int64 ARG_MAX,
which the GPU rejects, or its float-index replacement, which overflows at
fp16) and the sigmoid applied to the winning logit only (sigmoid is
monotonic: same score, same class, 1/4585 of the sigmoids). Outputs: boxes
[1,4,8400], score [1,8400], cls [1,8400] (float), coef [1,32,8400], protos
[1,32,160,160]. Stage 1: vs the validated fp32 head ONNX on the same
features; stage 2: converted vs eager.  usage: <dl-yoloe> <yoloe dir> <out dir>"""
import sys
import numpy as np, torch, onnxruntime as ort
import litert_torch
from ultralytics import YOLOE
D, Y, OUT = sys.argv[1:4]; v = "yoloe-v8s-seg-pf"
torch.set_grad_enabled(False)
dm = YOLOE(f"{D}/{v}.pt").model.fuse().eval(); head = dm.model[-1]
head.export = True; head.dynamic = False; head.format = "litert"
head._inference = lambda x, h=head: (h._get_decode_boxes(x), x["scores"], x["mask_coefficient"])   # logits, not sigmoid

class Head(torch.nn.Module):
    def __init__(s): super().__init__(); s.h = head
    def forward(s, p3, p4, p5):                                    # NHWC, as the TPU backbone emits them
        (boxes, logits, coef), protos = s.h([t.permute(0, 3, 1, 2) for t in (p3, p4, p5)])
        lmax, idx = logits.max(1)
        return boxes, torch.sigmoid(lmax), idx.float(), coef, protos

H = Head().eval()
B = ort.InferenceSession(f"{Y}/{v}-backbone.onnx"); hon = ort.InferenceSession(f"{Y}/{v}-head.onnx")
x = np.load(f"{Y}/in0.npz")["images"]; feats = dict(zip([o.name for o in B.get_outputs()], B.run(None, {"images": x})))
order = sorted(feats, key=lambda n: -feats[n].shape[2])            # 80, 40, 20
args = tuple(torch.from_numpy(feats[n].transpose(0, 2, 3, 1).copy()) for n in order)
ref = dict(zip([o.name for o in hon.get_outputs()], hon.run(None, {i.name: feats[i.name] for i in hon.get_inputs()})))
got = [t.numpy() for t in H(*args)]
print(f"stage 1 (vs fp32 head ONNX): boxes {np.abs(got[0] - ref['boxes']).max():.1e}, score {np.abs(got[1] - ref['score']).max():.1e}, "
      f"cls differs on {(got[2] != ref['cls']).sum()} of 8400 anchors (on scored >= 0.25: {((got[2] != ref['cls']) & (ref['score'] >= 0.25)).sum()}), "
      f"coef {np.abs(got[3] - ref['coef']).max():.1e}, protos {np.abs(got[4] - ref['output1']).max():.1e}", flush=True)
edge = litert_torch.convert(H, args); path = f"{OUT}/{v}-head-gpu.tflite"; edge.export(path)
for n, a, b in zip(("boxes", "score", "cls", "coef", "protos"), edge(*args), H(*args)):
    a = np.asarray(a, np.float32).ravel(); b = b.numpy().ravel()
    print(f"  stage 2 {n}: cosine {a @ b / (np.linalg.norm(a) * np.linalg.norm(b)):.6f} max abs {np.abs(a - b).max():.3g}", flush=True)
from ai_edge_litert.interpreter import Interpreter
it = Interpreter(model_path=path); print("  inputs", [list(d["shape"]) for d in it.get_input_details()], "| ops:", len(it._get_ops_details()),
                                        "| ARG_MAX out dtype:", [it.get_tensor_details()[o["outputs"][0]]["dtype"].__name__ for o in it._get_ops_details() if o["op_name"] == "ARG_MAX"])
print(" ", path)
