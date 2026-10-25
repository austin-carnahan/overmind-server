"""SAM 2.1 photo path on the device: the adapter hook (PIL bilinear 1024x1024,
prompt encoder in numpy) around a graph-mode worker (encoder cached per
image_id, constants-as-inputs box decoder), on the validation set: 4 photos x
2 boxes, judged against the original model's low-res masks (all 3 candidates,
> 0 at 256x256: IoU and flipped pixels), then the hook's final masks.
usage: sam2_photo_check.py <host> <port> <dir: photo0-3.jpg, ref_masks.npy, ref_iou.npy>"""
import sys, socket, json, asyncio
import numpy as np
sys.path.insert(0, "/home/droid/cg-test/stage/code/cerebrate-graph")
import cerebrate_graph_protocol as protocol
import cerebrate_graph_photo as cgp
from mlserver.types import RequestInput
from PIL import Image

HOST, PORT, D = sys.argv[1], int(sys.argv[2]), sys.argv[3]
BOXES = [[0.25, 0.35, 0.75, 0.95], [0.05, 0.05, 0.55, 0.60]]
ref, ref_iou = np.load(f"{D}/ref_masks.npy"), np.load(f"{D}/ref_iou.npy")


class Params:
    def __init__(self, **kw): self.__dict__.update(kw)


h = cgp.HOOKS["sam2"]()
s = socket.create_connection((HOST, PORT)); s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
worst, flipped, iou_diff, k, enc_ms, box_ms = 1.0, 0, 0.0, 0, [], []
for i in range(4):
    data = open(f"{D}/photo{i}.jpg", "rb").read()
    w, hh = Image.open(f"{D}/photo{i}.jpg").size
    boxes = np.array([[b[0] * w, b[1] * hh, b[2] * w, b[3] * hh] for b in BOXES], np.float32)
    inputs = {"photo": RequestInput(name="photo", datatype="BYTES", shape=[1], data=[data]),
              "image_id": RequestInput(name="image_id", datatype="INT64", shape=[1], data=[i]),
              "boxes": RequestInput(name="boxes", datatype="FP32", shape=[2, 4], data=boxes.ravel().tolist())}
    worker, ctx = h.prepare(inputs, Params(output="raw"))
    out, done = protocol.call(s, worker); enc_ms.append(done["gpu_us"] / 1000); box_ms.append(done["prompt_us"] / 2000)
    for j in range(2):
        got = out["masks"][j, 0] > 0; r = ref[k] > 0
        for c in range(3):
            u = (got[c] | r[c]).sum(); worst = min(worst, (got[c] & r[c]).sum() / u if u else 1.0); flipped += int((got[c] != r[c]).sum())
        iou_diff = max(iou_diff, float(np.abs(out["iou"][j, 0] - ref_iou[k]).max())); k += 1
    doc = json.loads(h.finish(out, {**ctx, "raw": False})["result"])
print(f"8 boxes x 3 masks vs the original: worst mask IoU {worst:.4f}, flipped pixels {flipped}, iou score max diff {iou_diff:.1e}; "
      f"encoder {np.median(enc_ms):.0f} ms, decoder {np.median(box_ms):.0f} ms/box (worker); final masks for the last photo: {len(doc['masks'])}, scores {[round(m['score'], 3) for m in doc['masks']]}")
