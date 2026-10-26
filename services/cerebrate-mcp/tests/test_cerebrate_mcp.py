"""Cerebrate MCP against a fake MLServer (real V2 REST shapes, a settable
repository index) and a temporary copy of the real model registry, through
FastMCP's in-memory client: tool discovery, capability derivation (registry
x readiness x contracts), staged/unready exclusion, a newly registered model
appearing with no code change, target resolution, request/response mapping
for segment_region, artifacts, and error reporting.
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
        elif "mask" in inputs:
            doc = {"image": image, "encoding": "png", "result": base64.b64encode(PHOTO).decode()}
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
        FakeMLServer.requests, FakeMLServer.fail_with = [], None
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
                                 "detect_by_text", "estimate_depth", "remove_object", "embed_image"})
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
        self.assertFalse(caps["tools"]["remove_object"]["available"])
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
        res = self.call("remove_object", image=base64.b64encode(PHOTO).decode(), mask=out["masks"][0]["mask_png"]["uri"])
        self.assertTrue(Path(res["result_png"]["path"]).is_file())
        sent = {i["name"]: i for i in FakeMLServer.requests[-1][1]["inputs"]}
        grown = np.asarray(Image.open(io.BytesIO(base64.b64decode(sent["mask"]["data"][0])))) > 0
        expected = box_mask([0, 0, 30 + 7, 20 + 7])    # the (4, 5, 30, 20) box grown 7 px, clipped at the image edge
        self.assertTrue(np.array_equal(grown, expected))

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
