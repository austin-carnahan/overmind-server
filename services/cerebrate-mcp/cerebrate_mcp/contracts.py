"""One adapter per serving contract -- the catalog's `serving.interface`,
defined by the MLServer photo hooks (hosts/cerebrate-pixel6/mlserver/README.md,
"Contracts") -- not per model. Every production endpoint whose interface is
here is callable through that contract's tool; a model with a new interface
needs one entry here and one tool in server.py (README, "Adding a contract").

Each adapter only maps MCP arguments to the endpoint's V2 inputs and the
endpoint's JSON result to a compact response: all model logic (preprocessing,
postprocessing, labels) stays in the MLServer hooks. Masks keep the hooks'
compact encoding and can also be saved as PNG artifacts, decoded with the
hooks' own photo_postprocess.decode_mask."""
import base64
import hashlib
import io
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageFilter

from .artifacts import Artifacts, InputError, b64
from .mlserver import bytes_input, tensor_input


@dataclass(frozen=True)
class Contract:
    interface: str
    tool: str
    default_task: str
    summary: str
    inputs: str


CONTRACTS = {c.interface: c for c in (
    Contract("photo-box-masks-v1", "segment_region", "box-refinement",
             "precise masks for regions given as boxes",
             "image; boxes [[x0, y0, x1, y1], ...] in image pixels"),
    Contract("photo-detections-v1", "detect_objects", "fixed-class-segmentation",
             "find and outline objects without a prompt (labels from the model's own vocabulary)",
             "image; optional min_score, max_detections, save_masks"),
    Contract("photo-text-segmentation-v1", "segment_by_text", "text-prompted-segmentation",
             "outline every instance of each text phrase",
             "image; prompts: up to 16 short phrases"),
    Contract("photo-text-detection-v1", "detect_by_text", "open-vocabulary-detection",
             "boxes for each text query (no masks)",
             "image; queries: up to 256 phrases; optional threshold"),
    Contract("photo-depth-v1", "estimate_depth", "relative-depth",
             "relative depth map (larger = nearer)",
             "image"),
    Contract("photo-inpaint-v1", "inpaint", "inpainting",
             "inpainting: fill the masked region from its surroundings",
             "image; mask: an image of the same size, white = remove"),
    Contract("photo-embedding-v1", "embed_image", "image-embedding",
             "a global image embedding for similarity",
             "image"),
)}
TOOL_CONTRACT = {c.tool: c.interface for c in CONTRACTS.values()}


def image_id(data: bytes) -> int:
    """A stable id per image, so cached-image endpoints (SAM, EfficientSAM3)
    reuse an embedding when the same photo comes back."""
    return int.from_bytes(hashlib.sha256(data).digest()[:7], "big")


def mask_png(post, art: Artifacts, run: str, name: str, enc: dict, size: tuple[int, int]) -> dict:
    w, h = size
    return art.save_png(run, name, post.decode_mask(enc, (h, w)).astype(np.uint8) * 255)


# ---- requests: MCP arguments -> (V2 inputs, parameters) ----------------------
def segment_region_request(photo: bytes, boxes: list) -> tuple[list, dict]:
    if not boxes or any(len(b) != 4 for b in boxes):
        raise InputError("boxes: a non-empty list of [x0, y0, x1, y1]")
    flat = [float(v) for b in boxes for v in b]
    return [bytes_input("photo", b64(photo)),
            tensor_input("image_id", "INT64", [1], [image_id(photo)]),
            tensor_input("boxes", "FP32", [len(boxes), 4], flat)], {}


def photo_request(photo: bytes, **parameters) -> tuple[list, dict]:
    return [bytes_input("photo", b64(photo))], {k: v for k, v in parameters.items() if v is not None}


def text_segmentation_request(photo: bytes, prompts: list[str]) -> tuple[list, dict]:
    if not prompts or len(prompts) > 16:
        raise InputError("prompts: 1 to 16 phrases")
    return [bytes_input("photo", b64(photo)),
            tensor_input("image_id", "INT64", [1], [image_id(photo)]),
            {"name": "prompts", "shape": [len(prompts)], "datatype": "BYTES", "data": list(prompts)}], {}


def text_detection_request(photo: bytes, queries: list[str], threshold: float | None) -> tuple[list, dict]:
    if not queries or len(queries) > 256:
        raise InputError("queries: 1 to 256 phrases")
    return [bytes_input("photo", b64(photo)),
            {"name": "queries", "shape": [len(queries)], "datatype": "BYTES", "data": list(queries)}], \
        ({"threshold": threshold} if threshold is not None else {})


def grow_mask(mask: bytes, px: int) -> bytes:
    """White (remove) = >= 128, grown by px pixels: inpainting needs a margin
    beyond a tight object mask, or the fill picks up the object's edges."""
    m = Image.open(io.BytesIO(mask)).convert("L").point(lambda v: 255 if v >= 128 else 0)
    if px > 0:
        m = m.filter(ImageFilter.MaxFilter(2 * px + 1))
    buf = io.BytesIO()
    m.save(buf, format="PNG")
    return buf.getvalue()


def inpaint_request(photo: bytes, size: tuple, mask: bytes, mask_size: tuple, grow_px: int) -> tuple[list, dict]:
    if size != mask_size:
        raise InputError(f"mask is {mask_size[0]}x{mask_size[1]}, the image {size[0]}x{size[1]}")
    if not 0 <= grow_px <= 64:
        raise InputError("grow_mask_px: 0 to 64")
    return [bytes_input("photo", b64(photo)), bytes_input("mask", b64(grow_mask(mask, grow_px)))], {}


# ---- results: the endpoint's JSON -> a compact response ----------------------
def segment_region_result(doc: dict, post, art: Artifacts, run: str, size: tuple) -> dict:
    masks = []
    for i, m in enumerate(doc["masks"]):
        masks.append({"box": m["box"], "score": m["score"], "mask": m["mask"],
                      "mask_png": mask_png(post, art, run, f"mask-{i}.png", m["mask"], size)})
    return {"image": doc["image"], "masks": masks}


def detections_result(doc: dict, post, art: Artifacts, run: str, size: tuple,
                      min_score: float, max_detections: int, save_masks: bool) -> dict:
    dets = sorted((d for d in doc["detections"] if d["score"] >= min_score), key=lambda d: -d["score"])
    total = len(dets)
    out = []
    for i, d in enumerate(dets[:max_detections]):
        item = {k: d[k] for k in ("label", "score", "box", "class_id") if k in d}
        if "mask" in d:
            item["mask"] = d["mask"]
            if save_masks:
                item["mask_png"] = mask_png(post, art, run, f"mask-{i}.png", d["mask"], size)
        out.append(item)
    return {"image": doc["image"], "detections": out, "total_detections": total}


def text_segmentation_result(doc: dict, post, art: Artifacts, run: str, size: tuple, save_masks: bool) -> dict:
    prompts = []
    for p, pr in enumerate(doc["prompts"]):
        dets = []
        for i, d in enumerate(pr["detections"]):
            item = {"box": d["box"], "score": d["score"], "mask": d["mask"]}
            if save_masks:
                item["mask_png"] = mask_png(post, art, run, f"prompt{p}-mask{i}.png", d["mask"], size)
            dets.append(item)
        prompts.append({"text": pr["text"], "presence": pr.get("presence"), "detections": dets})
    return {"image": doc["image"], "prompts": prompts}


def depth_result(doc: dict, art: Artifacts, run: str) -> dict:
    depth = dict(doc["depth"])
    png = base64.b64decode(depth.pop("data"))
    depth["png16"] = art.save_bytes(run, "depth.png", png)
    return {"image": doc["image"], "depth": depth}


def inpaint_result(doc: dict, art: Artifacts, run: str) -> dict:
    return {"image": doc["image"], "result_png": art.save_bytes(run, "inpainted.png", base64.b64decode(doc["result"]))}
