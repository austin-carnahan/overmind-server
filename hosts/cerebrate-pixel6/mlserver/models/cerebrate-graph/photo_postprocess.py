"""Model outputs -> final results in photo coordinates, numpy only (the
guest has no torch), mirroring the reference postprocessing:
  yoloe_results  Ultralytics 8.4.184 with retina_masks: non_max_suppression
                 (best class, class-agnostic, conf 0.25, IoU 0.7, max_det
                 300), scale_boxes to the photo, process_mask_native at photo
                 resolution, empty masks dropped
  sam_results    SAM's postprocess_masks: bilinear to 1024 x 1024, crop to the
                 valid extent, bilinear to the photo, > 0
bilinear() follows PyTorch's CPU upsample_bilinear2d (align_corners=False):
float32 source index max(scale * (i + 0.5) - 0.5, 0), index clamped, weights
(1 - l, l), width interpolated first, then height. Masks are encoded
compactly (encode_mask / decode_mask): cropped to the mask's own bounding box,
as row-major run lengths or bit-packed rows, whichever is smaller."""
import base64
import math

import numpy as np

CONF, IOU, MAX_DET, MAX_NMS = 0.25, 0.7, 300, 30000


def _taps(in_size, out_size, scale):
    real = np.maximum(np.float32(scale) * (np.arange(out_size, dtype=np.float32) + np.float32(0.5)) - np.float32(0.5), np.float32(0))
    i0 = np.minimum(np.floor(real).astype(np.int64), in_size - 1)
    lam = np.clip(real - i0.astype(np.float32), np.float32(0), np.float32(1)).astype(np.float32)
    i1 = i0 + (i0 < in_size - 1)
    return i0, i1, (np.float32(1) - lam).astype(np.float32), lam


def bilinear(x, out_h, out_w, scale_h=None, scale_w=None, rows=None, cols=None):
    """x float32 [N, H, W] -> [N, out_h, out_w] (or only the given output
    row/column ranges). scale = 1 / scale_factor when interpolating by a
    factor, else in / out, as PyTorch computes them."""
    n, h, w = x.shape
    sh = np.float32(scale_h) if scale_h is not None else np.float32(h) / np.float32(out_h)
    sw = np.float32(scale_w) if scale_w is not None else np.float32(w) / np.float32(out_w)
    y0, y1, wy0, wy1 = _taps(h, out_h, sh)
    x0, x1, wx0, wx1 = _taps(w, out_w, sw)
    if rows is not None:
        y0, y1, wy0, wy1 = (a[rows[0]:rows[1]] for a in (y0, y1, wy0, wy1))
    if cols is not None:
        x0, x1, wx0, wx1 = (a[cols[0]:cols[1]] for a in (x0, x1, wx0, wx1))
    top = x[:, y0][:, :, x0] * wx0 + x[:, y0][:, :, x1] * wx1
    bot = x[:, y1][:, :, x0] * wx0 + x[:, y1][:, :, x1] * wx1
    return (top * wy0[:, None] + bot * wy1[:, None]).astype(np.float32)


def _nms(boxes, scores, iou):
    """Greedy NMS as torchvision.ops.nms: highest score first, suppress
    IoU > iou."""
    x1, y1, x2, y2 = boxes.T
    areas = (x2 - x1) * (y2 - y1)
    order = np.argsort(-scores, kind="stable")
    keep = []
    while order.size:
        i = order[0]; keep.append(i)
        rest = order[1:]
        w = np.clip(np.minimum(x2[i], x2[rest]) - np.maximum(x1[i], x1[rest]), 0, None)
        h = np.clip(np.minimum(y2[i], y2[rest]) - np.maximum(y1[i], y1[rest]), 0, None)
        inter = w * h
        order = rest[inter / (areas[i] + areas[rest] - inter) <= iou]
    return np.array(keep, np.int64)


def _scale_boxes(boxes, size, shape):
    """Ultralytics scale_boxes from the size x size letterbox to the photo, clipped."""
    h0, w0 = shape
    gain = min(size / h0, size / w0)
    nh, nw = max(round(h0 * gain), 1), max(round(w0 * gain), 1)
    gy, gx = nh / h0, nw / w0
    px, py = round((size - nw) / 2 - 0.1), round((size - nh) / 2 - 0.1)
    b = boxes.copy()
    b[:, [0, 2]] -= px; b[:, [1, 3]] -= py
    b[:, [0, 2]] /= gx; b[:, [1, 3]] /= gy
    b[:, [0, 2]] = b[:, [0, 2]].clip(0, w0); b[:, [1, 3]] = b[:, [1, 3]].clip(0, h0)
    return b


def yoloe_results(boxes, score, cls, coef, protos, shape, size=640):
    """Raw YOLOE outputs (boxes [1,4,8400] cx,cy,w,h; score, cls [1,8400];
    coef [1,32,8400]; protos [1,32,160,160] or NHWC) for a size x size
    letterbox of a photo of `shape` (h, w) -> (xyxy [N,4] in photo pixels,
    scores [N], class ids [N], masks: list of bool arrays [h, w] cropped to
    their boxes)."""
    sc = score.reshape(-1)
    keep = np.nonzero(sc > CONF)[0]
    if keep.size > MAX_NMS:
        keep = keep[np.argsort(-sc[keep], kind="stable")[:MAX_NMS]]
    b = boxes.reshape(4, -1)[:, keep].T.astype(np.float32)
    xyxy = np.concatenate([b[:, :2] - b[:, 2:] / 2, b[:, :2] + b[:, 2:] / 2], 1)
    k = _nms(xyxy, sc[keep], IOU)[:MAX_DET]
    idx = keep[k]
    xyxy, conf, cid = xyxy[k], sc[idx].astype(np.float32), cls.reshape(-1)[idx].astype(np.int64)
    if not len(idx):
        return xyxy, conf, cid, []
    xyxy = _scale_boxes(xyxy, size, shape)
    p = protos[0] if protos.shape[1] == 32 else protos[0].transpose(2, 0, 1)   # CHW
    c, mh, mw = p.shape
    logits = (coef.reshape(c, -1)[:, idx].T.astype(np.float32) @ p.reshape(c, -1).astype(np.float32)).reshape(-1, mh, mw)
    h, w = shape
    gain = min(4 * mh / h, 4 * mw / w)
    pad = (4 * mh - max(round(h * gain), 1)) | (4 * mw - max(round(w * gain), 1))
    f = 4 // math.gcd(4, pad | pad // 2)
    m1h, m1w = mh * f, mw * f
    g2 = min(m1h / h, m1w / w)
    pw, ph = (m1w - max(round(w * g2), 1)) / 2, (m1h - max(round(h * g2), 1)) / 2
    top, left = round(ph - 0.1), round(pw - 0.1)
    bottom, right = top + max(round(h * g2), 1), left + max(round(w * g2), 1)
    masks, kept = [], []
    for j in range(len(idx)):
        up = bilinear(logits[j:j + 1], m1h, m1w, scale_h=1.0 / f, scale_w=1.0 / f) if f > 1 else logits[j:j + 1]
        crop = up[:, top:bottom, left:right]
        # only the box's pixels survive crop_mask: interpolate just those
        x1, y1, x2, y2 = xyxy[j]
        r0, r1 = int(np.clip(np.ceil(y1), 0, h)), int(np.clip(np.ceil(y2), 0, h))
        c0, c1 = int(np.clip(np.ceil(x1), 0, w)), int(np.clip(np.ceil(x2), 0, w))
        m = np.zeros((h, w), bool)
        if r1 > r0 and c1 > c0:
            m[r0:r1, c0:c1] = bilinear(crop, h, w, rows=(r0, r1), cols=(c0, c1))[0] > 0
        if m.any():
            masks.append(m); kept.append(j)
    kept = np.array(kept, np.int64)
    return xyxy[kept], conf[kept], cid[kept], masks


def _fed(in_size, out_size, scale, lo, hi):
    """Output index range [a, b) whose bilinear taps touch source [lo, hi)."""
    i0, i1, _, _ = _taps(in_size, out_size, scale)
    hit = np.flatnonzero(((i0 >= lo) & (i0 < hi)) | ((i1 >= lo) & (i1 < hi)))
    return (int(hit[0]), int(hit[-1]) + 1) if hit.size else (0, 0)


def sam_masks(logits, input_size, original_size, target=1024):
    """Low-res mask logits [N, 256, 256] -> bool masks [N, h, w] (SAM's
    postprocess_masks, > 0). Exact shortcut: bilinear weights are
    non-negative, so an output pixel can only be positive if a source pixel
    it reads is positive; both resizes are computed only over the region the
    positive low-res cells feed (everything else is <= 0), which matters on
    large photos."""
    (ih, iw), (oh, ow) = input_size, original_size
    n, lh, lw = logits.shape
    s1h, s1w = np.float32(lh) / np.float32(target), np.float32(lw) / np.float32(target)
    s2h, s2w = np.float32(ih) / np.float32(oh), np.float32(iw) / np.float32(ow)
    out = np.zeros((n, oh, ow), bool)
    for j in range(n):
        ys, xs = np.nonzero(logits[j] > 0)
        if not ys.size:
            continue
        r1 = _fed(lh, target, s1h, ys.min(), ys.max() + 1); c1 = _fed(lw, target, s1w, xs.min(), xs.max() + 1)
        r1 = (r1[0], min(r1[1], ih)); c1 = (c1[0], min(c1[1], iw))   # crop to the valid extent
        if r1[1] <= r1[0] or c1[1] <= c1[0]:
            continue
        r2 = _fed(ih, oh, s2h, *r1); c2 = _fed(iw, ow, s2w, *c1)
        # stage 1 over the rows/columns stage 2 reads (a superset of r1/c1 is harmless: exact values)
        y0, y1, _, _ = _taps(ih, oh, s2h); x0, x1, _, _ = _taps(iw, ow, s2w)
        ra = (int(min(y0[r2[0]:r2[1]].min(), y1[r2[0]:r2[1]].min())), int(max(y0[r2[0]:r2[1]].max(), y1[r2[0]:r2[1]].max())) + 1)
        ca = (int(min(x0[c2[0]:c2[1]].min(), x1[c2[0]:c2[1]].min())), int(max(x0[c2[0]:c2[1]].max(), x1[c2[0]:c2[1]].max())) + 1)
        big = np.zeros((1, ih, iw), np.float32)
        big[:, ra[0]:ra[1], ca[0]:ca[1]] = bilinear(logits[j:j + 1].astype(np.float32), target, target, rows=ra, cols=ca)
        out[j, r2[0]:r2[1], c2[0]:c2[1]] = bilinear(big, oh, ow, rows=r2, cols=c2)[0] > 0
    return out


def encode_mask(m):
    """bool [h, w] -> {"bbox": [x0, y0, x1, y1] (end-exclusive), "rle": [...]}
    or {..., "bits": base64} -- whichever is smaller. rle: row-major run
    lengths inside the bbox, starting with a run of zeros; bits: row-major
    np.packbits (big-endian bit order) of the bbox crop."""
    ys, xs = np.nonzero(m)
    if not ys.size:
        return {"bbox": [0, 0, 0, 0], "rle": []}
    y0, y1, x0, x1 = int(ys.min()), int(ys.max()) + 1, int(xs.min()), int(xs.max()) + 1
    crop = m[y0:y1, x0:x1].reshape(-1)
    change = np.flatnonzero(np.diff(crop.astype(np.int8))) + 1
    edges = np.concatenate([[0], change, [crop.size]])
    runs = np.diff(edges).tolist()
    if crop[0]:
        runs = [0] + runs
    bits = base64.b64encode(np.packbits(crop).tobytes()).decode()
    rle_len = sum(len(str(r)) + 1 for r in runs)
    out = {"bbox": [x0, y0, x1, y1]}
    if rle_len <= len(bits):
        out["rle"] = runs
    else:
        out["bits"] = bits
    return out


def decode_mask(enc, shape):
    """The inverse of encode_mask, onto a full [h, w] bool array."""
    x0, y0, x1, y1 = enc["bbox"]
    m = np.zeros(shape, bool)
    n = (y1 - y0) * (x1 - x0)
    if n == 0:
        return m
    if "rle" in enc:
        vals = np.zeros(n, bool); pos = 0; v = False
        for r in enc["rle"]:
            vals[pos:pos + r] = v; pos += r; v = not v
    else:
        vals = np.unpackbits(np.frombuffer(base64.b64decode(enc["bits"]), np.uint8))[:n].astype(bool)
    m[y0:y1, x0:x1] = vals.reshape(y1 - y0, x1 - x0)
    return m
