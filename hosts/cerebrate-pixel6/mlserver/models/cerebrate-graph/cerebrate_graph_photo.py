"""Photo-in hooks for the cerebrate-graph adapter (model-settings extra
cerebrate_graph_photo: yoloe | sam). A request carrying a "photo" (BYTES,
one element: the encoded JPEG/PNG file; base64 text over REST) is turned
into the worker's uint8 input here, with the reference preprocessing
(photo_preprocess), and the worker normalizes it. Requests without a photo
pass through unchanged (the raw tensor / debug path).
Step 1 of the transport work: the worker's outputs are still the raw
tensors; finish() adds the geometry a client needs to map them back to the
photo. (Step 2 replaces this with final results.)
  yoloe  {photo} -> worker {images: uint8 [1,640,640,3]}; adds
         letterbox [ratio, pad_left, pad_top] (float32) and original_size
         [h, w] (int64)
  sam    {photo?, image_id, boxes?} with boxes [N,4] xyxy in photo pixels ->
         worker {image: uint8 [1,1024,1024,3], extent [h, w], image_id,
         boxes [N,1,4] in the 1024 frame (SAM's apply_boxes)}; adds
         input_size and original_size. Without a photo the request decodes
         against the worker's cached embedding; this hook remembers each
         image_id's size (the last 16) to rescale its boxes."""
import base64
from collections import OrderedDict

import numpy as np
from mlserver.codecs import NumpyCodec

import photo_preprocess as pp


def photo_bytes(request_input) -> bytes:
    data = getattr(request_input.data, "root", request_input.data)
    if request_input.datatype != "BYTES" or len(data) != 1:
        raise ValueError("photo: one BYTES element (the encoded image file)")
    item = data[0]
    return base64.b64decode(item) if isinstance(item, str) else bytes(item)


def tensor(request_input) -> np.ndarray:
    return NumpyCodec.decode_input(request_input)


class YoloeHooks:
    def prepare(self, inputs: dict):
        if "photo" not in inputs:
            return None
        if set(inputs) != {"photo"}:
            raise ValueError("with a photo, send only the photo")
        bgr = pp.decode(photo_bytes(inputs["photo"]))
        u8, (r, left, top, _, _) = pp.yoloe_letterbox(bgr)
        ctx = {"letterbox": np.array([r, left, top], np.float32), "original_size": np.array(bgr.shape[:2], np.int64)}
        return {"images": u8[None]}, ctx

    def finish(self, outputs: dict, ctx: dict) -> dict:
        return {**outputs, **ctx}


class SamHooks:
    def __init__(self, remember: int = 16):
        self.sizes = OrderedDict()   # image_id -> (original (h, w), resized (h, w))
        self.remember = remember

    def prepare(self, inputs: dict):
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
        if "boxes" in inputs:
            b = tensor(inputs["boxes"]).reshape(-1, 4).astype(np.float64)   # as SAM's apply_coords: float64, then float32
            b[:, [0, 2]] *= nw / w
            b[:, [1, 3]] *= nh / h
            worker["boxes"] = b.astype(np.float32).reshape(-1, 1, 4)
        elif "photo" not in inputs:
            raise ValueError("send boxes, a photo, or both")
        return worker, {"input_size": np.array([nh, nw], np.int64), "original_size": np.array([h, w], np.int64)}

    def finish(self, outputs: dict, ctx: dict) -> dict:
        return {**outputs, **ctx}


HOOKS = {"yoloe": YoloeHooks, "sam": SamHooks}
