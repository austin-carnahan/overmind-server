"""Photo -> model input, exactly as the validated reference pipelines do it,
for the guest adapter (uint8 to the worker; the worker normalizes):
  decode          cv2.imdecode (the references read photos with cv2.imread),
                  BGR uint8
  yoloe_letterbox Ultralytics LetterBox(640, auto=False): scale to fit,
                  cv2.resize INTER_LINEAR, centered padding with 114, RGB --
                  the worker computes x / 255 in float32
  sam_resize      SAM's ResizeLongestSide(1024) (torchvision resize of a PIL
                  image = Pillow BILINEAR) on RGB, padded with zeros to
                  1024 x 1024; the worker computes (x - mean) / std in float32
                  inside the valid extent and leaves the padding at 0, as
                  Sam.preprocess normalizes before padding
OpenCV is a dependency on purpose: on ARM its 8-bit bilinear resize goes
through a NEON HAL with its own rounding, which a numpy re-implementation of
OpenCV's generic code paths didn't reproduce (off by 1-2 levels), and the
references decode with OpenCV too. normalize_* are the worker's formulas in
numpy, used to check that uint8 + worker normalization equals the fp32
inputs the models were validated with."""
import numpy as np
import cv2
from PIL import Image

SAM_MEAN = np.array([123.675, 116.28, 103.53], np.float32)
SAM_STD = np.array([58.395, 57.12, 57.375], np.float32)


def decode(data: bytes) -> np.ndarray:
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("not a decodable image")
    return img


def yoloe_letterbox(bgr, size=640, pad=114):
    """-> RGB uint8 [size, size, 3], (ratio, left, top, new_w, new_h)."""
    h, w = bgr.shape[:2]
    r = min(size / h, size / w)
    nw, nh = max(round(w * r), 1), max(round(h * r), 1)
    dw, dh = (size - nw) / 2, (size - nh) / 2
    top, bottom = round(dh - 0.1), round(dh + 0.1)
    left, right = round(dw - 0.1), round(dw + 0.1)
    img = bgr if (w, h) == (nw, nh) else cv2.resize(bgr, (nw, nh), interpolation=cv2.INTER_LINEAR)
    img = cv2.copyMakeBorder(img, top, bottom, left, right, cv2.BORDER_CONSTANT, value=(pad, pad, pad))
    return np.ascontiguousarray(img[..., ::-1]), (r, left, top, nw, nh)


def sam_shape(h, w, target=1024):
    scale = target * 1.0 / max(h, w)
    return int(h * scale + 0.5), int(w * scale + 0.5)


def sam_resize(bgr, target=1024):
    """-> RGB uint8 [target, target, 3] zero-padded, (h, w) valid extent."""
    rgb = np.ascontiguousarray(bgr[..., ::-1])
    nh, nw = sam_shape(*rgb.shape[:2], target)
    small = np.array(Image.fromarray(rgb).resize((nw, nh), Image.BILINEAR))
    out = np.zeros((target, target, 3), np.uint8)
    out[:nh, :nw] = small
    return out, (nh, nw)


def normalize_yoloe(u8):
    return (u8.astype(np.float32) / np.float32(255))[None]


def normalize_sam(u8, extent):
    h, w = extent
    out = np.zeros(u8.shape, np.float32)
    out[:h, :w] = (u8[:h, :w].astype(np.float32) - SAM_MEAN) / SAM_STD
    return out[None]
