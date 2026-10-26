"""RF-DETR-Seg-Nano photo path on the device: the adapter hook (PIL bilinear
312x312; two worker calls with the published host step between them) around a
graph-mode worker. Graph A's outputs vs the validated device run (bit for bit),
graph B's vs the validated device run, and the detections vs the original
model (rfdetr 1.9.3) with the validation's rule: matched one-to-one by box IoU
>= 0.5; class, box IoU and mask IoU (78x78, > 0) of the matched.
usage: rfdetr_photo_check.py <host> <port> <photos dir> <dir: ref<i>.npz, outA/, outB/> """
import sys, socket, json, asyncio
import numpy as np
sys.path.insert(0, "/home/droid/cg-test/stage/code/cerebrate-graph")
import cerebrate_graph_protocol as protocol
import cerebrate_graph_photo as cgp
from mlserver.types import RequestInput

HOST, PORT, PH, R = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]


class Params:
    def __init__(self, **kw): self.__dict__.update(kw)


def dets(logits, boxes, masks, thr=0.5):
    score = 1 / (1 + np.exp(-logits.max(-1))); cls = logits.argmax(-1)
    return [(int(cls[q]), float(score[q]), boxes[q], masks[q] > 0) for q in np.where((score > thr) & (cls > 0))[0]]


def xyxy(b):
    cx, cy, w, h = b; return np.array([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2])


def box_iou(a, b):
    a, b = xyxy(a), xyxy(b)
    iw = max(0, min(a[2], b[2]) - max(a[0], b[0])); ih = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = iw * ih; u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / u if u > 0 else 0.0


s = socket.create_connection((HOST, PORT)); s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
async def call(inputs):
    return protocol.call(s, inputs)
h = cgp.HOOKS["rfdetr"]()
tot = dict(ref=0, got=0, matched=0, same_cls=0); biou, miou, a_same, b_same, ms = [], [], 0, 0, []
for i in range(8):
    photo = RequestInput(name="photo", datatype="BYTES", shape=[1], data=[open(f"{PH}/photo{i}.jpg", "rb").read()])
    out, done = asyncio.run(h.run({"photo": photo}, Params(output="raw"), call)); ms.append(done["inference_us"] / 1000)
    a_same += all(np.array_equal(np.fromfile(f"{R}/outA/{i}_o{k}.bin", np.float32), out[n].ravel()) for k, n in enumerate(("a_enc_cls", "a_delta", "a_memory2")))
    b_same += all(np.array_equal(np.fromfile(f"{R}/outB/{i}_o{k}.bin", np.float32), out[n].ravel()) for k, n in enumerate(("boxes", "logits", "masks")))
    r = np.load(f"{R}/ref{i}.npz")
    rd = dets(r["logits"], r["boxes"], r["masks"]); gd = dets(out["logits"][0, 0], out["boxes"][0, 0], out["masks"][0, 0])
    used = set(); tot["ref"] += len(rd); tot["got"] += len(gd)
    for rc, rs, rb, rm in sorted(rd, key=lambda d: -d[1]):
        best, bj = 0.5, None
        for j, (gc, gs, gb, gm) in enumerate(gd):
            if j not in used and box_iou(rb, gb) >= best: best, bj = box_iou(rb, gb), j
        if bj is None: continue
        used.add(bj); tot["matched"] += 1; gc, gs, gb, gm = gd[bj]; tot["same_cls"] += gc == rc; biou.append(best)
        u = (rm | gm).sum(); miou.append((rm & gm).sum() / u if u else 1.0)
    res, _ = asyncio.run(h.run({"photo": photo}, None, call))
    print(f"photo {i}: {len(json.loads(res['result'])['detections'])} final detections {[d['label'] for d in json.loads(res['result'])['detections']]}")
print(f"graph A bit-identical {a_same}/8, graph B bit-identical {b_same}/8; vs the original: matched {tot['matched']}/{tot['ref']} (+{tot['got'] - tot['matched']} extra), same class {tot['same_cls']}, "
      f"box IoU min {min(biou):.3f}, mask IoU min {min(miou):.3f} mean {np.mean(miou):.4f}; worker A+B median {np.median(ms):.0f} ms")
