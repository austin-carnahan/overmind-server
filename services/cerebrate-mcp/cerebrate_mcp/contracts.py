"""One adapter per serving contract -- the catalog's `serving.interface`,
defined by the MLServer photo hooks (hosts/cerebrate-pixel6/mlserver/README.md,
"Contracts") -- not per model. Every production endpoint whose interface is
here is callable through that contract's tool; a model with a new interface
needs one entry here and one tool in server.py (README, "Adding a contract").

Each adapter only maps MCP arguments to the endpoint's V2 inputs and the
endpoint's JSON result to a compact response: all model logic (preprocessing,
postprocessing, labels) stays in the MLServer hooks. Masks keep the hooks'
compact encoding and can also be saved as PNG artifacts, decoded with the
hooks' own photo_postprocess.decode_mask. Every mask also comes as polygons
(mask_polygons) -- the form an editor takes a selection in.

Two adapters reshape the request itself, for the photo sizes a phone
produces: inpaint sends a window around the mask instead of the whole photo
and returns a patch, and segment_by_text sends large photos scaled down
(text_segmentation_scale)."""
import base64
import hashlib
import io
import math
from dataclasses import dataclass

import cv2
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
             "image; prompts: up to 16 short phrases (photos over 2048 px are segmented scaled down)"),
    Contract("photo-text-detection-v1", "detect_by_text", "open-vocabulary-detection",
             "boxes for each text query (no masks)",
             "image; queries: up to 256 phrases; optional threshold"),
    Contract("photo-depth-v1", "estimate_depth", "relative-depth",
             "relative depth map (larger = nearer)",
             "image"),
    Contract("photo-inpaint-v1", "inpaint", "inpainting",
             "inpainting: fill the masked region from its surroundings; returns a patch and its offset",
             "image; mask: an image of the same size, white = remove; optional grow_mask_px, composite"),
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


def mask_polygons(post, enc: dict, scale: float = 1.0, eps: float = 1.0, min_area: float = 4.0) -> list[dict]:
    """A mask as polygon rings {"hole", "points": [x0, y0, x1, y1, ...]} in
    image pixels, ordered for an editor's polygon select: each outer ring
    (largest first) followed by its holes, so "replace" for the first ring,
    "add" for later outers and "subtract" for holes rebuilds the mask -- an
    island inside a hole comes after that hole. Vertices sit on pixel
    corners: contours of the 2x nearest-upscaled mask, q -> (q + 1) // 2.
    Tracing pixel centres instead loses half a pixel all round in GIMP (which
    keeps pixels whose centre is inside); corner-traced and simplified to
    eps 1 px, GIMP selections rebuilt from these matched the masks at IoU
    0.998 median, 0.990 minimum (services/cerebrate-mcp/README.md, "Polygons").
    scale maps a mask computed on a scaled-down photo back to the original."""
    x0, y0, x1, y1 = enc["bbox"]
    w, h = x1 - x0, y1 - y0
    if w <= 0 or h <= 0:
        return []
    crop = post.decode_mask({**enc, "bbox": [0, 0, w, h]}, (h, w)).astype(np.uint8)
    up = np.pad(np.kron(crop, np.ones((2, 2), np.uint8)), 1)
    contours, hier = cv2.findContours(up, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    rings = []
    for i, c in enumerate(contours):
        p = c.reshape(-1, 2) // 2 + [x0, y0]          # (q + 1) // 2 with q = c - 1 (the pad)
        p = p[np.any(p != np.roll(p, 1, 0), 1)]
        if len(p) < 3 or cv2.contourArea(p.astype(np.float32)) < min_area:
            continue
        a = cv2.approxPolyDP(p.reshape(-1, 1, 2).astype(np.int32), eps, True).reshape(-1, 2)
        parent = int(hier[0][i][3])
        rings.append({"i": i, "parent": parent, "area": cv2.contourArea(a.astype(np.float32)), "points": a})
    outers = sorted((r for r in rings if r["parent"] < 0), key=lambda r: -r["area"])
    holes = {}
    for r in rings:
        if r["parent"] >= 0:
            holes.setdefault(r["parent"], []).append(r)
    out = []
    for o in outers:
        for r in [o] + holes.get(o["i"], []):
            pts = r["points"].astype(np.float64) * scale
            out.append({"hole": r["parent"] >= 0,
                        "points": [round(float(v), 2) if scale != 1 else int(v) for v in pts.reshape(-1)]})
    return out


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


def text_segmentation_scale(photo: bytes, size: tuple, max_side: int) -> tuple[bytes, float]:
    """A photo over max_side px goes to the model scaled down; the factor
    maps results back. EfficientSAM3 sees 1008 px and predicts 288 px masks,
    so nothing is lost -- and its hook upsamples every kept mask to the photo
    as float32 at once, which on a 12 MP photo got MLServer OOM-killed on the
    Pixel guest (959 MB). Interim until that hook upsamples mask by mask."""
    if max(size) <= max_side:
        return photo, 1.0
    s = max(size) / max_side
    im = Image.open(io.BytesIO(photo)).convert("RGB").resize((round(size[0] / s), round(size[1] / s)), Image.BILINEAR)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=95)
    return buf.getvalue(), s


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


def _png(im: Image.Image) -> bytes:
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def inpaint_window(size: tuple, bbox: tuple, side_min: int = 512, context: float = 2.0) -> tuple:
    """The crop sent to the inpainting model: a square (where the photo
    allows) of at least side_min px and `context` times the mask's extent,
    centred on the mask. The model works at a fixed size (MI-GAN: 512), so a
    whole 12 MP photo squashed to 512 left a 15x26 px hole to fill and an 8x
    blurred patch; a window keeps the fill near the photo's resolution."""
    w, h = size
    x0, y0, x1, y1 = bbox
    side = max(side_min, math.ceil(context * max(x1 - x0, y1 - y0)))
    ww, wh = min(side, w), min(side, h)
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    wx = min(max(cx - ww // 2, 0), w - ww)
    wy = min(max(cy - wh // 2, 0), h - wh)
    return wx, wy, wx + ww, wy + wh


def inpaint_request(photo: bytes, size: tuple, mask: bytes, mask_size: tuple, grow_px: int, ctx: dict) -> tuple[list, dict]:
    if size != mask_size:
        raise InputError(f"mask is {mask_size[0]}x{mask_size[1]}, the image {size[0]}x{size[1]}")
    if not 0 <= grow_px <= 64:
        raise InputError("grow_mask_px: 0 to 64")
    grown = Image.open(io.BytesIO(grow_mask(mask, grow_px))).convert("L")
    bbox = grown.getbbox()
    if bbox is None:
        raise InputError("mask: empty (no white pixels)")
    window = inpaint_window(size, bbox)
    im = Image.open(io.BytesIO(photo)).convert("RGB")
    ctx.update(window=window, bbox=bbox, mask=grown.crop(window), photo=im)
    return [bytes_input("photo", b64(_png(im.crop(window)))), bytes_input("mask", b64(_png(ctx["mask"])))], {}


# ---- results: the endpoint's JSON -> a compact response ----------------------
def segment_region_result(doc: dict, post, art: Artifacts, run: str, size: tuple) -> dict:
    masks = []
    for i, m in enumerate(doc["masks"]):
        masks.append({"box": m["box"], "score": m["score"], "mask": m["mask"],
                      "polygons": mask_polygons(post, m["mask"]),
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
            item["polygons"] = mask_polygons(post, d["mask"])
            if save_masks:
                item["mask_png"] = mask_png(post, art, run, f"mask-{i}.png", d["mask"], size)
        out.append(item)
    return {"image": doc["image"], "detections": out, "total_detections": total}


def _upscaled_mask(post, enc: dict, small: tuple, size: tuple) -> dict:
    """A mask from the scaled-down photo, at the original size (nearest)."""
    m = post.decode_mask(enc, (small[1], small[0])).astype(np.uint8) * 255
    return post.encode_mask(np.asarray(Image.fromarray(m).resize(size, Image.NEAREST)) >= 128)


def text_segmentation_result(doc: dict, post, art: Artifacts, run: str, size: tuple, save_masks: bool,
                             scale: float = 1.0) -> dict:
    small = (doc["image"]["width"], doc["image"]["height"])
    prompts = []
    for p, pr in enumerate(doc["prompts"]):
        dets = []
        for i, d in enumerate(pr["detections"]):
            full = d["mask"] if scale == 1 else _upscaled_mask(post, d["mask"], small, size)
            item = {"box": [v * scale for v in d["box"]], "score": d["score"], "mask": full,
                    "polygons": mask_polygons(post, d["mask"], scale)}
            if save_masks:
                item["mask_png"] = mask_png(post, art, run, f"prompt{p}-mask{i}.png", full, size)
            dets.append(item)
        prompts.append({"text": pr["text"], "presence": pr.get("presence"), "detections": dets})
    out = {"image": {"width": size[0], "height": size[1]}, "prompts": prompts}
    if scale != 1:
        out["segmented_at"] = {"width": small[0], "height": small[1]}
    return out


def depth_result(doc: dict, art: Artifacts, run: str) -> dict:
    depth = dict(doc["depth"])
    png = base64.b64decode(depth.pop("data"))
    depth["png16"] = art.save_bytes(run, "depth.png", png)
    return {"image": doc["image"], "depth": depth}


def inpaint_result(doc: dict, art: Artifacts, run: str, ctx: dict, composite: bool) -> dict:
    """The fill as a patch: RGBA, alpha = the grown mask, cut to the mask's
    bounds, with its offset in the photo -- placed as a layer it covers only
    the filled pixels. composite also saves the whole photo with the patch."""
    wx, wy, wx1, wy1 = ctx["window"]
    filled = Image.open(io.BytesIO(base64.b64decode(doc["result"]))).convert("RGB")
    if filled.size != (wx1 - wx, wy1 - wy):
        raise InputError(f"inpainting returned {filled.size[0]}x{filled.size[1]} for a {wx1 - wx}x{wy1 - wy} window")
    bx0, by0, bx1, by1 = ctx["bbox"]
    local = (bx0 - wx, by0 - wy, bx1 - wx, by1 - wy)
    patch = filled.crop(local)
    patch.putalpha(ctx["mask"].crop(local))
    out = {"image": {"width": ctx["photo"].width, "height": ctx["photo"].height},
           "patch": art.save_bytes(run, "patch.png", _png(patch)),
           "offset": [bx0, by0], "size": [bx1 - bx0, by1 - by0], "window": [wx, wy, wx1, wy1]}
    if composite:
        full = ctx["photo"].copy()
        full.paste(patch, (bx0, by0), patch)
        out["result_png"] = art.save_bytes(run, "inpainted.png", _png(full))
    return out
