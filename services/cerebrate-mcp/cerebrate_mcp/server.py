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
  CEREBRATE_MCP_PUBLIC_URL       base URL the /artifacts route is reachable at by other machines
                                 (e.g. http://artifacts.home.arpa); unset = no URLs in results
  CEREBRATE_MCP_URL_KEY_FILE     URL-signing key, created on first start (<artifact dir>/../url-key)
  CEREBRATE_MCP_URL_TTL_H        hours a signed URL stays valid (the artifact TTL)
  CEREBRATE_MCP_UPLOAD_TOKENS    uploading hosts' token hashes (<artifact dir>/../upload-tokens.json;
                                 managed with python -m cerebrate_mcp.uploads)
  CEREBRATE_MCP_UPLOAD_MAX_MB    largest upload (32)
  CEREBRATE_MCP_UPLOAD_DAILY_MAX uploads per host per day (500)
  CEREBRATE_MCP_INPUT_ROOTS      colon-separated directories image paths may come from
                                 (the artifact directory is always allowed)
  CEREBRATE_MCP_TIMEOUT_S        per inference (300: a cold model start plus a capacity wait)
  CEREBRATE_MCP_HOST, _PORT      bind address (127.0.0.1:8002; private by default)"""
import io
import os
import sys
import time
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse

from . import contracts as c
from . import imageops
from .artifacts import Artifacts, InputError
from .uploads import Tokens, UploadError, accept
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
                          [p for p in _env("INPUT_ROOTS", "").split(":") if p],
                          public_url=_env("PUBLIC_URL", ""), key_file=_env("URL_KEY_FILE", ""),
                          url_ttl_s=float(_env("URL_TTL_H", "0")) * 3600)
    tokens = Tokens(_env("UPLOAD_TOKENS", str(artifacts.root.parent / "upload-tokens.json")))
    upload_max, upload_daily = int(float(_env("UPLOAD_MAX_MB", "32")) * 1024 * 1024), int(_env("UPLOAD_DAILY_MAX", "500"))

    mcp = FastMCP("cerebrate", instructions=(
        "Inference on the Cerebrate Pixel 6 models. Call list_capabilities first: it lists the tools, the "
        "tasks and models each can call right now, and their inputs. Images are base64 (or data: URIs), "
        "artifact:// URIs or artifact URLs from earlier results, or allowed absolute paths. Results are compact "
        "JSON. Every mask comes as polygons (rings of flat [x0, y0, x1, y1, ...] image-pixel points, ready for "
        "an editor's polygon select: first ring replace, later outer rings add, holes subtract). Output files "
        "(mask PNGs, depth maps, inpaint patches) are artifact:// resources and, where configured, signed "
        "http URLs another tool (e.g. GIMP's overmind-import-artifact) can fetch directly -- pass the URL, "
        "not the bytes. seamless_blend is an image operation on overmind's CPU, not a model."))

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
        from the model registry and MLServer's live state; plus the image operations that run on overmind."""
        return {**discovery.capabilities(), "image_operations": {
            "seamless_blend": "Poisson blend (OpenCV seamlessClone) of a reconstruction into its surroundings; "
                              "CPU on overmind, about 2 s for a 1,100x700 region"}}

    @mcp.tool
    def segment_region(image: str, boxes: list[list[float]], target: str = "box-refinement") -> dict:
        """Precise masks for regions of an image, one per box [x0, y0, x1, y1] (image pixels). target: a
        task such as "box-refinement" (fast, default) or "box-refinement@quality", or a model id. Returns
        per box: score, the mask as polygons and in a compact encoding, and mask_png (an artifact:// PNG,
        white = region, with a url where configured)."""
        return run("segment_region", target, image,
                   lambda photo, size: c.segment_region_request(photo, boxes),
                   lambda doc, rid, size: c.segment_region_result(doc, post, artifacts, rid, size))

    @mcp.tool
    def detect_objects(image: str, target: str = "fixed-class-segmentation", min_score: float = 0.0,
                       max_detections: int = 50, save_masks: bool = False) -> dict:
        """Find and outline objects with no prompt. target: "fixed-class-segmentation" (default: 80 common
        categories, clean labels), "prompt-free-segmentation" (4,585 tags: more objects, odder labels) or a
        model id. Returns labels, scores, boxes and masks (polygons + compact encoding); save_masks adds
        mask PNG artifacts."""
        return run("detect_objects", target, image,
                   lambda photo, size: c.photo_request(photo),
                   lambda doc, rid, size: c.detections_result(doc, post, artifacts, rid, size, min_score,
                                                              max_detections, save_masks))

    @mcp.tool
    def segment_by_text(image: str, prompts: list[str], target: str = "text-prompted-segmentation",
                        save_masks: bool = True, threshold: float | None = None) -> dict:
        """Outline every instance of each short phrase (up to 16), e.g. ["lamp", "suitcase"]. Returns per
        phrase: presence score and instances with boxes, masks (polygons + compact encoding) and mask PNG
        artifacts. threshold (default 0.5) is the instance cut-off, score x presence: lower it when presence
        is high but nothing is returned. The image is cached by its content, so further phrases on it are
        faster."""
        return run("segment_by_text", target, image,
                   lambda photo, size: c.text_segmentation_request(photo, prompts, threshold),
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
    def inpaint(image: str, mask: str, target: str = "inpainting", grow_mask_px: int = 7,
                composite: bool = False) -> dict:
        """Inpainting: repaint the masked region from its surroundings (e.g. to erase an object). mask: an
        image of the same size, white = region to fill (a mask_png from segment_region works directly).
        grow_mask_px widens the mask first (default 7; the fill needs a margin around an object). The model
        runs on a window around the mask, so one modest region at a time works best. Returns a patch: an
        RGBA PNG covering only the filled pixels (artifact + url), its offset [x, y] and size in the photo,
        and context (the photo's pixels around the fill, + url and offset) -- pass both URLs to GIMP's
        overmind-import-artifact, which checks the context before placing the patch. composite=True also
        returns the whole repainted photo."""
        ctx = {}

        def request(photo, size):
            mask_bytes, mask_size = artifacts.load_image(mask, "mask")
            return c.inpaint_request(post, photo, size, mask_bytes, mask_size, grow_mask_px, ctx)
        return run("inpaint", target, image, request,
                   lambda doc, rid, size: c.inpaint_result(doc, artifacts, rid, ctx, composite))

    @mcp.tool
    def embed_image(image: str, target: str = "image-embedding") -> dict:
        """A global image embedding (DINOv2, 384 float32, base64 little-endian) for comparing images by
        cosine similarity."""
        return run("embed_image", target, image,
                   lambda photo, size: c.photo_request(photo),
                   lambda doc, rid, size: doc)

    @mcp.tool
    def seamless_blend(image: str, mask: str, destination: str, mode: str = "normal") -> dict:
        """Blend a reconstruction into its surroundings (Poisson blending, OpenCV seamlessClone): inside the
        mask it keeps image's texture (the reconstruction), at the mask's edge it takes on the light and colour
        of destination -- the same region WITHOUT the reconstruction (e.g. the original photo layer; one that
        already contains the reconstruction keeps its hard edge). mask: same size, white = the region to
        blend (cover the hole plus a margin of clean surroundings). All three the same size. Returns a patch: an
        RGBA PNG covering the mask (artifact + url), its offset [x, y] and size in image -- import it with GIMP's
        overmind-import-artifact (snapshot=...) as a layer above the raw reconstruction. mode "mixed" keeps the
        stronger of the two images' gradients. An image operation on overmind's CPU, not a model."""
        t0 = time.perf_counter()
        try:
            src, _ = artifacts.load_image(image)
            m, _ = artifacts.load_image(mask, "mask")
            dst, _ = artifacts.load_image(destination, "destination")
            res = imageops.seamless_blend(src, m, dst, mode)
            run_id = artifacts.new_run()
            buf = io.BytesIO()
            res.pop("patch").save(buf, format="PNG")
            patch = artifacts.save_bytes(run_id, "blend-patch.png", buf.getvalue())
        except InputError as exc:
            raise ToolError(str(exc)) from exc
        return {"operation": "seamless_blend", "elapsed_s": round(time.perf_counter() - t0, 2), "patch": patch, **res}

    @mcp.resource("artifact://{run}/{name}", mime_type="image/png",
                  description="An output file of an earlier call (masks, depth maps, inpainted images).")
    def artifact(run: str, name: str) -> bytes:
        try:
            return artifacts.path_of(run, name).read_bytes()
        except InputError as exc:
            raise ValueError(str(exc)) from exc

    @mcp.custom_route("/artifacts/upload", methods=["POST"])
    async def artifact_upload(request: Request):
        """Create one artifact from the request body (PNG/JPEG), for a host
        with an upload token: e.g. GIMP publishing a snapshot of its document.
        ?name= names the file. Returns its artifact:// URI and signed URL."""
        host = tokens.host_for(request.headers.get("authorization"))
        if host is None:
            return PlainTextResponse("upload token missing, invalid or revoked\n", status_code=401)
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > upload_max:
            return PlainTextResponse(f"larger than {upload_max} bytes\n", status_code=413)
        body = bytearray()
        async for chunk in request.stream():
            body += chunk
            if len(body) > upload_max:
                return PlainTextResponse(f"larger than {upload_max} bytes\n", status_code=413)
        try:
            ref = accept(artifacts, host, bytes(body), request.query_params.get("name", ""), upload_max, upload_daily)
        except UploadError as exc:
            return PlainTextResponse(f"{exc}\n", status_code=exc.status)
        return JSONResponse(ref)

    @mcp.custom_route("/artifacts/{run}/{name}", methods=["GET"])
    async def artifact_download(request: Request):
        """Signed, read-only download of one output file -- the route the
        artifacts.home.arpa Caddy site exposes (nothing else of this server is)."""
        run_id, name = request.path_params["run"], request.path_params["name"]
        if not artifacts.verify(run_id, name, request.query_params.get("exp", ""), request.query_params.get("sig", "")):
            return PlainTextResponse("invalid or expired link\n", status_code=403)
        try:
            path = artifacts.path_of(run_id, name)
        except InputError:
            return PlainTextResponse("not found\n", status_code=404)
        media = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}.get(path.suffix.lower(),
                                                                                       "application/octet-stream")
        return FileResponse(path, media_type=media, headers={"Cache-Control": "private, max-age=3600, immutable"})

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
