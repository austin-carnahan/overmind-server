"""RF-DETR-Seg-Nano evaluation: references from the original rfdetr 1.9.3
PyTorch model, graph A device inputs, and a desktop LiteRT CPU run of the
published two-graph pipeline judged at task level."""
import sys, glob, os
import numpy as np
import torch
from PIL import Image
from ai_edge_litert.interpreter import Interpreter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rfdetr_host import host_step, detections, compare, NP_, NQ, NC, H, M
P, OUT = sys.argv[1], sys.argv[2]
from rfdetr import RFDETRSegNano
core = RFDETRSegNano().model.model.eval()
BP = "/Users/dev/Code/browser-perception/demos"
imgs = sorted(glob.glob(f"{BP}/object-selection/samples/*.jpg"))[:5] + sorted(glob.glob(f"{BP}/segmentation/samples/*.jpg"))[:3]
mean = np.array([0.485, 0.456, 0.406], np.float32); std = np.array([0.229, 0.224, 0.225], np.float32)
consts = {n: np.fromfile(f"{P}/{n}.bin", np.float32) for n in ("clspos", "pospatch", "query_feat", "refpoint_embed")}
A = Interpreter(model_path=f"{P}/rfdetrseg_graphA_fp16.tflite"); A.allocate_tensors()
B = Interpreter(model_path=f"{P}/rfdetrseg_graphB_fp16.tflite"); B.allocate_tensors()
def size_of(d): return int(np.prod(d["shape"]))
print("graph A inputs", [(d["name"], list(d["shape"])) for d in sorted(A.get_input_details(), key=lambda d: d["index"])])
print("graph B inputs", [(d["name"], list(d["shape"])) for d in sorted(B.get_input_details(), key=lambda d: d["index"])])
refs, linesA = [], []
for i, p in enumerate(imgs):
    x = np.asarray(Image.open(p).convert("RGB").resize((312, 312), Image.BILINEAR), np.float32) / 255.0
    x = ((x - mean) / std).transpose(2, 0, 1)[None].astype(np.float32).copy()
    x.tofile(f"{OUT}/inputs/img{i}.bin")
    with torch.no_grad():
        o = core(torch.from_numpy(x))
    ref = (o["pred_logits"][0].numpy(), o["pred_boxes"][0].numpy(), o["pred_masks"][0].numpy())
    np.savez(f"{OUT}/ref{i}.npz", logits=ref[0], boxes=ref[1], masks=ref[2]); refs.append(ref)
    # desktop published pipeline
    feedA = {x.size: x, consts["clspos"].size: consts["clspos"], consts["pospatch"].size: consts["pospatch"]}
    for d in A.get_input_details(): A.set_tensor(d["index"], feedA[size_of(d)].reshape(d["shape"]))
    A.invoke()
    a = {size_of(d): A.get_tensor(d["index"]).ravel() for d in A.get_output_details()}
    mem, refp = host_step(a[NP_ * NC].reshape(NP_, NC), a[NP_ * 4].reshape(NP_, 4), a[NP_ * H].reshape(NP_, H), consts["refpoint_embed"].reshape(NQ, 4))
    feedB = {mem.size: mem, refp.size: refp, consts["query_feat"].size: consts["query_feat"]}
    for d in B.get_input_details(): B.set_tensor(d["index"], feedB[size_of(d)].reshape(d["shape"]))
    B.invoke()
    b = {size_of(d): B.get_tensor(d["index"]).ravel() for d in B.get_output_details()}
    got = (b[NQ * NC].reshape(NQ, NC), b[NQ * 4].reshape(NQ, 4), b[NQ * M * M].reshape(NQ, M, M))
    print(f"img{i} {os.path.basename(p)}: desktop published vs original:", compare(detections(*ref), detections(*got)), flush=True)
    order = {consts['clspos'].size: f"/data/local/tmp/rfdetr/clspos.bin", consts['pospatch'].size: f"/data/local/tmp/rfdetr/pospatch.bin", x.size: f"/data/local/tmp/rfdetr/img{i}.bin"}
    linesA.append(",".join(order[size_of(d)] for d in sorted(A.get_input_details(), key=lambda d: d["index"])))
open(f"{OUT}/inputsA.txt", "w").write("\n".join(linesA) + "\n")
