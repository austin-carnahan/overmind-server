"""photo_postprocess (numpy) against the reference postprocessing (PyTorch),
on the same raw device outputs: YOLOE (out-fast) through Ultralytics 8.4.184
with retina_masks (non_max_suppression, scale_boxes, process_mask_native,
empty masks dropped); EdgeSAM (supervisor-run logits) through SAM's
postprocess_masks. Reports detections, boxes, scores, flipped mask pixels,
and checks encode_mask / decode_mask round trips and their sizes. Exactly
tied scores (the fp16 head produces some) have an implementation-defined
order (torchvision sorts stably, Ultralytics' fallback NMS doesn't), so both
sides are compared sorted by score, then box, then class.
usage: photo_postprocess_check.py <dl-edgesam dir> <yoloe raw dir> <edgesam ref dir> <edgesam logits dir> <photo files in index order...>"""
import sys, os, json
import numpy as np, cv2, torch
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../mlserver/models/cerebrate-graph"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../spikes/edgesam-tpu"))
import photo_postprocess as post
from ultralytics.utils import nms as unms, ops
D, YR, ER, EL = sys.argv[1:5]
files = sys.argv[5:]
NC = 4585
enc_sizes, flips_y, flips_e, total_e, dets = [], 0, 0, 0, 0
for i, f in enumerate(files):
    h, w = cv2.imread(f).shape[:2]
    r = np.load(f"{YR}/out{i}.npz")
    pred = torch.zeros(1, 4 + NC + 32, 8400)
    pred[0, :4] = torch.from_numpy(r["boxes"][0]); pred[0, 4 + NC:] = torch.from_numpy(r["coef"][0])
    pred[0, 4 + torch.from_numpy(r["cls"][0]).long(), torch.arange(8400)] = torch.from_numpy(r["score"][0])
    det = unms.non_max_suppression(pred, 0.25, 0.7, agnostic=True, nc=NC, max_det=300)[0]
    det[:, :4] = ops.scale_boxes((640, 640), det[:, :4], (h, w))
    rm = ops.process_mask_native(torch.from_numpy(r["protos"][0]), det[:, 6:], det[:, :4], (h, w)) if len(det) else torch.zeros(0, h, w)
    keep = rm.amax((-2, -1)) > 0
    det, rm = det[keep], rm[keep].numpy().astype(bool)
    xyxy, conf, cid, masks = post.yoloe_results(r["boxes"], r["score"], r["cls"], r["coef"], r["protos"], (h, w))
    ra = np.lexsort((det[:, 5].numpy(), det[:, 1].numpy(), det[:, 0].numpy(), -det[:, 4].numpy()))
    det, rm = det[torch.from_numpy(ra)], rm[ra]
    na = np.lexsort((cid, xyxy[:, 1], xyxy[:, 0], -conf))
    xyxy, conf, cid, masks = xyxy[na], conf[na], cid[na], [masks[j] for j in na]
    same = len(masks) == len(det) and np.array_equal(cid, det[:, 5].numpy().astype(np.int64)) and np.array_equal(conf, det[:, 4].numpy())
    bd = float(np.abs(xyxy - det[:, :4].numpy()).max(initial=0)) if same else float("nan")
    fl = int(sum((a ^ b).sum() for a, b in zip(masks, rm))) if same else -1
    flips_y += max(fl, 0); dets += len(det)
    for m in masks:
        e = post.encode_mask(m); assert np.array_equal(post.decode_mask(e, (h, w)), m); enc_sizes.append(len(json.dumps(e)))
    print(f"photo {i} ({w}x{h}): YOLOE {len(det)} detections, same classes+scores {same}, box max |diff| {bd:.1e} px, mask pixels flipped {fl}", flush=True)
from edgesam_common import load_edgesam
sam, _ = load_edgesam(D, "bicubic")
k = 0
for i in range(len(files)):
    ref = np.load(f"{ER}/ref{i}.npz"); n = len(ref["boxes"])
    low = np.stack([np.fromfile(f"{EL}/{k + j}_o0.bin", np.float32).reshape(256, 256) for j in range(n)]); k += n
    isz, osz = tuple(ref["input_size"]), tuple(ref["original_size"])
    with torch.no_grad():
        tm = (sam.postprocess_masks(torch.from_numpy(low)[:, None], isz, osz) > 0).numpy()[:, 0]
    nm = post.sam_masks(low, isz, osz)
    flips_e += int((tm ^ nm).sum()); total_e += n
    for m in nm:
        e = post.encode_mask(m); assert np.array_equal(post.decode_mask(e, osz), m); enc_sizes.append(len(json.dumps(e)))
print(f"YOLOE: {dets} detections, mask pixels flipped in total {flips_y}")
print(f"EdgeSAM: {total_e} masks, pixels flipped vs postprocess_masks {flips_e}")
print(f"encoded masks: {len(enc_sizes)} round trips exact; JSON size median {int(np.median(enc_sizes))} B, max {max(enc_sizes)} B")
