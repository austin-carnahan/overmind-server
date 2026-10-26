"""Cerebrate MCP: the Pixel's inference endpoints for MCP clients (OpenClaw
and any other), over Streamable HTTP. One tool per serving contract plus
list_capabilities; what each tool can call comes from the model registry and
MLServer's readiness (discovery.py), never from a list kept here. Inference
only: no loading, unloading or deployment.

Environment (defaults for a same-host run on overmind-01):
  CEREBRATE_MCP_MLSERVER_URL     MLServer REST (http://127.0.0.1:8500, the tunnel to the Pixel)
  CEREBRATE_MCP_REGISTRY_DIR     the repo's models/ (catalog.yaml, variants.yaml, registry.py)
  CEREBRATE_MCP_ADAPTER_DIR      the MLServer adapter's cerebrate-graph/ (photo_postprocess.py)
  CEREBRATE_MCP_ARTIFACT_DIR     output files (/var/lib/overmind/cerebrate-mcp/artifacts)
  CEREBRATE_MCP_ARTIFACT_TTL_H   hours to keep them (24)
  CEREBRATE_MCP_INPUT_ROOTS      colon-separated directories image paths may come from
                                 (the artifact directory is always allowed)
  CEREBRATE_MCP_TIMEOUT_S        per inference (300: a cold model start plus a capacity wait)
  CEREBRATE_MCP_HOST, _PORT      bind address (127.0.0.1:8002; private by default)"""
import os
import sys
import time
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from starlette.requests import Request
from starlette.responses import JSONResponse

from . import contracts as c
from .artifacts import Artifacts, InputError
from .discovery import Discovery, TargetError
from .mlserver import MLServer, MLServerError

# Defaults for a run from a checkout (services/cerebrate-mcp/cerebrate_mcp/);
# the container sets every path explicitly.
_PARENTS = Path(__file__).resolve().parents
REPO = _PARENTS[3] if len(_PARENTS) > 3 else Path("/repo")


def _env(name, default):
    return os.environ.get(f"CEREBRATE_MCP_{name}", default)


def create_app() -> FastMCP:
    mlserver = MLServer(_env("MLSERVER_URL", "http://127.0.0.1:8500"), float(_env("TIMEOUT_S", "300")))
    discovery = Discovery(_env("REGISTRY_DIR", str(REPO / "models")), mlserver)
    adapter_dir = _env("ADAPTER_DIR", str(REPO / "hosts/cerebrate-pixel6/mlserver/models/cerebrate-graph"))
    if adapter_dir not in sys.path:
        sys.path.insert(0, adapter_dir)
    import photo_postprocess as post   # the hooks' own mask codec
    artifacts = Artifacts(_env("ARTIFACT_DIR", "/var/lib/overmind/cerebrate-mcp/artifacts"),
                          float(_env("ARTIFACT_TTL_H", "24")) * 3600,
                          [p for p in _env("INPUT_ROOTS", "").split(":") if p])

    mcp = FastMCP("cerebrate", instructions=(
        "Inference on the Cerebrate Pixel 6 models. Call list_capabilities first: it lists the tools, the "
        "tasks and models each can call right now, and their inputs. Images are base64 (or data: URIs), "
        "artifact:// URIs from earlier results, or allowed absolute paths. Results are compact JSON; masks, "
        "depth maps and inpainted images are artifact:// files, readable as resources."))

    def run(tool: str, target: str, image: str, request, shape) -> dict:
        interface = c.TOOL_CONTRACT[tool]
        t0 = time.perf_counter()
        try:
            ep = discovery.resolve(target, interface)
            photo, size = artifacts.load_image(image)
            inputs, parameters = request(photo, size)
            doc = mlserver.infer(ep["endpoint"], inputs, parameters)
            run_id = artifacts.new_run()
            out = shape(doc, run_id, size)
        except (InputError, TargetError, MLServerError) as exc:
            raise ToolError(str(exc)) from exc
        return {"target": target, "endpoint": ep["endpoint"], "model": ep["model"], "variant": ep["variant"],
                "elapsed_s": round(time.perf_counter() - t0, 2), **out}

    @mcp.tool
    def list_capabilities() -> dict:
        """What can be called right now: each inference tool with its inputs and the endpoints it reaches,
        the tasks (with their default/quality/fallback selections) and the models behind them. Derived
        from the model registry and MLServer's live state."""
        return discovery.capabilities()

    @mcp.tool
    def segment_region(image: str, boxes: list[list[float]], target: str = "box-refinement") -> dict:
        """Precise masks for regions of an image, one per box [x0, y0, x1, y1] (image pixels). target: a
        task such as "box-refinement" (fast, default) or "box-refinement@quality", or a model id. Returns
        per box: score, the mask (compact encoding) and mask_png (an artifact:// PNG, white = region)."""
        return run("segment_region", target, image,
                   lambda photo, size: c.segment_region_request(photo, boxes),
                   lambda doc, rid, size: c.segment_region_result(doc, post, artifacts, rid, size))

    @mcp.tool
    def detect_objects(image: str, target: str = "fixed-class-segmentation", min_score: float = 0.0,
                       max_detections: int = 50, save_masks: bool = False) -> dict:
        """Find and outline objects with no prompt. target: "fixed-class-segmentation" (default: 80 common
        categories, clean labels), "prompt-free-segmentation" (4,585 tags: more objects, odder labels) or a
        model id. Returns labels, scores, boxes and compact masks; save_masks adds artifact:// PNGs."""
        return run("detect_objects", target, image,
                   lambda photo, size: c.photo_request(photo),
                   lambda doc, rid, size: c.detections_result(doc, post, artifacts, rid, size, min_score,
                                                              max_detections, save_masks))

    @mcp.tool
    def segment_by_text(image: str, prompts: list[str], target: str = "text-prompted-segmentation",
                        save_masks: bool = True) -> dict:
        """Outline every instance of each short phrase (up to 16), e.g. ["lamp", "suitcase"]. Returns per
        phrase: presence score and instances with boxes, compact masks and artifact:// mask PNGs. The image
        is cached by its content, so further phrases on the same image are faster."""
        return run("segment_by_text", target, image,
                   lambda photo, size: c.text_segmentation_request(photo, prompts),
                   lambda doc, rid, size: c.text_segmentation_result(doc, post, artifacts, rid, size, save_masks))

    @mcp.tool
    def detect_by_text(image: str, queries: list[str], target: str = "open-vocabulary-detection",
                       threshold: float | None = None) -> dict:
        """Boxes for each text query, e.g. ["a bed", "a wall sconce"] (up to 256; no masks -- pass the boxes
        to segment_region for masks). threshold defaults to the model's (0.2)."""
        return run("detect_by_text", target, image,
                   lambda photo, size: c.text_detection_request(photo, queries, threshold),
                   lambda doc, rid, size: doc)

    @mcp.tool
    def estimate_depth(image: str, target: str = "relative-depth") -> dict:
        """Relative depth of each pixel (larger = nearer; not metric). Returns the range and the depth map
        as an artifact:// 16-bit PNG at the model's resolution (stretched over the image)."""
        return run("estimate_depth", target, image,
                   lambda photo, size: c.photo_request(photo),
                   lambda doc, rid, size: c.depth_result(doc, artifacts, rid))

    @mcp.tool
    def inpaint(image: str, mask: str, target: str = "inpainting", grow_mask_px: int = 7) -> dict:
        """Inpainting: repaint the masked region from its surroundings (e.g. to erase an object). mask: an
        image of the same size, white = region to fill (a mask_png from segment_region works directly).
        grow_mask_px widens the mask first (default 7; the fill needs a margin around an object). Works best
        on one modest region at a time. Returns the result as an artifact:// PNG."""
        def request(photo, size):
            mask_bytes, mask_size = artifacts.load_image(mask, "mask")
            return c.inpaint_request(photo, size, mask_bytes, mask_size, grow_mask_px)
        return run("inpaint", target, image, request,
                   lambda doc, rid, size: c.inpaint_result(doc, artifacts, rid))

    @mcp.tool
    def embed_image(image: str, target: str = "image-embedding") -> dict:
        """A global image embedding (DINOv2, 384 float32, base64 little-endian) for comparing images by
        cosine similarity."""
        return run("embed_image", target, image,
                   lambda photo, size: c.photo_request(photo),
                   lambda doc, rid, size: doc)

    @mcp.resource("artifact://{run}/{name}", mime_type="image/png",
                  description="An output file of an earlier call (masks, depth maps, inpainted images).")
    def artifact(run: str, name: str) -> bytes:
        try:
            return artifacts.path_of(run, name).read_bytes()
        except InputError as exc:
            raise ValueError(str(exc)) from exc

    @mcp.custom_route("/healthz", methods=["GET"])
    async def healthz(request: Request) -> JSONResponse:
        readiness, problem = discovery.readiness()
        return JSONResponse({"ok": readiness is not None, **({"error": problem} if problem else {})},
                            status_code=200 if readiness is not None else 503)

    return mcp


def main():
    create_app().run(transport="http", host=_env("HOST", "127.0.0.1"), port=int(_env("PORT", "8002")),
                     show_banner=False)


if __name__ == "__main__":
    main()
