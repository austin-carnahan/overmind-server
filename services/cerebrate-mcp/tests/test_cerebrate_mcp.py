"""Cerebrate MCP against a fake MLServer (real V2 REST shapes, a settable
repository index) and a temporary copy of the real model registry, through
FastMCP's in-memory client: tool discovery, capability derivation (registry
x readiness x contracts), staged/unready exclusion, a newly registered model
appearing with no code change, target resolution, request/response mapping
for segment_region, artifacts, polygons, signed artifact URLs, the inpaint
window and patch, scaled-down text segmentation, and error reporting.
  cd services/cerebrate-mcp && python -m unittest discover -s tests -v"""
import asyncio
import base64
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import yaml
from PIL import Image

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(REPO / "hosts/cerebrate-pixel6/mlserver/models/cerebrate-graph"))
import photo_postprocess as post  # noqa: E402
from fastmcp import Client  # noqa: E402
from fastmcp.exceptions import ToolError  # noqa: E402

W, H = 64, 48
FILL = (200, 50, 50)


def png(array) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(array).save(buf, format="PNG")
    return buf.getvalue()


PHOTO = png(np.random.default_rng(0).integers(0, 255, (H, W, 3), dtype=np.uint8))


def jpeg(array) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(array).save(buf, format="JPEG")
    return buf.getvalue()


def box_mask(box):
    m = np.zeros((H, W), bool)
    x0, y0, x1, y1 = [int(v) for v in box]
    m[y0:y1, x0:x1] = True
    return m


class FakeMLServer(BaseHTTPRequestHandler):
    states: dict = {}
    requests: list = []
    seen_sizes: list = []
    fail_with: str | None = None

    def log_message(self, *args):
        pass

    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
        if self.path == "/v2/repository/index":
            return self._send(200, [{"name": n, "version": "v0.1.0", "state": s, "reason": ""} for n, s in self.states.items()])
        endpoint = self.path.split("/")[3]
        FakeMLServer.requests.append((endpoint, body))
        if FakeMLServer.fail_with:
            return self._send(400, {"error": FakeMLServer.fail_with})
        inputs = {i["name"]: i for i in body["inputs"]}
        image = {"width": W, "height": H}
        if "boxes" in inputs:
            flat = inputs["boxes"]["data"]
            boxes = [flat[i:i + 4] for i in range(0, len(flat), 4)]
            doc = {"image": image, "image_id": inputs["image_id"]["data"][0],
                   "masks": [{"box": b, "score": 0.9, "mask": post.encode_mask(box_mask(b))} for b in boxes]}
        elif "mask" in inputs:      # "inpaint": the sent photo with the masked pixels painted FILL
            photo = np.array(Image.open(io.BytesIO(base64.b64decode(inputs["photo"]["data"][0]))).convert("RGB"))
            hole = np.asarray(Image.open(io.BytesIO(base64.b64decode(inputs["mask"]["data"][0])))) >= 128
            photo[hole] = FILL
            doc = {"image": {"width": photo.shape[1], "height": photo.shape[0]}, "encoding": "png",
                   "result": base64.b64encode(png(photo)).decode()}
        elif "prompts" in inputs:   # one instance per phrase: the photo's central quarter
            ph = Image.open(io.BytesIO(base64.b64decode(inputs["photo"]["data"][0])))
            w, h = ph.size
            FakeMLServer.seen_sizes.append((w, h))
            box = [w // 4, h // 4, 3 * w // 4, 3 * h // 4]
            m = np.zeros((h, w), bool)
            m[box[1]:box[3], box[0]:box[2]] = True
            doc = {"image": {"width": w, "height": h}, "image_id": inputs["image_id"]["data"][0],
                   "prompts": [{"text": t, "presence": 0.9, "detections": [{"box": box, "score": 0.8, "mask": post.encode_mask(m)}]}
                               for t in inputs["prompts"]["data"]]}
        elif endpoint.startswith("depth") or endpoint.startswith("test-depth"):
            d = base64.b64encode(png(np.zeros((8, 8), np.uint16))).decode()
            doc = {"image": image, "depth": {"width": 8, "height": 8, "encoding": "png16", "min": 0.0, "max": 1.0, "data": d}}
        else:
            doc = {"image": image, "detections": [{"box": [1, 2, 10, 12], "score": 0.8, "class_id": 1, "label": "thing",
                                                   "mask": post.encode_mask(box_mask([1, 2, 10, 12]))}]}
        self._send(200, {"model_name": endpoint, "outputs": [{"name": "result", "datatype": "BYTES", "shape": [1], "data": [json.dumps(doc)]}]})


class CerebrateMCP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeMLServer)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.registry = Path(self.tmp) / "models"
        shutil.copytree(REPO / "models", self.registry, ignore=shutil.ignore_patterns("tests", "__pycache__"))
        os.environ.update({
            "CEREBRATE_MCP_MLSERVER_URL": f"http://127.0.0.1:{self.httpd.server_port}",
            "CEREBRATE_MCP_REGISTRY_DIR": str(self.registry),
            "CEREBRATE_MCP_ARTIFACT_DIR": str(Path(self.tmp) / "artifacts"),
        })
        catalog = yaml.safe_load((self.registry / "catalog.yaml").read_text())
        FakeMLServer.states = {m["serving"]["mlserver_model"]: "READY" for m in catalog["models"].values()
                               if (m.get("serving") or {}).get("mlserver_model")}
        FakeMLServer.states.update({"cerebrate-infer": "READY", "cerebrate-generate": "READY"})
        FakeMLServer.requests, FakeMLServer.fail_with, FakeMLServer.seen_sizes = [], None, []
        for k in ("CEREBRATE_MCP_PUBLIC_URL", "CEREBRATE_MCP_TEXT_SEG_MAX_SIDE"):
            os.environ.pop(k, None)
        from cerebrate_mcp.server import create_app
        self.app = create_app()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def call(self, tool, **args):
        async def go():
            async with Client(self.app) as c:
                return (await c.call_tool(tool, args)).data
        return asyncio.run(go())

    def edit(self, name, fn):
        p = self.registry / name
        doc = yaml.safe_load(p.read_text())
        fn(doc)
        p.write_text(yaml.safe_dump(doc, sort_keys=False))

    def expected_endpoints(self):
        """Independently of the server: production variants with an endpoint
        whose model's interface is one the adapter implements."""
        from cerebrate_mcp.contracts import CONTRACTS
        cat = yaml.safe_load((self.registry / "catalog.yaml").read_text())
        var = yaml.safe_load((self.registry / "variants.yaml").read_text())
        out = set()
        for ref, v in var["variants"].items():
            m = cat["models"][ref.split("/")[0]]
            ep = (v.get("serving") or {}).get("mlserver_model")
            if v["status"] == "production" and ep and (m.get("serving") or {}).get("interface") in CONTRACTS \
                    and FakeMLServer.states.get(ep) == "READY":
                out.add(ep)
        return out

    def test_tool_discovery(self):
        async def go():
            async with Client(self.app) as c:
                return {t.name for t in await c.list_tools()}, [t.uri_template for t in await c.list_resource_templates()]
        tools, templates = asyncio.run(go())
        self.assertEqual(tools, {"list_capabilities", "segment_region", "detect_objects", "segment_by_text",
                                 "detect_by_text", "estimate_depth", "inpaint", "embed_image"})
        self.assertEqual(templates, ["artifact://{run}/{name}"])

    def test_capabilities_match_registry_and_readiness(self):
        caps = self.call("list_capabilities")
        listed = {m["endpoint"] for m in caps["models"]}
        self.assertEqual(listed, self.expected_endpoints())
        self.assertIn("edgesam3x-box", listed)
        for excluded in ("cerebrate-infer", "cerebrate-generate", "cerebrate-gguf"):   # no photo contract
            self.assertNotIn(excluded, listed)
        box = next(t for t in caps["tasks"] if t["task"] == "box-refinement")
        self.assertEqual(box["tool"], "segment_region")
        self.assertEqual(box["selections"]["default"]["endpoint"], "edgesam3x-box")
        self.assertEqual(box["selections"]["quality"]["endpoint"], "sam2.1-hiera-tiny")
        self.assertNotIn("fallback", box["selections"])      # EdgeSAM FP32 has no endpoint of its own
        self.assertTrue(caps["tools"]["segment_region"]["available"])

    def test_unready_and_staged_configurations_are_excluded(self):
        FakeMLServer.states["owlv2-b16"] = "UNAVAILABLE"
        self.edit("variants.yaml", lambda v: v["variants"]["mi-gan-512/gpu-fp16"].update(status="staged"))
        caps = self.call("list_capabilities")
        listed = {m["endpoint"] for m in caps["models"]}
        self.assertNotIn("owlv2-b16", listed)
        self.assertNotIn("mi-gan-512", listed)
        self.assertFalse(caps["tools"]["detect_by_text"]["available"])
        self.assertFalse(caps["tools"]["inpaint"]["available"])
        with self.assertRaisesRegex(ToolError, "not loaded"):
            self.call("detect_by_text", image=base64.b64encode(PHOTO).decode(), queries=["a bed"])

    def test_newly_registered_model_appears_without_code_changes(self):
        def add_model(cat):
            m = json.loads(json.dumps(cat["models"]["depth-anything-v2-small"]))
            m["serving"]["mlserver_model"] = "test-depth-xl"
            cat["models"]["test-depth-xl"] = m

        def add_variant(var):
            v = json.loads(json.dumps(var["variants"]["depth-anything-v2-small/gpu-fp16acc32"]))
            v["serving"]["mlserver_model"] = "test-depth-xl"
            var["variants"]["test-depth-xl/gpu-fp16acc32"] = v
        self.edit("catalog.yaml", add_model)
        self.edit("variants.yaml", add_variant)
        FakeMLServer.states["test-depth-xl"] = "READY"
        caps = self.call("list_capabilities")
        self.assertIn("test-depth-xl", {m["endpoint"] for m in caps["models"]})
        self.assertIn("test-depth-xl", caps["tools"]["estimate_depth"]["endpoints"])
        out = self.call("estimate_depth", image=base64.b64encode(PHOTO).decode(), target="test-depth-xl")
        self.assertEqual(out["endpoint"], "test-depth-xl")
        self.assertEqual(FakeMLServer.requests[-1][0], "test-depth-xl")

    def test_segment_region_request_and_result(self):
        boxes = [[4, 5, 30, 20], [10, 10, 60, 40]]
        out = self.call("segment_region", image="data:image/png;base64," + base64.b64encode(PHOTO).decode(), boxes=boxes)
        endpoint, body = FakeMLServer.requests[-1]
        self.assertEqual(endpoint, "edgesam3x-box")
        inputs = {i["name"]: i for i in body["inputs"]}
        self.assertEqual(base64.b64decode(inputs["photo"]["data"][0]), PHOTO)
        self.assertEqual((inputs["image_id"]["datatype"], inputs["image_id"]["shape"]), ("INT64", [1]))
        self.assertEqual((inputs["boxes"]["datatype"], inputs["boxes"]["shape"]), ("FP32", [2, 4]))
        self.assertEqual(inputs["boxes"]["data"], [float(v) for b in boxes for v in b])
        self.assertEqual((out["model"], out["variant"]), ("edgesam-3x", "edgesam-3x/tpu-fp16r-gpu-neck-fp32"))
        self.assertEqual(len(out["masks"]), 2)
        for b, m in zip(boxes, out["masks"]):
            saved = np.asarray(Image.open(m["mask_png"]["path"])) > 0
            self.assertTrue(np.array_equal(saved, box_mask(b)))
            self.assertTrue(np.array_equal(post.decode_mask(m["mask"], (H, W)), box_mask(b)))
        # the artifact is readable as an MCP resource, and usable as the next call's mask input
        async def read():
            async with Client(self.app) as c:
                return await c.read_resource(out["masks"][0]["mask_png"]["uri"])
        blob = asyncio.run(read())[0].blob
        self.assertEqual(base64.b64decode(blob), Path(out["masks"][0]["mask_png"]["path"]).read_bytes())
        res = self.call("inpaint", image=base64.b64encode(PHOTO).decode(), mask=out["masks"][0]["mask_png"]["uri"])
        sent = {i["name"]: i for i in FakeMLServer.requests[-1][1]["inputs"]}
        grown = np.asarray(Image.open(io.BytesIO(base64.b64decode(sent["mask"]["data"][0])))) > 0
        expected = box_mask([0, 0, 30 + 7, 20 + 7])    # the (4, 5, 30, 20) box grown 7 px, clipped at the image edge
        self.assertTrue(np.array_equal(grown, expected))  # a 64x48 photo is its own window
        # the patch: the grown mask's bounds, alpha = the grown mask, the fill inside
        self.assertEqual((res["offset"], res["size"], res["window"]), ([0, 0], [37, 27], [0, 0, W, H]))
        patch = np.asarray(Image.open(res["patch"]["path"]))
        self.assertEqual(patch.shape, (27, 37, 4))
        self.assertTrue(np.array_equal(patch[..., 3] > 0, expected[:27, :37]))
        self.assertTrue((patch[..., :3][expected[:27, :37]] == FILL).all())
        self.assertNotIn("result_png", res)
        # the context: the photo around the fill (bounds + 6 px), alpha 0 over the grown mask
        self.assertEqual(res["context"]["offset"], [0, 0])
        ctxim = np.asarray(Image.open(res["context"]["path"]))
        self.assertEqual(ctxim.shape, (27 + 6, 37 + 6, 4))
        self.assertTrue(np.array_equal(ctxim[..., 3] == 0, expected[:33, :43]))
        photo = np.asarray(Image.open(io.BytesIO(PHOTO)).convert("RGB"))
        self.assertTrue(np.array_equal(ctxim[..., :3], photo[:33, :43]))

    def test_polygons_rebuild_the_mask(self):
        """Rings replayed as an editor would (replace, add, subtract; a pixel
        is in a ring when its centre is) give back exactly the mask -- an
        outer ring with a hole, an island inside the hole, a separate blob."""
        import cv2
        from cerebrate_mcp.contracts import mask_polygons
        m = np.zeros((H, W), bool)
        m[4:40, 4:40] = True
        m[12:32, 12:32] = False
        m[18:26, 18:26] = True
        m[10:20, 48:60] = True
        rings = mask_polygons(post, post.encode_mask(m))
        self.assertEqual([r["hole"] for r in rings], [False, True, False, False])
        self.assertEqual(rings[0]["points"], [4, 4, 4, 40, 40, 40, 40, 4])   # pixel corners
        sel = np.zeros((H, W), bool)
        yy, xx = np.mgrid[0:H, 0:W]
        for k, r in enumerate(rings):
            poly = np.array(r["points"], np.float32).reshape(-1, 1, 2)
            inside = np.array([cv2.pointPolygonTest(poly, (float(x) + 0.5, float(y) + 0.5), False) > 0
                               for x, y in zip(xx.ravel(), yy.ravel())]).reshape(H, W)
            sel = (sel & ~inside) if r["hole"] else (inside if k == 0 else sel | inside)
        self.assertTrue(np.array_equal(sel, m))
        out = self.call("detect_objects", image=base64.b64encode(PHOTO).decode())
        self.assertEqual(out["detections"][0]["polygons"], [{"hole": False, "points": [1, 2, 1, 12, 10, 12, 10, 2]}])

    def test_artifact_urls(self):
        from starlette.testclient import TestClient
        os.environ["CEREBRATE_MCP_PUBLIC_URL"] = "http://artifacts.test"
        from cerebrate_mcp.server import create_app
        self.app = create_app()
        out = self.call("segment_region", image=base64.b64encode(PHOTO).decode(), boxes=[[4, 5, 30, 20]])
        ref = out["masks"][0]["mask_png"]
        self.assertTrue(ref["url"].startswith("http://artifacts.test/artifacts/"))
        self.assertTrue((Path(self.tmp) / "url-key").is_file())
        with TestClient(self.app.http_app()) as http:
            path = ref["url"][len("http://artifacts.test"):]
            r = http.get(path)
            self.assertEqual((r.status_code, r.headers["content-type"]), (200, "image/png"))
            self.assertEqual(r.content, Path(ref["path"]).read_bytes())
            self.assertEqual(http.get(path[:-1] + ("0" if path[-1] != "0" else "1")).status_code, 403)   # tampered
            other = path.replace("mask-0.png", "mask-1.png")
            self.assertEqual(http.get(other).status_code, 403)          # a signature covers one file
            run, name = path.split("?")[0].split("/")[2:4]
            expired = self.app_artifacts_sig(run, name, 1)
            self.assertEqual(http.get(f"/artifacts/{run}/{name}?exp=1&sig={expired}").status_code, 403)
        # the store's own URL is accepted as an input, read locally
        res = self.call("inpaint", image=base64.b64encode(PHOTO).decode(), mask=ref["url"])
        self.assertTrue(res["patch"]["url"].startswith("http://artifacts.test/artifacts/"))
        with self.assertRaisesRegex(ToolError, "invalid or expired"):
            self.call("inpaint", image=base64.b64encode(PHOTO).decode(), mask=ref["url"].replace("sig=", "sig=0"))

    def app_artifacts_sig(self, run, name, exp):
        import hashlib
        import hmac
        key = (Path(self.tmp) / "url-key").read_bytes()
        return hmac.new(key, f"{run}/{name}:{exp}".encode(), hashlib.sha256).hexdigest()[:32]

    def test_inpaint_window_and_composite(self):
        from cerebrate_mcp.contracts import inpaint_window
        self.assertEqual(inpaint_window((4000, 3000), (2165, 1384, 2272, 1552)), (1962, 1212, 2474, 1724))
        self.assertEqual(inpaint_window((4000, 3000), (3900, 2900, 4000, 3000)), (3488, 2488, 4000, 3000))  # clamped
        self.assertEqual(inpaint_window((4000, 3000), (1000, 1000, 2000, 1500)), (500, 250, 2500, 2250))   # 2x context
        self.assertEqual(inpaint_window((300, 200), (10, 10, 20, 20)), (0, 0, 300, 200))                  # small photo
        big = np.random.default_rng(1).integers(0, 255, (700, 900, 3), dtype=np.uint8)
        mask = np.zeros((700, 900), np.uint8)
        mask[600:640, 800:860] = 255
        res = self.call("inpaint", image=base64.b64encode(png(big)).decode(), mask=base64.b64encode(png(mask)).decode(),
                        grow_mask_px=0, composite=True)
        sent = {i["name"]: i for i in FakeMLServer.requests[-1][1]["inputs"]}
        self.assertEqual(Image.open(io.BytesIO(base64.b64decode(sent["photo"]["data"][0]))).size, (512, 512))
        self.assertEqual((res["offset"], res["size"], res["window"]), ([800, 600], [60, 40], [388, 188, 900, 700]))
        full = np.asarray(Image.open(res["result_png"]["path"]))
        expect = big.copy()
        expect[600:640, 800:860] = FILL
        self.assertTrue(np.array_equal(full, expect))

    def test_text_segmentation_scales_large_photos(self):
        os.environ["CEREBRATE_MCP_TEXT_SEG_MAX_SIDE"] = "32"
        from cerebrate_mcp.server import create_app
        self.app = create_app()
        out = self.call("segment_by_text", image=base64.b64encode(PHOTO).decode(), prompts=["lamp"])
        self.assertEqual(FakeMLServer.seen_sizes[-1], (32, 24))
        self.assertEqual((out["image"], out["segmented_at"]), ({"width": W, "height": H}, {"width": 32, "height": 24}))
        d = out["prompts"][0]["detections"][0]
        self.assertEqual(d["box"], [16.0, 12.0, 48.0, 36.0])
        self.assertEqual(d["polygons"][0]["points"], [16.0, 12.0, 16.0, 36.0, 48.0, 36.0, 48.0, 12.0])
        full = box_mask([16, 12, 48, 36])
        self.assertTrue(np.array_equal(post.decode_mask(d["mask"], (H, W)), full))
        self.assertTrue(np.array_equal(np.asarray(Image.open(d["mask_png"]["path"])) > 0, full))
        os.environ.pop("CEREBRATE_MCP_TEXT_SEG_MAX_SIDE")
        self.app = create_app()
        out = self.call("segment_by_text", image=base64.b64encode(PHOTO).decode(), prompts=["lamp"])
        self.assertEqual(FakeMLServer.seen_sizes[-1], (W, H))
        self.assertNotIn("segmented_at", out)

    def test_target_resolution(self):
        img = base64.b64encode(PHOTO).decode()
        self.assertEqual(self.call("segment_region", image=img, boxes=[[1, 1, 9, 9]], target="box-refinement@quality")["endpoint"],
                         "sam2.1-hiera-tiny")
        self.assertEqual(self.call("segment_region", image=img, boxes=[[1, 1, 9, 9]], target="edgesam-3x")["endpoint"], "edgesam3x-box")
        self.assertEqual(self.call("detect_objects", image=img, target="prompt-free-segmentation")["endpoint"], "yoloe-v8s-pf")
        with self.assertRaisesRegex(ToolError, "no MCP-callable endpoint"):
            self.call("segment_region", image=img, boxes=[[1, 1, 9, 9]], target="box-refinement@fallback")
        with self.assertRaisesRegex(ToolError, "use estimate_depth"):
            self.call("segment_region", image=img, boxes=[[1, 1, 9, 9]], target="relative-depth")
        with self.assertRaisesRegex(ToolError, "unknown target"):
            self.call("segment_region", image=img, boxes=[[1, 1, 9, 9]], target="no-such-model")

    def test_jpeg_base64_is_not_mistaken_for_a_path(self):
        photo = jpeg(np.full((H, W, 3), 128, np.uint8))
        img = base64.b64encode(photo).decode()
        self.assertTrue(img.startswith("/9j/"))
        self.call("segment_region", image=img, boxes=[[1, 1, 9, 9]])
        sent = {i["name"]: i for i in FakeMLServer.requests[-1][1]["inputs"]}
        self.assertEqual(base64.b64decode(sent["photo"]["data"][0]), photo)

    def test_errors_are_reported(self):
        img = base64.b64encode(PHOTO).decode()
        FakeMLServer.fail_with = "cerebrate-graph (edgesam3x-box): could not start hetero2: no capacity"
        with self.assertRaisesRegex(ToolError, "no capacity"):
            self.call("segment_region", image=img, boxes=[[1, 1, 9, 9]])
        FakeMLServer.fail_with = None
        with self.assertRaisesRegex(ToolError, "not base64"):
            self.call("segment_region", image="!!!", boxes=[[1, 1, 9, 9]])
        with self.assertRaisesRegex(ToolError, "outside the allowed input directories"):
            self.call("segment_region", image="/etc/hostname", boxes=[[1, 1, 9, 9]])
        with self.assertRaisesRegex(ToolError, "boxes"):
            self.call("segment_region", image=img, boxes=[[1, 2, 3]])


if __name__ == "__main__":
    unittest.main()
