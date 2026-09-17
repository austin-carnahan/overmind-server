# MLServer baseline (Stage 5, Phase 1)

Standardized serving layer for `cerebrate-pixel6`, per
[Stage 5 — Standardized Pixel Inference Service](../../../design-notes/Stage%205%20%E2%80%94%20Standardized%20Pixel%20Inference%20Service.md).
Phase 1 only: prove MLServer itself runs acceptably on this
memory-constrained guest, under normal systemd supervision, with a trivial
echo model. No Pixel-specific adapter yet — that's Phase 2.

## Layout

```text
hosts/cerebrate-pixel6/mlserver/
├── requirements.txt              # pinned, from `pip freeze` inside the venv
├── models/
│   └── example-echo/
│       ├── model.py              # trivial echo MLModel, Phase 1 placeholder
│       └── model-settings.json
└── README.md
```

The Python virtualenv itself (`~/mlserver-venv` on the guest) is **not**
committed — only `requirements.txt` is. Recreate it with:

```sh
python3 -m venv ~/mlserver-venv
~/mlserver-venv/bin/pip install -r requirements.txt
```

Do not create the venv inside this repo checkout and then move it — venv
scripts embed the venv's absolute path in their shebang line at creation
time, so moving the directory breaks every entry point (`mlserver`, `pip`,
etc.) with an opaque exec failure. Create it at its final path directly.

## Known issue: MLServer's parallel worker pool crashes on this stack

MLServer 1.3.5 on Python 3.13 with `uvloop` throws
`RuntimeError: There is no current event loop in thread 'MainThread'` in
its multiprocessing worker pool (`mlserver/parallel/worker.py`,
`asyncio.get_event_loop()` called outside a running loop). A
`parallel_workers` value in `settings.json` was not reliably honored in
testing; setting the environment variable directly was:

```sh
MLSERVER_PARALLEL_WORKERS=0
```

This is set in the systemd unit. It's also the architecturally correct
choice independent of the bug: `cerebrate-infer` (the eventual backend,
Phase 2+) serializes requests one at a time on a single persistent Android
worker, so a multi-process worker pool on the MLServer side has no
downstream backend to parallelize against.

No `settings.json` is committed at the repository root — this repo's
top-level `.gitignore` excludes any file literally named `settings.json`
(a pattern meant for local/secret config elsewhere in the repo), so
server-wide MLServer settings (ports, `parallel_workers`) are passed as
environment variables in the systemd unit instead of a settings file. This
also keeps the one source of truth for those values in a single committed
file (the unit) rather than splitting it across a gitignored file and the
unit's `Environment=` lines.

## systemd unit

Installed at `/etc/systemd/system/cerebrate-mlserver.service` on the guest
(not committed as a live symlinked file, since systemd units aren't
tracked live elsewhere in this repo either — copy it manually per the
block below, matching the venv/repo paths for the `droid` user):

```ini
[Unit]
Description=MLServer standardized inference service (cerebrate-pixel6, Stage 5)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=droid
WorkingDirectory=/home/droid/code/overmind-server/hosts/cerebrate-pixel6/mlserver
Environment=MLSERVER_PARALLEL_WORKERS=0
Environment=MLSERVER_HTTP_PORT=8080
Environment=MLSERVER_GRPC_PORT=8081
Environment=MLSERVER_METRICS_PORT=8082
ExecStart=/home/droid/mlserver-venv/bin/mlserver start /home/droid/code/overmind-server/hosts/cerebrate-pixel6/mlserver/models
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

## Verified (2026-09-16)

- `GET /v2/health/live`, `GET /v2/health/ready`,
  `GET /v2/models/example-echo/ready` all return `200`.
- `POST /v2/models/example-echo/infer` round-trips a real V2 payload
  correctly (echoes input tensor back unchanged).
- `systemctl kill -9` on the main process is followed by an automatic
  restart (`Restart=on-failure`) and the model reloads within ~2s.
- Enabled at boot (`systemctl enable`).

## Baseline resource usage

Single MLServer process, `parallel_workers=0` (no additional worker
subprocesses beyond a small `multiprocessing.resource_tracker` helper):

| condition | RSS |
| --- | --- |
| idle, just started | ~118.7 MB |
| after 200 sequential inference requests | ~118.9 MB (flat, no growth) |
| under systemd (`systemctl status`) | ~75-80 MB reported `Memory:` (cgroup accounting differs slightly from `/proc` RSS) |

Guest total RAM is 959 MB (~665 MB available at idle before MLServer). A
~120 MB steady-state footprint leaves comfortable headroom for Phase 2's
adapter and normal guest operation — `cerebrate-infer` itself runs on the
**Android host**, not in this guest, so it does not compete with this
budget.

## Phase 2 — `cerebrate-infer` custom runtime adapter (done, 2026-09-16)

```text
hosts/cerebrate-pixel6/mlserver/models/cerebrate-infer/
├── cerebrate_infer_runtime.py   # the adapter (CerebrateInferRuntime)
└── model-settings.json
```

A thin protocol adapter, nothing more: on `predict()`, it writes a single
trigger byte over a persistent TCP connection to `cerebrate-infer`
(`10.70.217.78:8765` by default — the real Debian→AVF-gateway→Android-host
path used throughout Stage 4D, not the ADB/loopback lab path), parses the
one-line response (`request_id=... top_class=... top_score=...
inference_us=... handle_us=...`), and returns those five fields as V2
`INT64` outputs. It does not reimplement TFLite, NNAPI, or accelerator
selection, and it does not yet do real image input/output — Phase 3's
job. `cerebrate-infer` itself still always classifies its fixed internal
dummy tensor regardless of what triggers it.

Connection handling: one persistent `asyncio` TCP connection, reused
across requests (serialized with a lock, matching `cerebrate-infer`'s own
one-request-at-a-time design), with a single reconnect-and-retry on any
`ConnectionError`/`OSError`/timeout before raising. Host/port are
configurable via `parameters.extra` in `model-settings.json`.

Verified end to end from inside the guest (`curl localhost:8080`, not yet
exposed externally — that's Phase 4):

- `GET /v2/models/cerebrate-infer/ready` → `200`.
- `POST /v2/models/cerebrate-infer/infer` → correct `top_class=795`,
  `top_score=120` (the known MobileNet dummy-input result), with
  `request_id` continuing the same monotonic counter as the native
  `nc`-based tests from Stage 4D — confirms the adapter is really talking
  to the same long-running worker process (PID unchanged throughout,
  `28046`), not spawning anything new.
- Cold/warm latency nuance reproduced exactly as documented in Stage 4:
  first request after idle ~9.2ms `inference_us`, settling to
  ~1.25-1.3ms on the next two.
- 100/100 requests over the same reused connection returned `200`, no
  errors, no reconnects needed.
- MLServer RSS after adding this model and running the burst: ~118.8 MB
  — effectively unchanged from the Phase 1 example-echo-only baseline,
  confirming the adapter itself adds negligible memory overhead.

## Phase 3 — real image classification (done, 2026-09-16)

Two changes, one on each side of the AVF network boundary:

**`cerebrate-infer.cc` wire format changed.** It previously ignored
request content entirely and always ran inference on a fixed
`i % 256` dummy pattern; a request was just any non-empty read to
trigger one inference cycle. It now reads **exactly `input_size` raw
bytes** (224×224×3 = 150528 for the currently-deployed MobileNet v1
1.0 224 quantized model) per request — the real input tensor, RGB,
uint8, no further encoding — and classifies that. Framing is implicit
from the fixed, known-at-startup size; there's no length prefix or
delimiter, and a client that sends a partial payload and closes is
treated as a dropped connection, not an error response. This is a
breaking protocol change from Stage 4D's throwaway `/tmp` load-test
scripts (which only ever sent a bare trigger byte) — those scripts were
never committed and aren't expected to keep working.

**The MLServer adapter now does real preprocessing/postprocessing.**
`cerebrate_infer_runtime.py` accepts a V2 `BYTES` input (any image
format Pillow can decode, sent as base64 with
`parameters.content_type = "base64"` — the standard MLServer/KServe V2
convention for binary payloads), decodes it, converts to RGB, resizes
to 224×224, and sends the raw HWC uint8 bytes to `cerebrate-infer`
exactly as it now expects. On the way back, `top_class` is mapped
through `imagenet_labels.txt` (the standard 1001-entry TensorFlow
ImageNet label list, index 0 = `background` — fetched from
`storage.googleapis.com/download.tensorflow.org/data/ImageNetLabels.txt`,
matching this model's output ordering) into a human-readable `label`
output, and `top_score` (a raw quantized `uint8` 0-255 confidence) is
normalized to a `confidence` float via `/255.0`. The raw diagnostic
fields (`request_id`, `top_class`, `inference_us`, `handle_us`) are
still returned alongside, for continuity with Stage 4D's data. This is
still tied to one specific model/input shape (constants at the top of
the file) — not a general multi-model runtime.

Verified with real, meaningful images, not just protocol plumbing:

- The standard Grace Hopper TensorFlow reference JPEG classifies as
  **`"military uniform"` at 88.6% confidence** — the well-documented
  expected result for this exact model, confirming the full chain
  (decode → resize → NNAPI/EdgeTPU → argmax → label lookup) is
  correct, not just wired together.
- A solid-color synthetic JPEG (no real object) classifies as
  `"corkscrew"` at 2.7% confidence — low-confidence, content-sensitive
  output on out-of-distribution input, as expected, confirming the
  server is genuinely responding to pixel content and not returning a
  fixed result.
- The confidence math checks out exactly: `226/255 = 0.8862745...`
  matches the returned float precisely.
- 30/30 repeated requests against the same image returned the
  identical correct label, ~46ms average wall time per request
  (includes base64 decode, JPEG decode, resize, and the real
  network+inference round-trip — Pillow's decode/resize is synchronous
  and currently runs inline in `predict()`, not offloaded to a thread;
  acceptable for this phase's single-client scope, worth revisiting if
  concurrent requests ever matter).
- MLServer RSS: ~122.6 MB after the batch, up only ~4MB from Phase 2's
  118.8MB baseline — Pillow's own footprint, no growth signal across
  the batch.

## Not yet done (later phases)

- Reachability through Overmind's existing access architecture (Phase 4).
- Supplemental Pixel telemetry (TPU temp, thermal status, worker
  liveness) alongside MLServer's own metrics (Phase 5).
