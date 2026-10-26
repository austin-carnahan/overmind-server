"""OWLv2 photo path on the device: the adapter hook (scipy-free port of
Owlv2ImageProcessorPil, stdlib CLIP tokenizer, image and text tower calls,
host step) around a graph-mode worker, on the validation set: 8 photos x 24
text queries, judged as spikes/owlv2-gpu/owlv2_accuracy.py does against the
original Owlv2ForObjectDetection (score >= 0.2, per-query NMS 0.3, matched by
query and box IoU >= 0.5). usage: owlv2_photo_check.py <host> <port> <photos dir> <refs dir (ref<i>.npz)>"""
import sys, socket, json, asyncio
import numpy as np
sys.path.insert(0, "/home/droid/cg-test/stage/code/cerebrate-graph")
import cerebrate_graph_protocol as protocol
import cerebrate_graph_photo as cgp
from mlserver.types import RequestInput

HOST, PORT, PH, R = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
VOCAB = ["a bed", "a pillow", "a lamp", "a wall sconce", "a suitcase", "a backpack", "a handbag", "a towel",
         "a chair", "a sofa", "a table", "a curtain", "a window", "a picture frame", "a mirror", "a television",
         "a person", "a dog", "a potted plant", "a rug", "a laptop", "a blanket", "a door", "a cabinet"]
TH, P = 0.2, 3600


class Params:
    def __init__(self, **kw): self.__dict__.update(kw)


h = cgp.HOOKS["owlv2"]()
def detections(lg, boxes):
    s = 1 / (1 + np.exp(-lg)); out = []
    for q in range(lg.shape[1]):
        idx = np.where(s[:, q] >= TH)[0]; idx = idx[np.argsort(-s[idx, q])]; keep = []
        while len(idx):
            keep.append(idx[0]); idx = idx[1:][h._iou(boxes[idx[:1]], boxes[idx[1:]])[0] < 0.3] if len(idx) > 1 else []
        out += [(q, k, s[k, q]) for k in keep]
    return out


s = socket.create_connection((HOST, PORT)); s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
async def call(inputs):
    return protocol.call(s, inputs)
ref_n = got_n = matched = 0; bmin, smax, lmax, t_img, t_txt = [], [], 0.0, [], []
for i in range(8):
    photo = RequestInput(name="photo", datatype="BYTES", shape=[1], data=[open(f"{PH}/photo{i}.jpg", "rb").read()])
    queries = RequestInput(name="queries", datatype="BYTES", shape=[len(VOCAB)], data=[v.encode() for v in VOCAB])
    out, done = asyncio.run(h.run({"photo": photo, "queries": queries}, Params(output="raw"), call))
    t_img.append(done["image_us"] / 1000); t_txt.append(done["text_us"] / 1000)
    r = np.load(f"{R}/ref{i}.npz"); rl, rb = r["logits"].reshape(P, -1), r["boxes"].reshape(P, 4)
    lmax = max(lmax, float(np.abs(out["logits"] - rl).max()))
    rd, gd = detections(rl, rb), detections(out["logits"], out["boxes"]); ref_n += len(rd); got_n += len(gd)
    for q, k, sc in rd:
        cand = [(kk, ss) for qq, kk, ss in gd if qq == q]
        if not cand: continue
        ious = h._iou(rb[[k]], out["boxes"][[kk for kk, _ in cand]])[0]; j = ious.argmax()
        if ious[j] >= 0.5: matched += 1; bmin.append(ious[j]); smax.append(abs(cand[j][1] - sc))
res, _ = asyncio.run(h.run({"photo": photo, "queries": queries}, None, call))
doc = json.loads(res["result"])
print(f"vs the original: detections {matched}/{ref_n} matched ({got_n} found), box IoU min {min(bmin):.4f}, score max diff {max(smax):.4f}, logit max diff {lmax:.4f}; "
      f"worker image tower {np.median(t_img):.0f} ms, text tower {np.median(t_txt):.0f} ms per 32; last photo's JSON: {sum(len(q['detections']) for q in doc['queries'])} detections")
