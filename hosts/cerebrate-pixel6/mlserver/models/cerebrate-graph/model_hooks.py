"""Photo-in hooks for the registry's GPU models (cerebrate_graph_photo has
YOLOE's and EdgeSAM's). Each turns a request carrying a "photo" (BYTES, the
encoded file; base64 text over REST) into the worker's inputs with the
preprocessing its reference used, and the worker's outputs into a task-level
JSON result ("result", BYTES). Request parameter output=raw returns the
worker's raw tensors instead (plus the geometry to map them back). Requests
without a photo pass through to the worker unchanged (the raw tensor path).
Contracts (hosts/cerebrate-pixel6/mlserver/README.md):

depth   {photo} -> {"image", "depth": {"width", "height", "encoding": "png16",
        "min", "max", "semantics", "mapping", "data": base64 16-bit PNG}};
        value = min + png / 65535 * (max - min). PIL decode + bicubic stretch
        to 686x518 (the published fixed shape), as the reference.
migan   {photo, mask} with mask white (>= 128) = remove -> {"image", "result":
        base64 PNG at the photo's size}: the author's pipeline (migan.onnx):
        bilinear to 512 (rounded to uint8), nearest mask, the generator, its
        output bilinear back to the photo, composited over the original.
dinov2  {photo} -> {"image", "embedding": {"dim": 384, "pooling", "dtype":
        "float32", "data": base64}, "patch_grid": [32, 32]}; parameter
        patches=true adds "patch_tokens" ([1024, 384] float32, base64). PIL
        decode + bicubic 448x448, as the reference.
"""
import base64
import io
import json

import cv2
import numpy as np
from PIL import Image

import photo_postprocess as post


def _bytes(request_input, what="photo"):
    data = getattr(request_input.data, "root", request_input.data)
    if request_input.datatype != "BYTES" or len(data) != 1:
        raise ValueError(f"{what}: one BYTES element (the encoded image file)")
    item = data[0]
    return base64.b64decode(item) if isinstance(item, str) else bytes(item)


def _param(params, name, default=None):
    if params is None:
        return default
    value = getattr(params, name, None)
    if value is None and getattr(params, "model_extra", None):
        value = params.model_extra.get(name)
    return default if value is None else value


def _raw(params) -> bool:
    mode = _param(params, "output")
    if mode not in (None, "result", "raw"):
        raise ValueError("parameter output: result (default) or raw")
    return mode == "raw"


def _json(doc) -> bytes:
    return json.dumps(doc, separators=(",", ":"), ensure_ascii=False).encode()


def pil_rgb(data: bytes) -> Image.Image:
    """PIL decode, as the published-model references (no EXIF rotation)."""
    try:
        img = Image.open(io.BytesIO(data))
        return img.convert("RGB")
    except Exception as exc:   # PIL raises several types for undecodable input
        raise ValueError(f"not a decodable image: {exc}") from exc


def _b64(a: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode()


class DepthHooks:
    W, H = 686, 518

    def prepare(self, inputs, params=None):
        if "photo" not in inputs:
            return None
        if set(inputs) != {"photo"}:
            raise ValueError("with a photo, send only the photo")
        img = pil_rgb(_bytes(inputs["photo"]))
        u8 = np.asarray(img.resize((self.W, self.H), Image.BICUBIC), np.uint8)
        return {"pixel_values": u8[None]}, {"raw": _raw(params), "size": (img.height, img.width)}

    def finish(self, outputs, ctx):
        h, w = ctx["size"]
        if ctx["raw"]:
            return {**outputs, "original_size": np.array([h, w], np.int64)}
        d = outputs["depth"].reshape(self.H, self.W).astype(np.float32)
        lo, hi = float(d.min()), float(d.max())
        q = np.zeros(d.shape, np.uint16) if hi <= lo else np.round((d - lo) / (hi - lo) * 65535).astype(np.uint16)
        ok, png = cv2.imencode(".png", q)
        if not ok:
            raise ValueError("PNG encoding failed")
        return {"result": _json({
            "image": {"width": w, "height": h},
            "depth": {"width": self.W, "height": self.H, "encoding": "png16", "min": lo, "max": hi,
                      "semantics": "relative inverse depth (affine-invariant, larger = nearer); value = min + png / 65535 * (max - min)",
                      "mapping": "the photo stretched to width x height (no letterbox)",
                      "data": base64.b64encode(png.tobytes()).decode()}})}


def _nearest_floor(in_size, out_size):
    """ONNX Resize nearest, asymmetric, floor: source index floor(i / (out / in))."""
    scale = np.float32(out_size) / np.float32(in_size)
    return np.minimum(np.floor(np.arange(out_size, dtype=np.float32) / scale).astype(np.int64), in_size - 1)


class MiganHooks:
    """MI-GAN 512 Places2 as the author's migan.onnx pipeline (MIT) wraps the
    generator, on a window of the photo around the hole
    (post.inpaint_window: >= 512 px, twice the hole's extent): the pipeline
    squashes the whole photo to 512, which on a 12 MP photo left the hole a
    few pixels wide and the fill an 8x blur, and held several float32 copies
    of the photo. Outside the window the photo is returned as sent. Parameter
    window=false (and output=raw) keep the whole-photo pipeline, as validated
    against the author's."""
    S = 512

    def prepare(self, inputs, params=None):
        if "photo" not in inputs:
            return None
        if set(inputs) != {"photo", "mask"}:
            raise ValueError("send photo and mask (white = remove)")
        rgb = np.asarray(pil_rgb(_bytes(inputs["photo"])), np.uint8)
        try:
            mask = np.asarray(Image.open(io.BytesIO(_bytes(inputs["mask"], "mask"))).convert("L"), np.uint8)
        except Exception as exc:
            raise ValueError(f"mask: not a decodable image: {exc}") from exc
        h, w = rgb.shape[:2]
        if mask.shape != (h, w):
            raise ValueError(f"mask is {mask.shape[1]}x{mask.shape[0]}, the photo {w}x{h}")
        keep = np.where(mask >= 128, 0, 255).astype(np.uint8)          # the pipeline's mask: 255 = keep
        raw = _raw(params)
        window = (0, 0, w, h)
        hole = np.argwhere(keep == 0)
        if not raw and str(_param(params, "window", "true")).lower() not in ("0", "false", "no") and len(hole):
            (y0, x0), (y1, x1) = hole.min(0), hole.max(0) + 1
            window = post.inpaint_window((w, h), (int(x0), int(y0), int(x1), int(y1)), self.S)
        wx0, wy0, wx1, wy1 = window
        crop, keep_c = rgb[wy0:wy1, wx0:wx1], keep[wy0:wy1, wx0:wx1]
        ch, cw = crop.shape[:2]
        small = np.round(post.bilinear(crop.transpose(2, 0, 1).astype(np.float32), self.S, self.S)).astype(np.uint8)  # Resize linear, Round, Cast
        keep_s = keep_c[_nearest_floor(ch, self.S)][:, _nearest_floor(cw, self.S)]
        x = small.astype(np.float32) * np.float32(2) / np.float32(255) - np.float32(1)
        k = keep_s.astype(np.float32) / np.float32(255)
        net = np.concatenate([(k - np.float32(0.5))[None], x * k[None]])[None].astype(np.float32)
        return {"masked_image": net}, {"raw": raw, "rgb": rgb, "keep": keep_c, "window": window}

    def finish(self, outputs, ctx):
        rgb, keep_c, (wx0, wy0, wx1, wy1) = ctx["rgb"], ctx["keep"], ctx["window"]
        h, w = rgb.shape[:2]
        if ctx["raw"]:
            return {**outputs, "original_size": np.array([h, w], np.int64)}
        g = outputs["image"].reshape(3, self.S, self.S).astype(np.float32)
        g = np.clip((g * np.float32(0.5) + np.float32(0.5)) * np.float32(255), 0, 255)
        up = post.bilinear(g, wy1 - wy0, wx1 - wx0)
        k = keep_c.astype(np.float32) / np.float32(255)
        crop = rgb[wy0:wy1, wx0:wx1].transpose(2, 0, 1).astype(np.float32)
        out = rgb.copy()
        out[wy0:wy1, wx0:wx1] = np.clip(crop * k + up * (np.float32(1) - k), 0, 255).astype(np.uint8).transpose(1, 2, 0)
        ok, png = cv2.imencode(".png", np.ascontiguousarray(out[..., ::-1]))
        if not ok:
            raise ValueError("PNG encoding failed")
        return {"result": _json({"image": {"width": w, "height": h}, "encoding": "png",
                                 "window": [int(wx0), int(wy0), int(wx1), int(wy1)],
                                 "result": base64.b64encode(png.tobytes()).decode()})}


class Dinov2Hooks:
    S = 448

    def prepare(self, inputs, params=None):
        if "photo" not in inputs:
            return None
        if set(inputs) != {"photo"}:
            raise ValueError("with a photo, send only the photo")
        img = pil_rgb(_bytes(inputs["photo"]))
        u8 = np.asarray(img.resize((self.S, self.S), Image.BICUBIC), np.uint8)
        patches = str(_param(params, "patches", "false")).lower() == "true"
        return {"pixel_values": u8[None]}, {"raw": _raw(params), "size": (img.height, img.width), "patches": patches}

    def finish(self, outputs, ctx):
        h, w = ctx["size"]
        if ctx["raw"]:
            return {**outputs, "original_size": np.array([h, w], np.int64)}
        t = outputs["patch_tokens"].reshape(-1, 384).astype(np.float32)
        doc = {"image": {"width": w, "height": h}, "input_size": [self.S, self.S], "patch_grid": [32, 32],
               "embedding": {"dim": 384, "dtype": "float32", "byte_order": "little",
                             "pooling": "mean of the 1,024 final-normalized patch tokens (not L2-normalized)",
                             "data": _b64(t.mean(0, dtype=np.float32).astype("<f4"))}}
        if ctx["patches"]:
            doc["patch_tokens"] = {"shape": [1024, 384], "dtype": "float32", "byte_order": "little", "data": _b64(t.astype("<f4"))}
        return {"result": _json(doc)}


ASSETS = __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), "assets")


class Sam2Hooks:
    """SAM 2.1 Hiera-Tiny box refinement: {photo?, image_id, boxes?} with boxes
    [N, 4] xyxy in photo pixels -> {"image", "image_id", "masks": [{"box",
    "score", "mask"}]}: per box the best of the decoder's three candidates by
    predicted IoU (parameter masks=all: all three, "candidates"). Photo: PIL
    decode + bilinear 1024x1024 (no aspect kept), as the reference; boxes
    scaled per axis into that frame and encoded here with SAM 2.1's prompt
    encoder (two corner tokens + padding); masks: the processor's
    post_process_masks (bilinear 256 -> photo, > 0)."""
    S = 1024

    def __init__(self, remember: int = 16):
        from collections import OrderedDict
        c = np.load(__import__("os").path.join(ASSETS, "sam2.1-hiera-tiny-prompt-encoder.npz"))
        self.gauss, self.c0, self.c1, self.nap = c["gauss"], c["corner0"], c["corner1"], c["not_a_point"]
        self.sizes, self.remember = OrderedDict(), remember

    def sparse(self, box):
        """box float32 [4] xyxy in the 1024 frame -> [3, 256] (Sam2PromptEncoder._embed_boxes)."""
        pts = (box.reshape(2, 2) + np.float32(0.5)) / np.float32(self.S)
        coords = np.float32(2 * np.pi) * ((np.float32(2) * pts - np.float32(1)) @ self.gauss)
        emb = np.concatenate([np.sin(coords), np.cos(coords)], -1).astype(np.float32)
        return np.stack([emb[0] + self.c0, emb[1] + self.c1, self.nap])

    def prepare(self, inputs, params=None):
        if "photo" not in inputs and "pixel_values" in inputs:
            return None
        if "image_id" not in inputs:
            raise ValueError("image_id (int64, one element) is required")
        unknown = set(inputs) - {"photo", "image_id", "boxes"}
        if unknown:
            raise ValueError(f"unexpected inputs {sorted(unknown)}")
        from mlserver.codecs import NumpyCodec
        image_id = NumpyCodec.decode_input(inputs["image_id"]).astype(np.int64).reshape(1)
        key = int(image_id[0])
        worker = {"image_id": image_id}
        if "photo" in inputs:
            img = pil_rgb(_bytes(inputs["photo"]))
            worker["pixel_values"] = np.asarray(img.resize((self.S, self.S), Image.BILINEAR), np.uint8)[None]
            self.sizes[key] = (img.height, img.width)
            self.sizes.move_to_end(key)
            while len(self.sizes) > self.remember:
                self.sizes.popitem(last=False)
        elif key not in self.sizes:
            raise ValueError(f"image_id {key} unknown here; send the photo again")
        h, w = self.sizes[key]
        boxes = None
        if "boxes" in inputs:
            boxes = NumpyCodec.decode_input(inputs["boxes"]).reshape(-1, 4).astype(np.float32)
            b = boxes.copy()
            b[:, [0, 2]] *= np.float32(self.S / w)    # the processor's _normalize_coordinates
            b[:, [1, 3]] *= np.float32(self.S / h)
            worker["sparse"] = np.stack([self.sparse(x) for x in b])[:, None]
        elif "photo" not in inputs:
            raise ValueError("send boxes, a photo, or both")
        return worker, {"raw": _raw(params), "image_id": key, "shape": (h, w), "boxes": boxes,
                        "all": _param(params, "masks", "best") == "all"}

    def finish(self, outputs, ctx):
        h, w = ctx["shape"]
        if ctx["raw"]:
            return {**outputs, "original_size": np.array([h, w], np.int64)}
        doc = {"image": {"width": w, "height": h}, "image_id": ctx["image_id"], "masks": []}
        if ctx["boxes"] is not None:
            logits = outputs["masks"].reshape(-1, 3, 256, 256)
            ious = outputs["iou"].reshape(-1, 3)
            for b, lg, iou in zip(ctx["boxes"], logits, ious):
                order = [int(np.argmax(iou))] + ([k for k in range(3) if k != int(np.argmax(iou))] if ctx["all"] else [])
                ms = post.bilinear_rows(lg[order].astype(np.float32), h, w, lambda x: x > 0)
                entry = {"box": [float(v) for v in b], "score": float(iou[order[0]]), "mask": post.encode_mask(ms[0])}
                if ctx["all"]:
                    entry["candidates"] = [{"score": float(iou[k]), "mask": post.encode_mask(m)} for k, m in zip(order, ms)]
                doc["masks"].append(entry)
        return {"result": _json(doc)}


COCO91 = {1: "person", 2: "bicycle", 3: "car", 4: "motorcycle", 5: "airplane", 6: "bus", 7: "train", 8: "truck", 9: "boat",
          10: "traffic light", 11: "fire hydrant", 13: "stop sign", 14: "parking meter", 15: "bench", 16: "bird", 17: "cat",
          18: "dog", 19: "horse", 20: "sheep", 21: "cow", 22: "elephant", 23: "bear", 24: "zebra", 25: "giraffe", 27: "backpack",
          28: "umbrella", 31: "handbag", 32: "tie", 33: "suitcase", 34: "frisbee", 35: "skis", 36: "snowboard", 37: "sports ball",
          38: "kite", 39: "baseball bat", 40: "baseball glove", 41: "skateboard", 42: "surfboard", 43: "tennis racket",
          44: "bottle", 46: "wine glass", 47: "cup", 48: "fork", 49: "knife", 50: "spoon", 51: "bowl", 52: "banana", 53: "apple",
          54: "sandwich", 55: "orange", 56: "broccoli", 57: "carrot", 58: "hot dog", 59: "pizza", 60: "donut", 61: "cake",
          62: "chair", 63: "couch", 64: "potted plant", 65: "bed", 67: "dining table", 70: "toilet", 72: "tv", 73: "laptop",
          74: "mouse", 75: "remote", 76: "keyboard", 77: "cell phone", 78: "microwave", 79: "oven", 80: "toaster", 81: "sink",
          82: "refrigerator", 84: "book", 85: "clock", 86: "vase", 87: "scissors", 88: "teddy bear", 89: "hair drier",
          90: "toothbrush"}


class RfdetrHooks:
    """RF-DETR-Seg-Nano: {photo} -> {"image", "detections": [{"box", "score",
    "class_id" (COCO id), "label", "mask"}]}. Two worker calls with the
    published host step between them (litert-community's card, verbatim; see
    spikes/published-litert-eval/rfdetr_host.py). Photo: PIL decode +
    bilinear 312x312 (stretched), as the reference. Detections as the
    validation judged them: per query the best class, sigmoid > threshold
    (parameter threshold, default 0.5), class 0 dropped; boxes (cx, cy, w, h,
    normalized) to photo pixels; masks bilinear 78 -> photo, > 0."""
    S, NP_, NQ, NC, G = 312, 676, 100, 91, 26

    def __init__(self):
        self.refpoint = np.fromfile(__import__("os").path.join(ASSETS, "rfdetr-refpoint_embed.bin"), np.float32).reshape(self.NQ, 4)

    def host_step(self, enc_cls, delta, mem2):
        mem = mem2 * 0.5
        gy, gx = np.mgrid[0:self.G, 0:self.G]
        prop = np.stack([(gx + .5) / self.G, (gy + .5) / self.G], -1).reshape(self.NP_, 2)
        cxcy = delta[:, :2] * 0.05 + prop
        wh = np.exp(delta[:, 2:]) * 0.05
        top = np.argsort(-enc_cls.max(-1))[:self.NQ]
        ts = np.concatenate([cxcy, wh], -1)[top]
        rp = self.refpoint
        ref = np.concatenate([rp[:, :2] * ts[:, 2:] + ts[:, :2], np.exp(rp[:, 2:]) * ts[:, 2:]], -1)
        return mem.reshape(1, self.NP_, 256).astype(np.float32), ref.reshape(1, self.NQ, 4).astype(np.float32)

    async def run(self, inputs, params, call):
        if set(inputs) != {"photo"}:
            raise ValueError("send only the photo")
        img = pil_rgb(_bytes(inputs["photo"]))
        h, w = img.height, img.width
        u8 = np.asarray(img.resize((self.S, self.S), Image.BILINEAR), np.uint8)
        a, done_a = await call({"pixel_values": u8[None]})
        mem, ref = self.host_step(a["enc_cls"].reshape(self.NP_, self.NC), a["delta"].reshape(self.NP_, 4), a["memory2"].reshape(self.NP_, 256))
        b, done_b = await call({"memory": mem[None], "refpoints": ref[None]})
        done = {"inference_us": done_a.get("inference_us", 0) + done_b.get("inference_us", 0), "graph_a_us": done_a.get("inference_us", 0), "graph_b_us": done_b.get("inference_us", 0)}
        if _raw(params):
            return {**{f"a_{k}": v for k, v in a.items()}, **b, "original_size": np.array([h, w], np.int64)}, done
        thr = float(_param(params, "threshold", 0.5))
        logits, boxes, masks = b["logits"].reshape(self.NQ, self.NC), b["boxes"].reshape(self.NQ, 4), b["masks"].reshape(self.NQ, 78, 78)
        score = 1 / (1 + np.exp(-logits.max(-1)))
        cls = logits.argmax(-1)
        keep = np.where((score > thr) & (cls > 0))[0]
        keep = keep[np.argsort(-score[keep])]
        dets = []
        for q in keep:   # mask by mask, in strips: all kept masks at photo size at once can OOM the guest
            m = post.bilinear_rows(masks[q:q + 1].astype(np.float32), h, w, lambda x: x > 0)[0]
            cx, cy, bw, bh = (float(v) for v in boxes[q])
            dets.append({"box": [(cx - bw / 2) * w, (cy - bh / 2) * h, (cx + bw / 2) * w, (cy + bh / 2) * h],
                         "score": float(score[q]), "class_id": int(cls[q]), "label": COCO91.get(int(cls[q]), "N/A"),
                         "mask": post.encode_mask(m)})
        return {"result": _json({"image": {"width": w, "height": h}, "detections": dets})}, done


class Esam3Hooks:
    """EfficientSAM3 RV-M text-prompted segmentation: {photo?, image_id,
    prompts} with prompts BYTES, one element per phrase -> {"image",
    "image_id", "prompts": [{"text", "presence", "detections": [{"box",
    "score", "mask"}]}]}. The photo runs once (vision cached per image_id in
    the worker); each phrase is one worker call (text on the CPU, grounding
    on the GPU), so the guest holds one phrase's [200, 288, 288] masks at a
    time. Preprocessing as Sam3Processor: torchvision Resize(1008) on uint8
    (bit-exact port), x / 255, (x - 0.5) / 0.5 in the worker; tokens from the
    stdlib CLIP tokenizer (context 16, padding mask = id 0). Detections as
    Sam3Processor: sigmoid(logit) * sigmoid(presence) > threshold (parameter,
    default 0.5); boxes cxcywh -> xyxy in photo pixels; masks bilinear to the
    photo, sigmoid > 0.5 -- mask by mask, in strips of rows
    (post.bilinear_rows): all kept masks at photo size at once got MLServer
    OOM-killed on a 12 MP photo. Parameter output=raw: the first phrase's raw
    tensors."""
    S, CTX, MAX_PROMPTS = 1008, 16, 16

    def __init__(self, remember: int = 16):
        from collections import OrderedDict
        import clip_bpe
        self.tok = clip_bpe.ClipTokenizer()
        self.sizes, self.remember = OrderedDict(), remember

    async def run(self, inputs, params, call):
        from mlserver.codecs import NumpyCodec
        import photo_preprocess as pp
        unknown = set(inputs) - {"photo", "image_id", "prompts"}
        if unknown or "image_id" not in inputs:
            raise ValueError("send image_id with a photo and/or prompts (BYTES, one phrase per element)")
        image_id = NumpyCodec.decode_input(inputs["image_id"]).astype(np.int64).reshape(1)
        key = int(image_id[0])
        done = {"inference_us": 0, "vision_us": 0, "prompt_us": 0}
        if "photo" in inputs:
            img = pil_rgb(_bytes(inputs["photo"]))
            u8 = pp.torchvision_resize_u8(np.asarray(img, np.uint8), self.S, self.S)
            _, d = await call({"pixel_values": u8[None], "image_id": image_id})
            done["vision_us"] = d.get("inference_us", 0)
            self.sizes[key] = (img.height, img.width)
            self.sizes.move_to_end(key)
            while len(self.sizes) > self.remember:
                self.sizes.popitem(last=False)
        elif key not in self.sizes:
            raise ValueError(f"image_id {key} unknown here; send the photo again")
        h, w = self.sizes[key]
        texts = []
        if "prompts" in inputs:
            data = getattr(inputs["prompts"].data, "root", inputs["prompts"].data)
            texts = [x.decode() if isinstance(x, (bytes, bytearray)) else str(x) for x in data]
        if len(texts) > self.MAX_PROMPTS:
            raise ValueError(f"at most {self.MAX_PROMPTS} prompts per request")
        raw, thr = _raw(params), float(_param(params, "threshold", 0.5))
        doc = {"image": {"width": w, "height": h}, "image_id": key, "prompts": []}
        sig = lambda x: (np.float32(1) / (np.float32(1) + np.exp(-x.astype(np.float32)))).astype(np.float32)
        for text in texts:
            ids = np.array(self.tok([text], self.CTX), np.int32).reshape(1, 1, self.CTX)
            pad = (ids == 0).astype(np.float32)
            out, d = await call({"image_id": image_id, "ids": ids, "pad": pad})
            done["prompt_us"] += d.get("prompt_us", 0)
            if raw:
                done["inference_us"] = done["vision_us"] + done["prompt_us"]
                return {**out, "ids": ids, "original_size": np.array([h, w], np.int64)}, done
            logits, boxes = out["logits"].reshape(200), out["boxes"].reshape(200, 4)
            presence, masks = out["presence"].reshape(1), out["masks"].reshape(200, 288, 288)
            score = sig(logits) * sig(presence)[0]
            keep = np.where(score > thr)[0]
            dets = []
            for q in keep:
                m = post.bilinear_rows(masks[q:q + 1].astype(np.float32), h, w, lambda x: sig(x) > 0.5)[0]
                cx, cy, bw, bh = (float(v) for v in boxes[q])
                dets.append({"box": [(cx - bw / 2) * w, (cy - bh / 2) * h, (cx + bw / 2) * w, (cy + bh / 2) * h],
                             "score": float(score[q]), "mask": post.encode_mask(m)})
            doc["prompts"].append({"text": text, "presence": float(sig(presence)[0]), "detections": dets})
            del out, masks
        done["inference_us"] = done["vision_us"] + done["prompt_us"]
        return {"result": _json(doc)}, done


class Owlv2Hooks:
    """OWLv2 B/16 open-vocabulary detection: {photo, queries} with queries
    BYTES, one phrase per element -> {"image", "queries": [{"text",
    "detections": [{"box", "score"}]}]}. Two worker calls: the image tower
    (per-patch class embeddings, box logits, objectness) and the text tower
    (phrases in batches of 32); the host step here: logits = (class_embeds .
    q / (|q| + 1e-6) + shift) * scale, boxes = sigmoid(box_logits + box_bias)
    (the bias add moved off the G1 GPU, which computed it wrongly). Detections
    as the validation judged them: sigmoid(logit) >= threshold (parameter,
    default 0.2), per-query NMS at IoU 0.3; boxes (cx, cy, w, h on the padded
    square) to photo pixels. Photo: PIL decode + Owlv2ImageProcessorPil's
    preprocessing (photo_preprocess.owlv2_pixels; float32 to the worker)."""
    P, CTX, BATCH, MAX_QUERIES = 3600, 16, 32, 256

    def __init__(self):
        import clip_bpe
        self.tok = clip_bpe.ClipTokenizer()
        self.bias = np.fromfile(__import__("os").path.join(ASSETS, "owlv2-box_bias.bin"), "<f4").reshape(self.P, 4)

    @staticmethod
    def _iou(a, b):
        def xy(x): return np.stack([x[:, 0] - x[:, 2] / 2, x[:, 1] - x[:, 3] / 2, x[:, 0] + x[:, 2] / 2, x[:, 1] + x[:, 3] / 2], 1)
        a, b = xy(a), xy(b)
        lt = np.maximum(a[:, None, :2], b[None, :, :2]); rb = np.minimum(a[:, None, 2:], b[None, :, 2:])
        inter = np.clip(rb - lt, 0, None).prod(-1)
        area = lambda x: (x[:, 2] - x[:, 0]) * (x[:, 3] - x[:, 1])
        return inter / (area(a)[:, None] + area(b)[None, :] - inter + 1e-9)

    async def run(self, inputs, params, call):
        import photo_preprocess as pp
        if set(inputs) != {"photo", "queries"}:
            raise ValueError("send photo and queries (BYTES, one phrase per element)")
        data = getattr(inputs["queries"].data, "root", inputs["queries"].data)
        texts = [x.decode() if isinstance(x, (bytes, bytearray)) else str(x) for x in data]
        if not texts or len(texts) > self.MAX_QUERIES:
            raise ValueError(f"1 to {self.MAX_QUERIES} queries")
        img = pil_rgb(_bytes(inputs["photo"]))
        h, w = img.height, img.width
        tower, d1 = await call({"pixel_values": pp.owlv2_pixels(np.asarray(img, np.uint8))})
        n = -(-len(texts) // self.BATCH)
        ids = np.array(self.tok(texts + [""] * (n * self.BATCH - len(texts)), self.CTX), np.int32).reshape(n, self.BATCH, self.CTX)
        emb, d2 = await call({"ids": ids})
        done = {"inference_us": d1.get("inference_us", 0) + d2.get("inference_us", 0), "image_us": d1.get("inference_us", 0), "text_us": d2.get("inference_us", 0)}
        q = emb["embeddings"].reshape(-1, 512)[:len(texts)].astype(np.float32)
        ce = tower["class_embeds"].reshape(self.P, 512)
        shift, scale = tower["logit_shift"].reshape(self.P, 1), tower["logit_scale"].reshape(self.P, 1)
        logits = (ce @ (q / (np.linalg.norm(q, axis=-1, keepdims=True) + np.float32(1e-6))).T + shift) * scale
        boxes = 1 / (1 + np.exp(-(tower["box_logits"].reshape(self.P, 4) + self.bias)))
        if _raw(params):
            return {"logits": logits, "boxes": boxes, "objectness": tower["objectness"].reshape(self.P), "original_size": np.array([h, w], np.int64)}, done
        thr, side = float(_param(params, "threshold", 0.2)), max(h, w)
        sc = 1 / (1 + np.exp(-logits))
        doc = {"image": {"width": w, "height": h}, "queries": []}
        for qi, text in enumerate(texts):
            idx = np.where(sc[:, qi] >= thr)[0]
            idx = idx[np.argsort(-sc[idx, qi])]
            keep = []
            while len(idx):
                keep.append(idx[0])
                idx = idx[1:][self._iou(boxes[idx[:1]], boxes[idx[1:]])[0] < 0.3] if len(idx) > 1 else []
            dets = []
            for k in keep:
                cx, cy, bw, bh = (float(v) * side for v in boxes[k])
                dets.append({"box": [max(cx - bw / 2, 0.0), max(cy - bh / 2, 0.0), min(cx + bw / 2, float(w)), min(cy + bh / 2, float(h))],
                             "score": float(sc[k, qi])})
            doc["queries"].append({"text": text, "detections": dets})
        return {"result": _json(doc)}, done
