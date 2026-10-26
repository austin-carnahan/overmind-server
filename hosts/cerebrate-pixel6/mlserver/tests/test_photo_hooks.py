"""Photo hooks' host-side postprocessing against the previous implementations:
mask upsampling in strips (post.bilinear_rows) gives the same masks as the
whole-photo float32 upsampling it replaced (EfficientSAM3 end to end, with a
fake worker); the block-wise EfficientSAM3 resize and the sampled-only OWLv2
preprocessing bit-identical to the whole-photo versions (kept here as
references); and MI-GAN's window around the hole -- the right window, the
photo untouched outside it, and the whole-photo pipeline unchanged with
window=false or on a photo smaller than the window. Needs numpy, Pillow and
OpenCV (the guest's MLServer environment); mlserver itself is stubbed:
  python3 -m unittest discover -s hosts/cerebrate-pixel6/mlserver/tests -v"""
import asyncio
import base64
import io
import json
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "models" / "cerebrate-graph"))
if "mlserver" not in sys.modules:   # only NumpyCodec.decode_input is used, on an INT64 input
    codecs = types.ModuleType("mlserver.codecs")
    codecs.NumpyCodec = SimpleNamespace(decode_input=lambda i: np.array(i.data))
    sys.modules["mlserver"] = types.ModuleType("mlserver")
    sys.modules["mlserver.codecs"] = codecs
import model_hooks  # noqa: E402
import photo_postprocess as post  # noqa: E402
import photo_preprocess as pp  # noqa: E402


def png(array) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(array).save(buf, format="PNG")
    return buf.getvalue()


def bytes_input(data: bytes):
    return SimpleNamespace(data=[base64.b64encode(data).decode()], datatype="BYTES")


def sig(x):
    return (np.float32(1) / (np.float32(1) + np.exp(-x.astype(np.float32)))).astype(np.float32)


class BilinearRows(unittest.TestCase):
    def test_same_values_as_bilinear(self):
        x = np.random.default_rng(0).normal(size=(2, 13, 17)).astype(np.float32)
        full = post.bilinear(x, 301, 401)
        for rows in (1, 37, 256, 1000):
            self.assertTrue(np.array_equal(post.bilinear_rows(x, 301, 401, lambda v: v, rows), full))
            self.assertTrue(np.array_equal(post.bilinear_rows(x, 301, 401, lambda v: v > 0, rows), full > 0))


# ---- the previous whole-photo preprocessing, as references ----
def previous_torchvision_resize_u8(rgb, out_h, out_w):
    x = rgb.astype(np.float64)
    for axis, size in ((1, out_w), (0, out_h)):
        m, p = pp._aa_weights(x.shape[axis], size)
        acc = np.tensordot(m, np.moveaxis(x, axis, 0), axes=(1, 0))
        x = np.moveaxis(np.clip(np.floor((acc + (1 << (p - 1))) / (1 << p)), 0, 255), 0, axis)
    return x.astype(np.uint8)


def previous_gaussian_filter1d(x, sigma, axis):
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
        out += wk * xm[pp._mirror(np.arange(n) + k - radius, n)]
    return np.moveaxis(out, 0, axis).astype(x.dtype)


def previous_zoom_linear(x, out_shape):
    y0, y1, wy0, wy1 = pp._zoom_taps(x.shape[0], out_shape[0])
    x0, x1, wx0, wx1 = pp._zoom_taps(x.shape[1], out_shape[1])
    xd = x.astype(np.float64)
    a, b = xd[y0], xd[y1]
    out = (wy0[:, None, None] * (wx0[None, :, None] * a[:, x0] + wx1[None, :, None] * a[:, x1])
           + wy1[:, None, None] * (wx0[None, :, None] * b[:, x0] + wx1[None, :, None] * b[:, x1]))
    return out.astype(np.float32)


def previous_owlv2_pixels(rgb, size=960):
    x = (rgb.astype(np.float64) * (1 / 255)).astype(np.float32)
    h, w = x.shape[:2]
    s = max(h, w)
    x = np.pad(x, ((0, s - h), (0, s - w), (0, 0)))
    sigma = max((s / size - 1) / 2, 0.0)
    f = x
    if sigma > 0:
        f = previous_gaussian_filter1d(previous_gaussian_filter1d(x, sigma, 0), sigma, 1)
    out = np.clip(previous_zoom_linear(f, (size, size)), x.min(), x.max())
    out = (out - pp.OWLV2_MEAN) / pp.OWLV2_STD
    return np.ascontiguousarray(out.transpose(2, 0, 1))[None].astype(np.float32)


class Preprocessing(unittest.TestCase):
    def test_torchvision_resize_bit_identical(self):
        rng = np.random.default_rng(4)
        for h, w, oh, ow in ((700, 1100, 1008, 1008), (1300, 900, 1008, 1008), (300, 200, 64, 48)):
            rgb = rng.integers(0, 255, (h, w, 3), dtype=np.uint8)
            for block in (1, 77, 256):
                self.assertTrue(np.array_equal(pp.torchvision_resize_u8(rgb, oh, ow, block), previous_torchvision_resize_u8(rgb, oh, ow)))

    def test_owlv2_pixels_bit_identical(self):
        rng = np.random.default_rng(5)
        # downscaled (blur on, sigma >= 0.5), portrait and landscape, exactly square, and upscaled (no blur)
        for h, w, size in ((1500, 2100, 960), (2100, 1400, 960), (1200, 1200, 960), (500, 700, 960), (90, 130, 32)):
            rgb = rng.integers(0, 255, (h, w, 3), dtype=np.uint8)
            rgb[0, 0] = 7                      # a photo whose minimum isn't 0
            self.assertTrue(np.array_equal(pp.owlv2_pixels(rgb, size), previous_owlv2_pixels(rgb, size)), (h, w, size))


class Esam3Masks(unittest.TestCase):
    def test_masks_identical_to_whole_photo_upsampling(self):
        rng = np.random.default_rng(1)
        h, w = 300, 400
        photo = png(rng.integers(0, 255, (h, w, 3), dtype=np.uint8))
        logits = np.full(200, -9.0, np.float32)
        logits[[3, 17, 90]] = 4.0                                   # three instances pass the threshold
        out = {"logits": logits, "boxes": rng.uniform(0.2, 0.6, (200, 4)).astype(np.float32),
               "presence": np.array([3.0], np.float32), "masks": rng.normal(size=(200, 288, 288)).astype(np.float32)}

        async def call(feed):
            return (out, {"prompt_us": 1}) if "ids" in feed else ({}, {"inference_us": 1})
        inputs = {"photo": bytes_input(photo), "image_id": SimpleNamespace(data=[42], datatype="INT64"),
                  "prompts": SimpleNamespace(data=[b"lamp"], datatype="BYTES")}
        result, _ = asyncio.run(model_hooks.Esam3Hooks().run(inputs, None, call))
        dets = json.loads(result["result"])["prompts"][0]["detections"]
        keep = np.where(sig(logits) * sig(out["presence"])[0] > 0.5)[0]
        ref = sig(post.bilinear(out["masks"][keep], h, w)) > 0.5    # the previous implementation
        self.assertEqual(len(dets), 3)
        for d, m in zip(dets, ref):
            self.assertTrue(np.array_equal(post.decode_mask(d["mask"], (h, w)), m))


class MiganWindow(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(2)
        self.big = rng.integers(0, 255, (700, 900, 3), dtype=np.uint8)
        self.mask = np.zeros((700, 900), np.uint8)
        self.mask[600:640, 800:860] = 255

    @staticmethod
    def previous(rgb, mask, g):
        """The whole-photo pipeline as it was: (net, output)."""
        h, w = rgb.shape[:2]
        S = 512
        keep = np.where(mask >= 128, 0, 255).astype(np.uint8)
        small = np.round(post.bilinear(rgb.transpose(2, 0, 1).astype(np.float32), S, S)).astype(np.uint8)
        keep_s = keep[model_hooks._nearest_floor(h, S)][:, model_hooks._nearest_floor(w, S)]
        x = small.astype(np.float32) * np.float32(2) / np.float32(255) - np.float32(1)
        k = keep_s.astype(np.float32) / np.float32(255)
        net = np.concatenate([(k - np.float32(0.5))[None], x * k[None]])[None].astype(np.float32)
        gg = np.clip((g.reshape(3, S, S) * np.float32(0.5) + np.float32(0.5)) * np.float32(255), 0, 255)
        up = post.bilinear(gg, h, w)
        kk = keep.astype(np.float32) / np.float32(255)
        out = np.clip(rgb.transpose(2, 0, 1).astype(np.float32) * kk + up * (np.float32(1) - kk), 0, 255).astype(np.uint8)
        return net, out.transpose(1, 2, 0)

    def run_hook(self, rgb, mask, params, g):
        hooks = model_hooks.MiganHooks()
        feed, ctx = hooks.prepare({"photo": bytes_input(png(rgb)), "mask": bytes_input(png(mask))}, params)
        doc = json.loads(hooks.finish({"image": g}, ctx)["result"])
        out = np.asarray(Image.open(io.BytesIO(base64.b64decode(doc["result"]))).convert("RGB"))
        return feed["masked_image"], out, doc

    def test_window_around_the_hole(self):
        g = np.zeros((1, 3, 512, 512), np.float32)                  # the fill: mid grey
        net, out, doc = self.run_hook(self.big, self.mask, None, g)
        self.assertEqual(net.shape, (1, 4, 512, 512))
        self.assertEqual(doc["window"], [388, 188, 900, 700])
        self.assertEqual(doc["window"], list(post.inpaint_window((900, 700), (800, 600, 860, 640))))
        hole = self.mask >= 128
        self.assertTrue(np.array_equal(out[~hole], self.big[~hole]))   # everything but the hole as sent
        self.assertTrue((out[hole] == 127).all())

    def test_whole_photo_pipeline_kept(self):
        g = np.random.default_rng(3).uniform(-1, 1, (1, 3, 512, 512)).astype(np.float32)
        ref_net, ref_out = self.previous(self.big, self.mask, g)
        net, out, doc = self.run_hook(self.big, self.mask, SimpleNamespace(window="false", model_extra=None), g)
        self.assertTrue(np.array_equal(net, ref_net) and np.array_equal(out, ref_out))
        self.assertEqual(doc["window"], [0, 0, 900, 700])
        small, small_mask = self.big[:300, :400], self.mask[:300, :400].copy()
        small_mask[100:140, 200:260] = 255
        ref_net, ref_out = self.previous(small, small_mask, g)      # a photo under 512 px is its own window
        net, out, _ = self.run_hook(small, small_mask, None, g)
        self.assertTrue(np.array_equal(net, ref_net) and np.array_equal(out, ref_out))


if __name__ == "__main__":
    unittest.main()
