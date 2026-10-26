# Cerebrate MCP

**Status:** SPIKE — validated live on 2026-10-26 with a temporary container
on overmind-01. It is not in the compose stack, and OpenClaw is not connected
to it yet; both steps are below.

The Pixel 6's inference endpoints, for any MCP client (OpenClaw first), over
Streamable HTTP on `127.0.0.1:8002/mcp`. The server is built with FastMCP 4.1.

It is a thin adapter over the existing serving stack. It reads the model
registry (`models/`) and MLServer's live state to decide what is callable, and
calls MLServer's REST API the way every other Overmind client does. All model
logic stays in the MLServer hooks: preprocessing, postprocessing, labels and
the compact mask encoding. The adapter does inference only: no loading,
unloading or deployment.

## Tools

There is one tool per **serving contract** (the catalog's `serving.interface`),
not per model, plus discovery:

| Tool | Contract | Default target | Inputs → output |
| --- | --- | --- | --- |
| `list_capabilities` | — | — | → every tool's callable endpoints, the tasks and their selections, the models |
| `segment_region` | `photo-box-masks-v1` | `box-refinement` (EdgeSAM; `@quality` = SAM 2.1) | image, boxes → per box: score, compact mask, `mask_png` |
| `detect_objects` | `photo-detections-v1` | `fixed-class-segmentation` (RF-DETR; `prompt-free-segmentation` = YOLOE) | image → labels, scores, boxes, compact masks (PNGs optional) |
| `segment_by_text` | `photo-text-segmentation-v1` | `text-prompted-segmentation` (EfficientSAM3) | image, phrases → per phrase: presence, instances, mask PNGs |
| `detect_by_text` | `photo-text-detection-v1` | `open-vocabulary-detection` (OWLv2) | image, queries → boxes per query |
| `estimate_depth` | `photo-depth-v1` | `relative-depth` (Depth Anything) | image → range, 16-bit depth PNG |
| `remove_object` | `photo-inpaint-v1` | `inpainting` (MI-GAN) | image, mask (grown 7 px by default) → inpainted PNG |
| `embed_image` | `photo-embedding-v1` | `image-embedding` (DINOv2) | image → 384 float32 (base64) |

**Targets.** A target can be any of:
- a task: `box-refinement`, or `box-refinement@quality`;
- a model id: `edgesam-3x`;
- a model alias: `sam2.1-hiera-tiny@default`;
- a variant: `<model>/<variant>`;
- an endpoint name.

The registry's own `resolve` maps each one to a variant. A target is callable
only when that variant is a **production** variant with an MLServer endpoint,
the endpoint is READY in MLServer, and its contract matches the tool. Staged,
blocked, unloaded and internal-fallback configurations are never offered.
Endpoints without a photo contract are left out: MobileNet, SmolLM2, and
Granite-Docling, which already has its own service, Doclet.

**Images and artifacts.**
- **Image inputs** are base64, a `data:` URI, an `artifact://` URI from an
  earlier result, or a file under the allowed input directories
  (`file:///…`, or an absolute path that exists there).
- **Outputs** are compact JSON. Masks keep the hooks' bbox+RLE/bit encoding,
  decodable with
  [`photo_postprocess.decode_mask`](../../hosts/cerebrate-pixel6/mlserver/models/cerebrate-graph/photo_postprocess.py).
- **Output files** (mask PNGs, depth maps, inpainted images) are written to the
  artifact directory and returned as `{"uri": "artifact://<run>/<name>",
  "path": …}`. A remote client reads them as the MCP resource with that URI; a
  same-host client can use the path. They are kept 24 h.

## Adding models and contracts

- **A model with an existing contract** needs nothing here. Register it, deploy
  and promote it, and it appears in `list_capabilities` and is callable by its
  tool. The registry is re-read whenever it changes.
- **A new contract** (a new `serving.interface`, i.e. a new input/output
  shape) needs four things in this service:
  1. an entry in `CONTRACTS` in
     [`cerebrate_mcp/contracts.py`](cerebrate_mcp/contracts.py): interface,
     tool name, default task, summary, inputs;
  2. a request builder and a result shaper in the same file, mapping
     arguments to the endpoint's V2 inputs and its JSON to a compact response;
  3. a tool function in [`cerebrate_mcp/server.py`](cerebrate_mcp/server.py)
     that calls `run(...)` with them;
  4. a test in [`tests/`](tests/test_cerebrate_mcp.py) with a canned endpoint
     result.

  Keep model logic in the MLServer hook, not here.

The onboarding walkthrough
([models/README.md](../../models/README.md#onboarding-a-validated-model)) and
the promotion checklist
([runbook](../../runbooks/cerebrate-pixel6-models.md#promote-a-staged-endpoint))
include the MCP check.

## Deploy (not done yet: needs approval)

1. **The checkout.** `/opt/overmind` must carry the model registry this service
   reads (`models/registry.py`, `variants.yaml`). Today that is on the
   `feat/segmentation-lane-graph-worker` line, which isn't merged into `main`.
2. **Artifact directory.** Create it for the container's user:
   `sudo install -d -o 10010 -g 10010 /var/lib/overmind/cerebrate-mcp/artifacts`.
3. **Start it.** Uncomment `cerebrate-mcp/compose.yaml` in
   [`services/compose.yaml`](../compose.yaml), then run `docker compose -f
   compose.yaml up -d cerebrate-mcp` from `services/`.
4. **Verify.**
   - `curl -s http://127.0.0.1:8002/healthz` returns `{"ok": true}` when
     MLServer is reachable.
   - Run the live smoke test (below).

**Rollback:** `docker compose -f compose.yaml rm -sf cerebrate-mcp`, then
comment the include out again. Nothing else depends on it.

## OpenClaw

Run on the Gateway host (overmind-01):

```bash
openclaw mcp add cerebrate --transport streamable-http --url http://127.0.0.1:8002/mcp --timeout 330
sudo systemctl restart openclaw-gateway.service   # mcp.* changes need a real restart
```

- **Agent scoping.** MCP servers aren't scoped to agents by default
  ([sandboxing and trust](../../runbooks/openclaw/sandboxing-and-trust.md#mcp-servers-and-tool-access)).
  Give the tools only to the agents that need them. Tool names are
  `cerebrate__<tool>`. [`examples/openclaw.json5`](examples/openclaw.json5)
  shows the resulting server entry and per-agent policy: allowed for
  Buckminster, the design agent; denied elsewhere.
- **Verify.** `openclaw mcp probe cerebrate --json`, then a real agent turn
  that calls `cerebrate__list_capabilities` and `cerebrate__segment_region`.
- **Why `--timeout 330`.** It sits above the server's 300 s inference timeout,
  which covers a cold model start plus up to 30 s of waiting for memory.

## Tests

```bash
cd services/cerebrate-mcp
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v                    # fake MLServer, temporary registry copy
.venv/bin/python smoke_test.py <photo.jpg> [--mcp URL] [--mlserver URL]  # live: needs the server and MLServer
```

The unit tests cover:
- tool discovery;
- the capabilities matching the registry and readiness;
- staged and unready configurations excluded;
- a newly registered model appearing, and callable, with no code change;
- target resolution;
- the `segment_region` request mapping and its decoded masks;
- artifacts as resources, and chaining a mask into `remove_object`;
- JPEG base64 not mistaken for a path;
- error reporting.

## Validation (2026-10-26)

| Check | Result |
| --- | --- |
| Unit tests | 8/8 |
| Live, temporary container on overmind-01 on 127.0.0.1:8002, MCP Python SDK 2.3 client | 7/7 |

The live run:
- **Discovery.** All 8 tools are discovered. `list_capabilities` lists exactly
  10 endpoints: the registry's production photo-contract endpoints that
  MLServer reports READY.
- **Detect.** `detect_objects` (RF-DETR) on the hotel-room photo returned
  suitcase 0.91, bottle 0.80, bed 0.78.
- **Segment.** `segment_region` with those boxes ran through MCP → MLServer →
  EdgeSAM (`edgesam-3x/tpu-fp16r-gpu-neck-fp32`) with scores 1.01, 0.98 and
  0.98. The masks are **identical to a direct MLServer request**.
- **Artifacts.** The mask PNG reads back as an MCP resource and feeds
  `remove_object`: MI-GAN removed the suitcase cleanly with the 7 px margin.
- **No restart needed.** Staging OWLv2 in the registry copy removed it, and
  `detect_by_text`, from discovery without a restart; reverting restored them.

## Remaining gaps

- **Not deployed.** It is not in the compose stack, and `/opt/overmind` doesn't
  have the registry line yet.
- **Not connected to OpenClaw yet.** That needs a config change and a Gateway
  restart. Whether OpenClaw surfaces MCP *resources* to agents is unverified;
  if it doesn't, a remote agent gets masks through the compact encoding, or
  the path with the existing artifact transport (e.g. the Mac's file
  transfer).
- **No authentication.** The endpoint is loopback-only, and any same-host
  process can call it, like garmin-mcp.
- **Readiness is MLServer's.** A READY on-demand model may still need a few
  seconds to start, or wait for memory (the supervisor's capacity rule).
  `list_capabilities` doesn't show capacity.
