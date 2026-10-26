# Cerebrate MCP

**Status:** DEPLOYED on overmind-01 on 2026-10-26, in the compose stack,
loopback-only (deploy record below). OpenClaw: connect with
[`openclaw-connect.sh`](openclaw-connect.sh) (below).

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
| `segment_region` | `photo-box-masks-v1` | `box-refinement` (EdgeSAM; `@quality` = SAM 2.1) | image, boxes → per box: score, polygons, compact mask, `mask_png` |
| `detect_objects` | `photo-detections-v1` | `fixed-class-segmentation` (RF-DETR; `prompt-free-segmentation` = YOLOE) | image → labels, scores, boxes, polygons, compact masks (PNGs optional) |
| `segment_by_text` | `photo-text-segmentation-v1` | `text-prompted-segmentation` (EfficientSAM3) | image, phrases → per phrase: presence, instances with polygons and mask PNGs (photos over 2048 px segmented scaled down) |
| `detect_by_text` | `photo-text-detection-v1` | `open-vocabulary-detection` (OWLv2) | image, queries → boxes per query |
| `estimate_depth` | `photo-depth-v1` | `relative-depth` (Depth Anything) | image → range, 16-bit depth PNG |
| `inpaint` | `photo-inpaint-v1` | `inpainting` (MI-GAN) | image, mask (grown 7 px by default) → RGBA patch of the filled pixels + offset (whole photo with `composite`) |
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
- **Image inputs** are base64, a `data:` URI, an `artifact://` URI or artifact
  URL from an earlier result, or a file under the allowed input directories
  (`file:///…`, or an absolute path that exists there). The deployment allows
  the design-studio project store
  (`/mnt/substrate/design-studio/projects/<project>/sources/…`, read-only), so
  an agent passes a source's path instead of its bytes.
- **Outputs** are compact JSON. Masks keep the hooks' bbox+RLE/bit encoding,
  decodable with
  [`photo_postprocess.decode_mask`](../../hosts/cerebrate-pixel6/mlserver/models/cerebrate-graph/photo_postprocess.py),
  and also come as **polygons** (below).
- **Output files** (mask PNGs, depth maps, inpaint patches) are written to the
  artifact directory and returned as `{"uri": "artifact://<run>/<name>",
  "path": …, "url": …}`. A remote MCP client reads them as the MCP resource
  with that URI; a same-host client can use the path; any other tool fetches
  the **signed URL** (below). They are kept 24 h.

### Polygons

Each mask is also a list of rings `{"hole": bool, "points": [x0, y0, x1, y1,
…]}` in image pixels, ordered so that replaying them with an editor's
polygon select rebuilds the mask: the first ring `replace`, later outer rings
`add`, holes `subtract`. Each outer ring comes with its own holes, largest
first, so an island inside a hole is added back after that hole. They are
GIMP's `gimp-image-select-polygon` `segs` as is.

- **Pixel corners, not centres.** Vertices are traced on the pixel grid's
  corners (contours of the mask upscaled 2×, `q → (q + 1) // 2`). Traced
  through pixel centres, GIMP — which keeps a pixel when its centre is inside
  — lost half a pixel all round.
- **Simplified to 1 px** (Douglas–Peucker). On a 4000×3000 photo (23 masks
  from EdgeSAM and YOLOE, up to 20 rings and 6 holes each), GIMP selections
  rebuilt from them matched the masks at IoU **0.998 median, 0.990 minimum**
  (the smallest mask, a pillow). The 23 masks took 103 KB as polygons vs
  307 KB as RLE, and 3.5 s to replay in GIMP.

### Artifact URLs

With `CEREBRATE_MCP_PUBLIC_URL` set, every output file also has a `url`:
`http://artifacts.home.arpa/artifacts/<run>/<name>?exp=…&sig=…`.

- **Served by** this container's `/artifacts/{run}/{name}` route, through
  Caddy's `artifacts.home.arpa` site, which proxies only that path. The MCP
  endpoint itself stays loopback-only. The file is the same one the
  `artifact://` resource reads; nothing is copied.
- **Signed:** an HMAC-SHA256 over the run, name and expiry, with a key created
  on first start (`/var/lib/overmind/cerebrate-mcp/url-key`, 0600). A URL
  works for that one file until it expires (the artifact TTL, 24 h) or the
  file is pruned. A wrong or expired signature gets 403.
- **HTTP over the LAN/Tailnet**, like every `*.home.arpa` site (the DNS plan
  defers HTTPS; Tailscale is the transport security).
- **Why URLs:** MCP doesn't forward a resource from one server to another, so
  `artifact://` means nothing to GIMP's MCP. A URL lets the consuming tool
  fetch the file itself and the agent passes only the reference. Passed back
  to this server as an input, the store's own URL is read locally.

### Inpaint patches

`inpaint` doesn't send the whole photo. The inpainting model works at a fixed
512 px: the whole 4000×3000 photo squashed to 512 left a 15×26 px hole and an
8× blurred, 15 MB result.

- **The window.** The adapter sends a square window around the grown mask, at
  least 512 px and twice the mask's extent, clamped to the photo.
- **The patch.** It returns an RGBA patch, alpha = the grown mask, cut to the
  mask's bounds, with its `offset` and `size`. Placed as a layer at the
  offset, it covers only the filled pixels, so other edits underneath survive.
- **Measured.** On the lamp in bedroom.jpg: 2.5 s and a clean fill, vs 23 s
  and a blur for the whole photo. `composite=True` also saves the whole photo
  with the patch applied.

### Large photos and text segmentation

`segment_by_text` sends photos over 2048 px scaled down, and maps boxes,
masks and polygons back to the photo's pixels (`segmented_at` gives the size
used).

- **Why.** EfficientSAM3's hook upsamples every kept mask to the photo as
  float32 at once, so a 12 MP phone photo got MLServer OOM-killed on the
  Pixel's 959 MB guest (2026-10-26).
- **No loss.** The model sees 1008 px and predicts 288 px masks, so nothing is
  lost.
- **Interim.** Until the hook upsamples mask by mask, which is an MLServer
  change.

The other contracts handled 12 MP photos (RF-DETR, YOLOE, EdgeSAM).

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

## Deploy

1. **The checkout.** `/opt/overmind` must carry the model registry this service
   reads (`models/registry.py`, `variants.yaml`). It has since the merge into
   `main` (`30bc2dd`).
2. **Artifact directory.** As austin, who owns `/var/lib/overmind` and is the
   container's user: `install -d /var/lib/overmind/cerebrate-mcp/artifacts`.
3. **Start it.** The include is enabled in
   [`services/compose.yaml`](../compose.yaml). From `services/`, run
   `docker compose -f compose.yaml up -d --build --no-deps cerebrate-mcp`.
4. **Verify.**
   - `curl -s http://127.0.0.1:8002/healthz` returns `{"ok": true}` when
     MLServer is reachable.
   - Run the live smoke test (below).

**Rollback:** `docker compose -f compose.yaml rm -sf cerebrate-mcp`, then
comment the include out again. Nothing else depends on it.

**Deploy record (2026-10-26).**
1. `/opt/overmind` was fast-forwarded to `7cc99d7`.
2. The artifact directory was created as austin.
3. `up -d --build --no-deps cerebrate-mcp` started it. No other container
   changed.

The live smoke test then passed 7/7 against the deployed service:
- discovery listed the 10 endpoints;
- RF-DETR → EdgeSAM masks identical to a direct MLServer request;
- the mask artifact read back as a resource;
- the mask fed `inpaint`.

## OpenClaw

Run on the Gateway host (overmind-01), as a sudoer:

```bash
bash /opt/overmind/services/cerebrate-mcp/openclaw-connect.sh   # ALLOW_AGENTS="buckminster" by default
```

The script does three things:
1. **Adds the server.** It runs `openclaw mcp add cerebrate --transport
   streamable-http --url http://127.0.0.1:8002/mcp --timeout 330`, as the
   `openclaw` user; OpenClaw probes the server before saving.
2. **Scopes the tools.** It appends `cerebrate__*` to the allowed agents'
   `tools.alsoAllow` and to every other agent's `tools.deny`. It shows the
   changes, dry-runs them, and asks before applying.
3. **Restarts the Gateway** (`mcp.*` changes need a real restart), confirms a
   new PID, and probes the server through OpenClaw.

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
- artifacts as resources, and chaining a mask into `inpaint`;
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
  `inpaint`: with the suitcase's mask grown 7 px, MI-GAN repainted it as wall cleanly.
- **No restart needed.** Staging OWLv2 in the registry copy removed it, and
  `detect_by_text`, from discovery without a restart; reverting restored them.

## GIMP handoff

Buckminster's recipe is
[`services/design-studio/buckminster/cerebrate-gimp.md`](../design-studio/buckminster/cerebrate-gimp.md):
1. source path → Cerebrate;
2. polygons → `gimp-image-select-polygon`;
3. duplicate layer + selection mask → cutout layer;
4. `inpaint` patch URL → GIMP's
   [`overmind-import-artifact`](../design-studio/gimp-plugins/overmind-import-artifact/overmind-import-artifact.py)
   at the offset.

What the 2026-10-26 spike established:
- **GIMP can't load a URL itself on macOS.**
  - The GIMP MCP bridge turns every file argument into a local path
    (`/http:/…`).
  - GIMP's GIO has only the `file` and `resource` schemes (no gvfs), so an
    http GFile is a dummy that `file_load_layer` returns nothing for.
- **Its bundled Python (3.14, OpenSSL, certifi) fetches HTTP and HTTPS**,
  hence the plug-in: download (artifact service only, no redirects, size cap,
  PNG/JPEG/WebP), then load the temporary file.
- **The bridge's `pdb_call` can't pass object arrays** (`gimp-edit-copy`) or
  a null `parent`, hence the duplicate-and-mask cutout.

## Remaining gaps

- **OpenClaw resources unverified.** Whether OpenClaw surfaces MCP
  *resources* to agents is unverified. With artifact URLs and source paths an
  agent doesn't need them.
- **No authentication on the MCP endpoint.** It is loopback-only, and any
  same-host process can call it, like garmin-mcp. Artifact downloads need a
  signed URL.
- **Readiness is MLServer's.** A READY on-demand model may still need a few
  seconds to start, or wait for memory (the supervisor's capacity rule).
  `list_capabilities` doesn't show capacity.
