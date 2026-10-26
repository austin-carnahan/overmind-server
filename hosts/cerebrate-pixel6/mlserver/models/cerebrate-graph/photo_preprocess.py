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


def torchvision_resize_u8(rgb, out_h, out_w, block=256):
    """torchvision v2.Resize((out_h, out_w)) on a uint8 HWC image (bilinear,
    antialias): horizontal pass, then vertical, each in fixed point with
    rounding and clamping -- bit-exact with torch's uint8 kernel (8/8 lane
    photos). Integer sums stay far below 2^53, so float64 BLAS is exact in
    any order: each pass runs in blocks of the other axis, with the
    intermediate in uint8 (its values are clamped integers). The whole photo
    in float64 at once took 830 MB for 12 MP; the guest has under 1 GB."""
    x = rgb
    for axis, size in ((1, out_w), (0, out_h)):
        m, p = _aa_weights(x.shape[axis], size)
        other = 1 - axis
        shape = list(x.shape)
        shape[axis] = size
        y = np.empty(shape, np.uint8)
        for s0 in range(0, x.shape[other], block):
            sl = [slice(None)] * 3
            sl[other] = slice(s0, s0 + block)
            acc = np.tensordot(m, np.moveaxis(x[tuple(sl)].astype(np.float64), axis, 0), axes=(1, 0))
            y[tuple(sl)] = np.moveaxis(np.clip(np.floor((acc + (1 << (p - 1))) / (1 << p)), 0, 255), 0, axis)
        x = y
    return x


OWLV2_MEAN = np.array([0.48145466, 0.4578275, 0.40821073], np.float32)
OWLV2_STD = np.array([0.26862954, 0.26130258, 0.27577711], np.float32)


def _mirror(i, n):
    """scipy.ndimage mode='mirror' (reflect about the edge pixels' centers)."""
    if n == 1:
        return np.zeros_like(i)
    period = 2 * n - 2
    i = np.abs(i) % period
    return np.where(i >= n, period - i, i)


def _gaussian_rows(gather, n, wanted, sigma, block=128):
    """scipy.ndimage.gaussian_filter1d (truncate 4.0, mode mirror) along the
    first axis of a length-n array, only at the rows `wanted`: gather(idx)
    returns those input rows as float64. float64 accumulation in tap order,
    result float32 -- per output row exactly what filtering the whole array
    computes."""
    radius = int(4.0 * sigma + 0.5)
    if sigma <= 0 or radius == 0:
        return gather(wanted).astype(np.float32)
    t = np.arange(-radius, radius + 1, dtype=np.float64)
    w = np.exp(-0.5 / (sigma * sigma) * t * t)
    w /= w.sum()
    out = None
    for b0 in range(0, len(wanted), block):
        idx = wanted[b0:b0 + block]
        acc = 0.0
        for k, wk in enumerate(w):
            acc = acc + wk * gather(_mirror(idx + k - radius, n))   # as zeros + taps, in order
        if out is None:
            out = np.empty((len(wanted), acc.shape[1]), np.float32)
        out[b0:b0 + len(idx)] = acc.astype(np.float32)
    return out


def _zoom_taps(n_in, n_out):
    """scipy.ndimage.zoom(order=1, mode='mirror', grid_mode=True) taps: source
    coordinate (o + 0.5) * in / out - 0.5, linear weights in float64."""
    c = (np.arange(n_out, dtype=np.float64) + 0.5) * (n_in / n_out) - 0.5
    i0 = np.floor(c).astype(np.int64)
    t = c - i0
    return _mirror(i0, n_in), _mirror(i0 + 1, n_in), 1.0 - t, t


def owlv2_pixels(rgb, size=960):
    """Owlv2ImageProcessorPil (transformers 5.20.2, the validated inputs):
    x * (1/255) (float64, stored float32), zero-padded bottom/right to a
    square, Gaussian anti-aliasing when downscaling (sigma = (factor - 1) / 2,
    scipy truncate 4, mirror), linear zoom to size x size (grid mode, mirror),
    clipped to the padded image's range, CLIP mean/std. rgb uint8 HWC ->
    float32 [1, 3, size, size]. Ports scipy.ndimage (the guest has no scipy).
    Computed only at the rows and columns the zoom samples, a channel and a
    block of rows at a time, the padding never materialized: the same values
    as filtering the whole padded square, which took 1.6 GB for a 12 MP
    photo (tests/test_photo_hooks.py checks them bit for bit)."""
    h, w = rgb.shape[:2]
    s = max(h, w)
    sigma = max((s / size - 1) / 2, 0.0)
    y0, y1, wy0, wy1 = _zoom_taps(s, size)
    x0, x1, wx0, wx1 = _zoom_taps(s, size)
    rows, cols = np.unique(np.concatenate([y0, y1])), np.unique(np.concatenate([x0, x1]))
    ry0, ry1, cx0, cx1 = (np.searchsorted(rows, y0), np.searchsorted(rows, y1),
                          np.searchsorted(cols, x0), np.searchsorted(cols, x1))
    scaled = lambda v: (np.asarray(v).astype(np.float64) * (1 / 255)).astype(np.float32)
    lo = np.float32(0) if (h < s or w < s) else scaled(rgb.min())        # the padded square's range
    hi = scaled(rgb.max())
    out = np.empty((size, size, 3), np.float32)
    for c in range(3):
        def padded_rows(idx):                 # rows of the padded square, scaled as gathered
            r = np.zeros((len(idx), s))
            ok = idx < h
            r[ok, :w] = scaled(rgb[idx[ok], :, c])
            return r
        f = _gaussian_rows(padded_rows, s, rows, sigma)                    # axis 0, at the sampled rows
        ft = f.T
        f = _gaussian_rows(lambda idx: ft[idx].astype(np.float64), s, cols, sigma).T   # axis 1, at the sampled columns
        a, b = f.astype(np.float64)[ry0], f.astype(np.float64)[ry1]
        z = (wy0[:, None] * (wx0[None, :] * a[:, cx0] + wx1[None, :] * a[:, cx1])
             + wy1[:, None] * (wx0[None, :] * b[:, cx0] + wx1[None, :] * b[:, cx1]))
        out[..., c] = z.astype(np.float32)
    out = np.clip(out, lo, hi)
    out = (out - OWLV2_MEAN) / OWLV2_STD
    return np.ascontiguousarray(out.transpose(2, 0, 1))[None].astype(np.float32)
