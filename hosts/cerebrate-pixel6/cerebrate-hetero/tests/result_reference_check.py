"""Result-mode JSON from MLServer (saved by mlserver_result_test.py for extra
photos) against PyTorch references computed here from the raw outputs saved
alongside: YOLOE through Ultralytics' NMS + native masks, EdgeSAM through
SAM's postprocess_masks. usage: result_reference_check.py <dl-edgesam dir> <saved dir>"""
import sys, os, json, glob
import numpy as np, torch
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../mlserver/models/cerebrate-graph"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../spikes/edgesam-tpu"))
import photo_postprocess as post
from ultralytics.utils import nms as unms, ops
from edgesam_common import load_edgesam
D, SD = sys.argv[1:3]
sam, _ = load_edgesam(D, "bicubic"); NC = 4585
for z in sorted(glob.glob(f"{SD}/extra*.npz")):
    r = np.load(z); doc = json.load(open(z[:-4] + ".json")); h, w = doc["yoloe"]["image"]["height"], doc["yoloe"]["image"]["width"]
    pred = torch.zeros(1, 4 + NC + 32, 8400)
    pred[0, :4] = torch.from_numpy(r["y_boxes"][0].copy()); pred[0, 4 + NC:] = torch.from_numpy(r["y_coef"][0].copy())
    pred[0, 4 + torch.from_numpy(r["y_cls"][0].copy()).long(), torch.arange(8400)] = torch.from_numpy(r["y_score"][0].copy())
    det = unms.non_max_suppression(pred, 0.25, 0.7, agnostic=True, nc=NC, max_det=300)[0]
    det[:, :4] = ops.scale_boxes((640, 640), det[:, :4], (h, w))
    rm = ops.process_mask_native(torch.from_numpy(r["y_protos"][0].copy()), det[:, 6:], det[:, :4], (h, w)) if len(det) else torch.zeros(0, h, w)
    keep = rm.amax((-2, -1)) > 0; det, rm = det[keep].numpy(), rm[keep].numpy().astype(bool)
    dets = doc["yoloe"]["detections"]
    key = lambda s, b, c: (-s, b[0], b[1], c)
    ref = sorted(zip(det[:, 4], det[:, :4].tolist(), det[:, 5].astype(int), rm), key=lambda t: key(t[0], t[1], t[2]))
    got = sorted(dets, key=lambda d: key(np.float32(d["score"]), d["box"], d["class_id"]))
    same = len(ref) == len(got) and all(np.float32(g["score"]) == s and g["class_id"] == c and np.array_equal(np.array(g["box"], np.float32), np.array(b, np.float32)) for (s, b, c, _), g in zip(ref, got))
    flips = sum(int((post.decode_mask(g["mask"], (h, w)) ^ m).sum()) for (_, _, _, m), g in zip(ref, got)) if same else -1
    isz = tuple(int(v) for v in r["e_input_size"].reshape(-1))
    with torch.no_grad():
        tm = (sam.postprocess_masks(torch.from_numpy(r["e_mask_logits"].copy()).reshape(-1, 1, 256, 256), isz, (h, w)) > 0).numpy()[:, 0]
    ef = sum(int((post.decode_mask(g["mask"], (h, w)) ^ t).sum()) for g, t in zip(doc["edgesam"]["masks"], tm))
    print(f"{os.path.basename(z)} ({w}x{h}): YOLOE {len(got)} detections same as Ultralytics {same}, mask pixels flipped {flips}; EdgeSAM {len(tm)} masks, pixels flipped vs postprocess_masks {ef}")
