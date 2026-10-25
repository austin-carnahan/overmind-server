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


def _aa_weights(in_size, out_size):
    """torch's antialiased bilinear weights for uint8 (UpSampleKernel's
    _compute_indices_weights_aa + int16 conversion, as Pillow-SIMD): a dense
    [out, in] float64 matrix of integer weights and their precision bits."""
    scale = in_size / out_size
    support = max(scale, 1.0)
    ss = 1.0 / max(scale, 1.0)
    rows = []
    for i in range(out_size):
        center = (i + 0.5) * scale
        xmin = max(int(center - support + 0.5), 0)
        xmax = min(int(center + support + 0.5), in_size)
        w = np.maximum(0.0, 1.0 - np.abs((np.arange(xmax - xmin) + xmin - center + 0.5) * ss))
        rows.append((xmin, w / w.sum() if w.sum() else w))
    wmax = max(w.max() for _, w in rows)
    p = 0
    while p < 22 and int(0.5 + wmax * (1 << (p + 1))) < (1 << 15):
        p += 1
    m = np.zeros((out_size, in_size))
    for i, (xmin, w) in enumerate(rows):
        m[i, xmin:xmin + len(w)] = np.floor(0.5 + w * (1 << p))
    return m, p


def torchvision_resize_u8(rgb, out_h, out_w):
    """torchvision v2.Resize((out_h, out_w)) on a uint8 HWC image (bilinear,
    antialias): horizontal pass, then vertical, each in fixed point with
    rounding and clamping -- bit-exact with torch's uint8 kernel (8/8 lane
    photos). Integer sums stay far below 2^53, so float64 BLAS is exact."""
    x = rgb.astype(np.float64)
    for axis, size in ((1, out_w), (0, out_h)):
        m, p = _aa_weights(x.shape[axis], size)
        acc = np.tensordot(m, np.moveaxis(x, axis, 0), axes=(1, 0))
        x = np.moveaxis(np.clip(np.floor((acc + (1 << (p - 1))) / (1 << p)), 0, 255), 0, axis)
    return x.astype(np.uint8)


OWLV2_MEAN = np.array([0.48145466, 0.4578275, 0.40821073], np.float32)
OWLV2_STD = np.array([0.26862954, 0.26130258, 0.27577711], np.float32)


def _mirror(i, n):
    """scipy.ndimage mode='mirror' (reflect about the edge pixels' centers)."""
    if n == 1:
        return np.zeros_like(i)
    period = 2 * n - 2
    i = np.abs(i) % period
    return np.where(i >= n, period - i, i)


def _gaussian_filter1d(x, sigma, axis):
    """scipy.ndimage.gaussian_filter1d (truncate 4.0, mode mirror), float64
    accumulation, result in x's dtype."""
    radius = int(4.0 * sigma + 0.5)
    if radius == 0:
        return x
    t = np.arange(-radius, radius + 1, dtype=np.float64)
    w = np.exp(-0.5 / (sigma * sigma) * t * t)
    w /= w.sum()
    n = x.shape[axis]
    xm = np.moveaxis(x, axis, 0).astype(np.float64)
    out = np.zeros_like(xm)
    for k, wk in enumerate(w):
        out += wk * xm[_mirror(np.arange(n) + k - radius, n)]
    return np.moveaxis(out, 0, axis).astype(x.dtype)


def _zoom_linear(x, out_shape):
    """scipy.ndimage.zoom(order=1, mode='mirror', grid_mode=True) over the
    first two axes of an HWC float32 image: source coordinate (o + 0.5) *
    in / out - 0.5, linear weights in float64, result float32."""
    def taps(n_in, n_out):
        c = (np.arange(n_out, dtype=np.float64) + 0.5) * (n_in / n_out) - 0.5
        i0 = np.floor(c).astype(np.int64)
        t = c - i0
        return _mirror(i0, n_in), _mirror(i0 + 1, n_in), 1.0 - t, t
    y0, y1, wy0, wy1 = taps(x.shape[0], out_shape[0])
    x0, x1, wx0, wx1 = taps(x.shape[1], out_shape[1])
    xd = x.astype(np.float64)
    a, b = xd[y0], xd[y1]
    out = (wy0[:, None, None] * (wx0[None, :, None] * a[:, x0] + wx1[None, :, None] * a[:, x1])
           + wy1[:, None, None] * (wx0[None, :, None] * b[:, x0] + wx1[None, :, None] * b[:, x1]))
    return out.astype(np.float32)


def owlv2_pixels(rgb, size=960):
    """Owlv2ImageProcessorPil (transformers 5.20.2, the validated inputs):
    x * (1/255) (float64, stored float32), zero-padded bottom/right to a
    square, Gaussian anti-aliasing when downscaling (sigma = (factor - 1) / 2,
    scipy truncate 4, mirror), linear zoom to size x size (grid mode, mirror),
    clipped to the padded image's range, CLIP mean/std. rgb uint8 HWC ->
    float32 [1, 3, size, size]. Ports scipy.ndimage (the guest has no scipy)."""
    x = (rgb.astype(np.float64) * (1 / 255)).astype(np.float32)
    h, w = x.shape[:2]
    s = max(h, w)
    x = np.pad(x, ((0, s - h), (0, s - w), (0, 0)))
    sigma = max((s / size - 1) / 2, 0.0)
    f = x
    if sigma > 0:
        f = _gaussian_filter1d(_gaussian_filter1d(x, sigma, 0), sigma, 1)
    out = np.clip(_zoom_linear(f, (size, size)), x.min(), x.max())
    out = (out - OWLV2_MEAN) / OWLV2_STD
    return np.ascontiguousarray(out.transpose(2, 0, 1))[None].astype(np.float32)
