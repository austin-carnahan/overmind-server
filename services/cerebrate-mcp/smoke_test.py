"""Live smoke test of a running Cerebrate MCP server with the official MCP
Python SDK client (Streamable HTTP), against real MLServer and the Pixel:
  1. tool discovery;
  2. list_capabilities equals the registry's production endpoints with an
     MCP contract that MLServer reports READY (computed here independently);
  3. a real chain: detect_objects -> segment_region (EdgeSAM, the default
     box-refinement) on the photo's top detections;
  4. the MCP masks are identical to a direct MLServer call with the same
     inputs, the mask artifacts read back as MCP resources, and a mask feeds
     remove_object (the editing workflow's next step).
usage: smoke_test.py <photo> [--mcp http://127.0.0.1:8002/mcp] [--mlserver http://127.0.0.1:8500] [--registry <repo>/models]
Exit 0 when every check passes."""
import argparse
import asyncio
import base64
import hashlib
import importlib.util
import json
import sys
import urllib.request
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

HERE = Path(__file__).resolve().parent
ap = argparse.ArgumentParser()
ap.add_argument("photo")
ap.add_argument("--mcp", default="http://127.0.0.1:8002/mcp")
ap.add_argument("--mlserver", default="http://127.0.0.1:8500")
ap.add_argument("--registry", default=str(HERE.parents[1] / "models"))
args = ap.parse_args()
results = []


def check(name, ok, note=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'} {name}{': ' + note if note else ''}", flush=True)


def post(path, payload):
    req = urllib.request.Request(args.mlserver + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())


def expected_endpoints():
    sys.path.insert(0, str(HERE))
    from cerebrate_mcp.contracts import CONTRACTS
    spec = importlib.util.spec_from_file_location("registry", Path(args.registry) / "registry.py")
    registry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(registry)
    reg = registry.Registry.load(Path(args.registry) / "catalog.yaml", Path(args.registry) / "variants.yaml")
    ready = {m["name"] for m in post("/v2/repository/index", {}) if m.get("state") == "READY"}
    out = set()
    for ref, v in reg.variants["variants"].items():
        ep = (v.get("serving") or {}).get("mlserver_model")
        interface = (reg.models[ref.split("/")[0]].get("serving") or {}).get("interface")
        if v.get("status") == "production" and ep in ready and interface in CONTRACTS:
            out.add(ep)
    return out


async def main():
    photo = Path(args.photo).read_bytes()
    image = base64.b64encode(photo).decode()
    async with streamable_http_client(args.mcp) as (read, write):
        async with ClientSession(read, write) as s:
            init = await s.initialize()
            tools = {t.name for t in (await s.list_tools()).tools}
            check("tool discovery", {"list_capabilities", "segment_region"} <= tools,
                  f"server {init.server_info.name}; tools {sorted(tools)}")

            async def call(tool, **kw):
                r = await s.call_tool(tool, kw)
                if r.is_error:
                    raise RuntimeError(r.content[0].text)
                return r.structured_content

            caps = await call("list_capabilities")
            listed = {m["endpoint"] for m in caps["models"]}
            want = expected_endpoints()
            check("capabilities = registry production endpoints with a contract x MLServer READY", listed == want,
                  f"{len(listed)} listed: {sorted(listed)}" + ("" if listed == want else f"; expected {sorted(want)}"))

            det = await call("detect_objects", image=image, max_detections=3)
            boxes = [d["box"] for d in det["detections"]]
            check("detect_objects (default fixed-class-segmentation)", len(boxes) > 0,
                  f"{det['endpoint']}: " + ", ".join(f"{d['label']} {d['score']:.2f}" for d in det["detections"]) + f"; {det['elapsed_s']} s")

            seg = await call("segment_region", image=image, boxes=boxes)
            areas = [sum(m["mask"].get("rle", [])[1::2]) if "rle" in m["mask"] else None for m in seg["masks"]]
            check("segment_region through MCP -> MLServer -> EdgeSAM",
                  seg["endpoint"] == "edgesam3x-box" and len(seg["masks"]) == len(boxes) and all(m["score"] > 0.5 for m in seg["masks"]),
                  f"{seg['variant']}: scores {[round(m['score'], 3) for m in seg['masks']]}, mask pixels {areas}; {seg['elapsed_s']} s")

            image_id = int.from_bytes(hashlib.sha256(photo).digest()[:7], "big")
            direct = post("/v2/models/edgesam3x-box/infer", {"inputs": [
                {"name": "photo", "shape": [1], "datatype": "BYTES", "data": [image]},
                {"name": "image_id", "shape": [1], "datatype": "INT64", "data": [image_id]},
                {"name": "boxes", "shape": [len(boxes), 4], "datatype": "FP32", "data": [float(v) for b in boxes for v in b]}]})
            doc = json.loads(next(o for o in direct["outputs"] if o["name"] == "result")["data"][0])
            check("MCP masks identical to a direct MLServer request", [m["mask"] for m in seg["masks"]] == [m["mask"] for m in doc["masks"]])

            ref = seg["masks"][0]["mask_png"]
            blob = (await s.read_resource(ref["uri"])).contents[0].blob
            png = base64.b64decode(blob)
            check("mask artifact readable as an MCP resource", png[:8] == b"\x89PNG\r\n\x1a\n",
                  f"{ref['uri']} ({len(png)} bytes)" + (" = local file" if Path(ref["path"]).exists() and Path(ref["path"]).read_bytes() == png else ""))

            inp = await call("remove_object", image=image, mask=ref["uri"])
            check("the mask feeds remove_object (MI-GAN)", inp["result_png"]["uri"].startswith("artifact://"),
                  f"{inp['result_png']['uri']}; {inp['elapsed_s']} s")
    print(f"{sum(results)}/{len(results)} checks passed")
    return all(results)


sys.exit(0 if asyncio.run(main()) else 1)
