"""Image operations that run here, on overmind's CPU, beside the model tools.
They aren't models: no registry entry, no MLServer, nothing on the Pixel.

seamless_blend is a Poisson blend, OpenCV's seamlessClone. It keeps the
source's texture (its gradients) inside the mask and matches the destination
at the mask's edge, so a reconstruction takes on the light and colour of its
surroundings. It is the algorithm of the 2026-10-26 bed-footprint prototype:
about 2 s for a 1,100x700 region on the Pi, where GIMP's GEGL seamless-clone
took about 100 s."""
import io
import time

import cv2
import numpy as np
from PIL import Image

from .artifacts import InputError

PAD = 4   # seamlessClone fails on a mask touching the image's edge: blend inside a reflected border


def _decode(data: bytes, what: str) -> np.ndarray:
    bgr = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if bgr is None:
        raise InputError(f"{what}: not a decodable image")
    return bgr


def seamless_blend(image: bytes, mask: bytes, destination: bytes, mode: str = "normal") -> dict:
    """The blended region as an RGBA patch (alpha = the mask) cut to the mask's
    bounds, with its offset. image supplies the texture inside the mask,
    destination the surroundings matched at its edge.

    destination must be the scene *without* the reconstruction (e.g. the
    original photo layer): OpenCV erodes the mask by 3 px and takes the
    destination's gradients in that ring, so a destination that already
    contains the reconstruction carries its hard edge into the result and
    nothing blends. In the bed prototype it was the original photo."""
    if mode not in ("normal", "mixed"):
        raise InputError("mode: normal or mixed")
    src = _decode(image, "image")
    dst = _decode(destination, "destination")
    try:
        m = np.asarray(Image.open(io.BytesIO(mask)).convert("L"))
    except Exception as exc:
        raise InputError(f"mask: not a decodable image ({exc})") from exc
    if src.shape != dst.shape or m.shape != src.shape[:2]:
        raise InputError(f"sizes differ: image {src.shape[1]}x{src.shape[0]}, destination {dst.shape[1]}x{dst.shape[0]}, "
                         f"mask {m.shape[1]}x{m.shape[0]}")
    m = np.where(m >= 128, 255, 0).astype(np.uint8)
    if not m.any():
        raise InputError("mask: empty (no white pixels)")
    x, y, w, h = cv2.boundingRect(m)
    t0 = time.perf_counter()
    border = lambda a, kind: cv2.copyMakeBorder(a, PAD, PAD, PAD, PAD, kind)
    out = cv2.seamlessClone(border(src, cv2.BORDER_REFLECT), border(dst, cv2.BORDER_REFLECT), border(m, cv2.BORDER_CONSTANT),
                            (x + PAD + w // 2, y + PAD + h // 2), cv2.NORMAL_CLONE if mode == "normal" else cv2.MIXED_CLONE)
    blend_s = time.perf_counter() - t0
    out = out[PAD:-PAD, PAD:-PAD]
    patch = np.dstack([cv2.cvtColor(out[y:y + h, x:x + w], cv2.COLOR_BGR2RGB), m[y:y + h, x:x + w]])
    return {"patch": Image.fromarray(patch, "RGBA"), "offset": [x, y], "size": [w, h],
            "image": {"width": src.shape[1], "height": src.shape[0]}, "blend_s": round(blend_s, 2)}
