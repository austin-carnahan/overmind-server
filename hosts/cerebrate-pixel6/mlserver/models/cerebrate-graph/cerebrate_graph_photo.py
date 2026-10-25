"""Photo-in hooks for the cerebrate-graph adapter (model-settings extra
cerebrate_graph_photo: yoloe | sam). A request carrying a "photo" (BYTES,
one element: the encoded JPEG/PNG file; base64 text over REST) is turned
into the worker's uint8 input with the reference preprocessing
(photo_preprocess) -- the worker normalizes -- and the worker's outputs into
final results in photo coordinates (photo_postprocess), returned as one
BYTES output "result" holding a JSON document. Request parameter
output=raw returns the worker's raw tensors instead, plus the geometry to
map them back (debugging and regression tests). Requests without a photo
pass through unchanged (the raw tensor path).

yoloe  {photo} -> {"image": {"width", "height"}, "detections": [{"box":
       [x1, y1, x2, y2], "score", "class_id", "label", "mask": <encoded>}]}
       (Ultralytics' NMS and native-resolution masks; raw mode adds
       letterbox [ratio, pad_left, pad_top] and original_size)
sam    {photo?, image_id, boxes?} with boxes [N, 4] xyxy in photo pixels ->
       {"image": {...}, "image_id", "masks": [{"box", "score", "mask":
       <encoded>}]} (one per box, in order; SAM's postprocess_masks). Without
       a photo the request decodes against the worker's cached embedding;
       the hook remembers each image_id's size (the last 16) to rescale
       boxes. A photo without boxes just encodes and caches (no masks).
       Raw mode adds input_size and original_size.
<encoded> mask: {"bbox": [x0, y0, x1, y1] end-exclusive, and "rle": run
lengths (row-major within the bbox, starting with zeros) or "bits": base64
of the bbox crop packed row-major (np.packbits)} -- photo_postprocess.decode_mask
inverts it."""
import base64
import json
import os
from collections import OrderedDict

import numpy as np
from mlserver.codecs import NumpyCodec

import photo_postprocess as post
import photo_preprocess as pp

LABELS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "labels")


def photo_bytes(request_input) -> bytes:
    data = getattr(request_input.data, "root", request_input.data)
    if request_input.datatype != "BYTES" or len(data) != 1:
        raise ValueError("photo: one BYTES element (the encoded image file)")
    item = data[0]
    return base64.b64decode(item) if isinstance(item, str) else bytes(item)


def tensor(request_input) -> np.ndarray:
    return NumpyCodec.decode_input(request_input)


def wants_raw(params) -> bool:
    mode = getattr(params, "output", None) if params is not None else None
    if mode not in (None, "result", "raw"):
        raise ValueError("parameter output: result (default) or raw")
    return mode == "raw"


def as_json(doc) -> bytes:
    return json.dumps(doc, separators=(",", ":"), ensure_ascii=False).encode()


class YoloeHooks:
    def __init__(self):
        with open(os.path.join(LABELS, "yoloe-v8s-pf.json"), encoding="utf-8") as f:
            self.labels = json.load(f)

    def prepare(self, inputs: dict, params=None):
        if "photo" not in inputs:
            return None
        if set(inputs) != {"photo"}:
            raise ValueError("with a photo, send only the photo")
        bgr = pp.decode(photo_bytes(inputs["photo"]))
        u8, (r, left, top, _, _) = pp.yoloe_letterbox(bgr)
        ctx = {"raw": wants_raw(params), "shape": bgr.shape[:2], "letterbox": (r, left, top)}
        return {"images": u8[None]}, ctx

    def finish(self, outputs: dict, ctx: dict) -> dict:
        h, w = ctx["shape"]
        if ctx["raw"]:
            return {**outputs, "letterbox": np.array(ctx["letterbox"], np.float32), "original_size": np.array([h, w], np.int64)}
        boxes, scores, ids, masks = post.yoloe_results(outputs["boxes"], outputs["score"], outputs["cls"], outputs["coef"], outputs["protos"], (h, w))
        dets = [{"box": [float(v) for v in b], "score": float(s), "class_id": int(c), "label": self.labels[int(c)], "mask": post.encode_mask(m)}
                for b, s, c, m in zip(boxes, scores, ids, masks)]
        return {"result": as_json({"image": {"width": w, "height": h}, "detections": dets})}


class SamHooks:
    def __init__(self, remember: int = 16):
        self.sizes = OrderedDict()   # image_id -> (original (h, w), resized (h, w))
        self.remember = remember

    def prepare(self, inputs: dict, params=None):
        if "photo" not in inputs and "image" in inputs:
            return None
        if "image_id" not in inputs:
            raise ValueError("image_id (int64, one element) is required")
        unknown = set(inputs) - {"photo", "image_id", "boxes"}
        if unknown:
            raise ValueError(f"unexpected inputs {sorted(unknown)}")
        image_id = tensor(inputs["image_id"]).astype(np.int64).reshape(1)
        key = int(image_id[0])
        worker = {"image_id": image_id}
        if "photo" in inputs:
            bgr = pp.decode(photo_bytes(inputs["photo"]))
            u8, (nh, nw) = pp.sam_resize(bgr)
            worker["image"], worker["extent"] = u8[None], np.array([nh, nw], np.int64)
            self.sizes[key] = (bgr.shape[:2], (nh, nw))
            self.sizes.move_to_end(key)
            while len(self.sizes) > self.remember:
                self.sizes.popitem(last=False)
        elif key not in self.sizes:
            raise ValueError(f"image_id {key} unknown here; send the photo again")
        (h, w), (nh, nw) = self.sizes[key]
        photo_boxes = None
        if "boxes" in inputs:
            photo_boxes = tensor(inputs["boxes"]).reshape(-1, 4).astype(np.float32)
            b = photo_boxes.astype(np.float64)   # as SAM's apply_coords: float64, then float32
            b[:, [0, 2]] *= nw / w
            b[:, [1, 3]] *= nh / h
            worker["boxes"] = b.astype(np.float32).reshape(-1, 1, 4)
        elif "photo" not in inputs:
            raise ValueError("send boxes, a photo, or both")
        return worker, {"raw": wants_raw(params), "image_id": key, "shape": (h, w), "input_size": (nh, nw), "boxes": photo_boxes}

    def finish(self, outputs: dict, ctx: dict) -> dict:
        (h, w), (nh, nw) = ctx["shape"], ctx["input_size"]
        if ctx["raw"]:
            return {**outputs, "input_size": np.array([nh, nw], np.int64), "original_size": np.array([h, w], np.int64)}
        doc = {"image": {"width": w, "height": h}, "image_id": ctx["image_id"], "masks": []}
        if ctx["boxes"] is not None:
            masks = post.sam_masks(outputs["mask_logits"].reshape(-1, 256, 256), (nh, nw), (h, w))
            scores = outputs["iou"].reshape(-1)
            doc["masks"] = [{"box": [float(v) for v in b], "score": float(s), "mask": post.encode_mask(m)}
                            for b, s, m in zip(ctx["boxes"], scores, masks)]
        return {"result": as_json(doc)}


HOOKS = {"yoloe": YoloeHooks, "sam": SamHooks}

# The registry's GPU models (model_hooks.py), registered here so the adapter
# keeps one lookup table.
import model_hooks  # noqa: E402

HOOKS.update({"depth": model_hooks.DepthHooks, "migan": model_hooks.MiganHooks, "dinov2": model_hooks.Dinov2Hooks,
              "sam2": model_hooks.Sam2Hooks, "rfdetr": model_hooks.RfdetrHooks, "esam3": model_hooks.Esam3Hooks,
              "owlv2": model_hooks.Owlv2Hooks})
