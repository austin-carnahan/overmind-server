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
| `segment_by_text` | `photo-text-segmentation-v1` | `text-prompted-segmentation` (EfficientSAM3) | image, phrases, optional `threshold` → per phrase: presence, instances with polygons and mask PNGs |
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
- **Context.** It also returns `context`: the photo's own pixels around the
  fill (the patch bounds plus 6 px, alpha 0 over the grown mask). GIMP
  compares it with what the target layer shows at the placement spot before
  placing the patch, which catches a misplaced or stale patch.
- **Measured.** On the lamp in bedroom.jpg: 2.5 s and a clean fill, vs 23 s
  and a blur for the whole photo. `composite=True` also saves the whole photo
  with the patch applied.
- **Mask growing.** Growing the mask with PIL's MaxFilter took 15 s on a 12 MP
  mask on the Pi; `cv2.dilate` gives identical output in 0.7 s.

### Image operations (CPU on overmind)

Not every useful tool is a model. These run in this container, on overmind's
CPU: no registry entry, no MLServer, nothing on the Pixel.
`list_capabilities` lists them under `image_operations`.

- **`seamless_blend(image, mask, destination, mode)`** is a Poisson blend,
  OpenCV's `seamlessClone`.
  - **What it does:** inside the mask it keeps `image`'s texture (the
    reconstruction). At the mask's edge it takes on `destination`'s light
    and colour.
  - **What it returns:** an RGBA patch over the mask, with its offset.
  - **`destination` must be the scene *without* the reconstruction,** for
    example the original photo layer. OpenCV erodes the mask by 3 px and
    takes the destination's gradients in that ring. A destination that
    already contains the reconstruction keeps its hard edge, and nothing
    blends; the unit test shows both cases.
  - **Speed:** about 2 s for a 1,100×700 region on the Pi. GIMP's GEGL
    seamless clone took about 100 s for the same region; it's
    single-threaded, and GIMP won't run it as a filter.

  From GIMP, publish the reconstruction and the original over the same
  region:

  ```
  overmind-publish(mode="bounds", source=<group with the reconstruction>)
  overmind-publish(mode="region", source=<the original layer>, x, y, w, h)
  ```

  The first call uses the footprint selection, which yields the mask. Then
  call `seamless_blend`, and import the patch with
  `snapshot=<the first snapshot>`.

### Uploads

`POST /artifacts/upload?name=<stem>` creates one artifact from the request
body. It's how GIMP publishes a snapshot of its document
([`overmind-publish`](../design-studio/gimp-plugins/overmind-import-artifact/overmind-import-artifact.py)).
Uploads are ordinary inputs to every tool, by URI or URL.

- **Create-only.** An upload makes a new artifact, with the usual 24 h
  lifetime and a signed URL, and can't read, overwrite or delete anything.
- **Per-host tokens.** Each host sends `Authorization: Bearer <host>.<secret>`.
  Only a hash of the secret is stored, in
  `/var/lib/overmind/cerebrate-mcp/upload-tokens.json`. Changes take effect
  without a restart:

  ```bash
  docker exec cerebrate-mcp python -m cerebrate_mcp.uploads add macbook-m1   # prints the token once
  docker exec cerebrate-mcp python -m cerebrate_mcp.uploads revoke macbook-m1
  docker exec cerebrate-mcp python -m cerebrate_mcp.uploads list
  ```

- **Limits:** PNG or JPEG only (checked by decoding), 32 MB
  (`CEREBRATE_MCP_UPLOAD_MAX_MB`), and 500 uploads per host per day
  (`CEREBRATE_MCP_UPLOAD_DAILY_MAX`, counted from the host's `up-<host>-<date>`
  folders).
- **Plain HTTP, accepted for now.** Tokens travel over plain HTTP on the LAN,
  like every `*.home.arpa` site, because the DNS plan defers HTTPS. Revisit
  together with that plan.

### Large photos

Phone photos (12 MP) go to the models as sent. The MLServer hooks do their
host steps in bounded memory (see
[the MLServer README](../../hosts/cerebrate-pixel6/mlserver/README.md#phone-photos-host-steps-in-bounded-memory-prepared-2026-10-26)).
An interim workaround that shrank `segment_by_text`'s photos was removed
when the hooks were fixed.

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

**Deploy record (2026-10-26, GIMP handoff, `c50fa30`).**
1. `up -d --build --no-deps cerebrate-mcp`; the signing key was created at
   `/var/lib/overmind/cerebrate-mcp/url-key`.
2. Caddy's `artifacts.home.arpa` site: `docker restart caddy`. A reload
   didn't see the pulled Caddyfile: single-file bind mount.
3. DNS `artifacts.home.arpa` via `scripts/sync-dns-rewrites --apply`.
4. Buckminster's recipe via `install-buckminster-cerebrate-runbook`.

End to end on bedroom.jpg (4000×3000), photo passed by path:
- RF-DETR → EdgeSAM → `inpaint` with the mask's URL as input → an 18.5 KB
  patch at (2167, 1386).
- On the Mac, `gimp_pdb_call("overmind-import-artifact", …)` fetched and
  placed it in 1.1 s.
- Another host's URL and a tampered signature were refused.
- Through Caddy, every path but `/artifacts/*` is 404.

**Deploy record (2026-10-26, snapshots and uploads, `d7840dc`).**
1. `/opt/overmind` was pulled. `docker restart cerebrate-mcp` was needed:
   compose leaves the container running when only the mounted code changed.
2. `macbook-m1` was issued an upload token, written to the Mac plug-in's
   settings.
3. The Pixel guest was moved to `main`, and MLServer restarted with the hook
   fixes.

Live, through the agent path (`gimp_pdb_call`):
- the code evaluators were refused;
- publish → `inpaint` on the snapshot → import with `snapshot=` placed the
  lamp patch at (2167, 1386), in the Room group;
- a spent snapshot was refused;
- a whole-canvas snapshot gave OWLv2 boxes in document coordinates;
- the object-group test passed 17/17 against the new plug-in.

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

**Working on the current document (snapshots).** Once a document has been
edited, Cerebrate works on what it shows now, not on the source photo:

1. GIMP's `overmind-publish` uploads the visible composite (the selection's
   inpainting window, or the whole canvas) and the selection as a mask. It
   keeps the snapshot's region and pixel hash in the document.
2. The agent passes the URLs to a Cerebrate tool.
3. `overmind-import-artifact` with `snapshot=` places the result at the
   snapshot's origin plus its offset. It first re-renders that region and
   compares hashes: an optimistic concurrency check. A document edited in the
   meantime is refused rather than silently patched.

The agent only ever handles URLs.

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

**Object groups (2026-10-26).**
- **Structure.** Each object or surface is a GIMP layer group holding its
  original pixels and its repairs, so patches move with their object and stay
  editable. The photo itself stays as a hidden bottom layer.
- **`overmind-make-object-group`** creates the group around a fresh cutout
  and records an *anchor* (a parasite saved in the `.xcf`).
- **`overmind-import-artifact` with a target** places a patch into that
  object's group, at its photo offset plus the group's movement since the
  anchor, after the context check:
  - the check refuses a mismatch, a target with too few overlapping pixels,
    or a group scaled since anchoring;
  - `force` overrides all three.

The integration test passed **17/17** on bedroom.jpg, through `pdb_call` and
layer ops only:
1. hidden original;
2. bed cut out, then grouped, then the group moved;
3. two repairs, one targeting the cutout and one the group, landing in order
   inside the group, offset by the move, and shown pixel for pixel;
4. a second group move moved all members;
5. the lamp repair created a "Room" group around the working layer, now
   "Room (original)";
6. refusals: a wrong object, stale pixels, a scaled group; `force` still
   places.

The check's margin: on unchanged pixels, GIMP's and the server's JPEG
decodes differ by a mean of 0.03–0.05 levels (max 3), against a threshold of
6. The stale case had 16.9% of its ring pixels off by more than 40.

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
