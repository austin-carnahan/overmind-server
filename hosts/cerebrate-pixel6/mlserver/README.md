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

The Python virtualenv itself (`~/mlserver17-venv` on the guest) is
**not** committed — only `requirements.txt` is. **Requires Python
3.12** (see "MLServer version" below for why) — Debian 13's default
`python3` is 3.13, which is outside MLServer's supported range, so this
venv is built on a separately-obtained Python 3.12 via
[`uv`](https://github.com/astral-sh/uv) (a static binary, no compiling
Python from source, no apt package needed — trixie doesn't ship one):

```sh
uv python install 3.12
uv venv --python 3.12 ~/mlserver17-venv
uv pip install --python ~/mlserver17-venv/bin/python3 -r requirements.txt
```

Do not create the venv inside this repo checkout and then move it — venv
scripts embed the venv's absolute path in their shebang line at creation
time, so moving the directory breaks every entry point (`mlserver`, `pip`,
etc.) with an opaque exec failure. Create it at its final path directly.
Note `uv`-created venvs don't bundle `pip` — use `uv pip install
--python <venv>/bin/python3 ...` instead of activating and calling `pip`
directly.

## MLServer version: 1.7.1, not 1.3.5 (corrected 2026-09-17)

Phase 1's original `pip install mlserver` silently resolved to
**1.3.5** — not because that was the newest released version, but
because PyPI's actual latest stable release, **1.7.1**, declares
`requires_python: <3.13,>=3.9`, and the guest's system Python is 3.13.
`pip` quietly picked the newest version compatible with that
interpreter, with no obvious warning that a newer release existed.
Verified directly against PyPI's raw release metadata (not `pip index`,
which filters by the running interpreter and would hide this same way)
before concluding anything.

This mattered because 1.3.5 predates MLServer's real, released
streaming support (`infer_stream`/`generate_stream`, REST and gRPC) —
confirmed by grepping the installed 1.3.5 package for those symbols and
finding nothing, versus finding real streaming code throughout 1.7.1's
`dataplane.py`, `rest/app.py`, `rest/endpoints.py`. The fix was a
version/environment correction, not a fundamental absence of the
feature in any released MLServer — no GitHub-master install, no
bespoke SSE server needed. See
[`cerebrate-generate`'s MLServer adapter README](models/cerebrate-generate/README.md)
and the [Multi-Runtime Execution Plane](../../../design-notes/Cerebrate%20Pixel%206%20%E2%80%94%20Multi-Runtime%20Execution%20Plane.md)
design notes for the full gated migration (A: prove existing models
survive the upgrade in a disposable environment; B: prove streaming
itself works with a trivial fake model; C/D: wire the real thing) that
preceded promoting 1.7.1 to production.

## Known issue: MLServer's parallel worker pool crashes on this stack

MLServer's multiprocessing worker pool
(`mlserver/parallel/worker.py`, `asyncio.get_event_loop()` called
outside a running loop) throws
`RuntimeError: There is no current event loop in thread 'MainThread'`
under `uvloop` in this environment (originally hit under 1.3.5/Python
3.13; not re-verified as fixed under 1.7.1/Python 3.12, so the
workaround stays). A `parallel_workers` value in `settings.json` was
not reliably honored in testing; setting the environment variable
directly was:

```sh
MLSERVER_PARALLEL_WORKERS=0
```

This is set in the systemd unit. It's also the architecturally correct
choice independent of the bug: `cerebrate-infer` and `cerebrate-generate`
(the Android-host backends) each serialize requests one at a time on a
single persistent worker, so a multi-process worker pool on the
MLServer side has no downstream backend to parallelize against. It also
happens to be one of two settings MLServer's own documentation calls
out as required for streaming to work at all (the other is disabling
gzip — see the adapter README linked above).

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
Environment=MLSERVER_HOST=127.0.0.1
Environment=MLSERVER_HTTP_PORT=8080
Environment=MLSERVER_GRPC_PORT=8081
Environment=MLSERVER_METRICS_PORT=8082
Environment=MLSERVER_GZIP_ENABLED=false
ExecStart=/home/droid/mlserver17-venv/bin/mlserver start /home/droid/code/overmind-server/hosts/cerebrate-pixel6/mlserver/models
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

(`MLSERVER_HOST=127.0.0.1` was added in Stage 5 Phase 4 to keep MLServer
off the LAN-facing interface; `MLSERVER_GZIP_ENABLED=false` was added
for streaming, in the MLServer 1.7.1 upgrade above — gzip middleware
doesn't work with streaming responses.)

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

## Phase 4 — reachable through Overmind, MLServer never LAN-facing (done, 2026-09-16)

```text
authorized client
      │  LAN / Tailscale (inference.home.arpa)
      ▼
   Overmind (Caddy)
      │  reverse_proxy host.docker.internal:8500
      ▼
socat relay (172.17.0.1:8500, Docker-bridge-only, NOT LAN-reachable)
      │  forwards to 127.0.0.1:8500
      ▼
sshd (pixel-mlserver-tunnel account) — 127.0.0.1:8500 on the Overmind host
      │  persistent reverse SSH tunnel, Debian-initiated
      ▼
MLServer :8080 — bound 127.0.0.1 only inside the Debian guest
      │
      ▼
cerebrate-infer → NNAPI → google-edgetpu → Tensor G1 TPU
```

MLServer itself never listens anywhere but loopback
(`MLSERVER_HOST=127.0.0.1`, verified via `ss -ltnp` showing `127.0.0.1`
on all three of its ports, not `0.0.0.0`). Reachability comes entirely
from Debian dialing *out*: a new, narrowly-scoped `pixel-mlserver-tunnel`
system account on Overmind — its own dedicated ed25519 key generated on
the guest (never leaves it), `authorized_keys`
`restrict,port-forwarding,permitlisten="127.0.0.1:8500",from="<pixel LAN IP>"`,
plus a matching `sshd_config` `Match User` block — mirrors the existing
`pixel-tunnel` (SSH-management) credential pattern from Stage 3 exactly,
per this repo's "every process gets its own scoped credential" rule
(`security-model.md`). Maintained by
`pixel-mlserver-tunnel.service` (systemd, `Restart=always`, `droid`
user) on the guest, keeping the tunnel binding at Overmind's `127.0.0.1`
only, same as `pixel-tunnel`'s:

```ini
[Unit]
Description=Reverse SSH tunnel to Overmind for MLServer (pixel-mlserver-tunnel)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=droid
ExecStart=/usr/bin/ssh -N -T \
  -o BatchMode=yes \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -o IdentitiesOnly=yes \
  -o StrictHostKeyChecking=yes \
  -o UserKnownHostsFile=/home/droid/.ssh/known_hosts.overmind \
  -i /home/droid/.ssh/pixel-mlserver-tunnel \
  -R 127.0.0.1:8500:127.0.0.1:8080 \
  pixel-mlserver-tunnel@overmind.home.arpa
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

On Overmind: the `pixel-mlserver-tunnel` account (system, `nologin`, no
password) with `authorized_keys` restricted to
`restrict,port-forwarding,permitlisten="127.0.0.1:8500",from="<pixel LAN
IP>"`, and a matching `sshd_config` block:

```
Match User pixel-mlserver-tunnel
    AllowTcpForwarding remote
    PermitListen 127.0.0.1:8500
    GatewayPorts no

    PermitTTY no
    X11Forwarding no
    AllowAgentForwarding no
    AllowStreamLocalForwarding no
    PermitTunnel no
    PermitUserRC no

    PasswordAuthentication no
    KbdInteractiveAuthentication no
```

And the relay unit, also on Overmind:

```ini
[Unit]
Description=Relay Docker-bridge-reachable :8500 to the loopback-only pixel-mlserver-tunnel port
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/socat TCP4-LISTEN:8500,bind=172.17.0.1,fork,reuseaddr TCP4:127.0.0.1:8500
Restart=always
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

**The one piece not in the original design: a relay hop.** Caddy runs in
its own Docker bridge network; a container can never reach a host socket
bound specifically to `127.0.0.1` (confirmed empirically — routing to
the Docker-bridge host IP worked, but got a real `Connection refused`,
since the kernel matches listening sockets by exact destination IP, and
a packet addressed to the bridge IP never matches a `127.0.0.1`-only
bind). Rather than loosen the tunnel's own bind (which would change its
security property), added a tiny single-purpose `socat` relay
(`pixel-mlserver-relay.service` on Overmind) listening only on
`172.17.0.1` — the docker0 bridge's host-side address, reachable from
containers via Docker's `host-gateway` `extra_hosts` alias, but **not**
from the LAN (it's a virtual bridge interface, not a physical one) — so
this doesn't expand exposure beyond what Caddy itself already needs.

Caddy's `inference.home.arpa` site block
(`services/caddy/Caddyfile`) reverse-proxies to
`host.docker.internal:8500`, resolved via `extra_hosts:
host.docker.internal:host-gateway` added to just the `caddy` service in
`services/caddy/compose.yaml` — every other site in that Caddyfile still
reaches a sibling container directly. DNS: `inference.home.arpa` added
to `hosts/dns-rewrites.yaml` as a **service**-tier entry pointed at
`overmind-01.home.arpa`, not at `cerebrate-pixel6` directly — deliberately
keeping which physical node serves inference out of the client-facing
contract, so a future multi-node inference fleet wouldn't require
clients to change URLs.

### A real bug found via this phase's own restart test

Testing "does the tunnel/proxy recover automatically after a restart"
surfaced a genuine, previously-undiagnosed reliability bug in
`cerebrate-infer` itself — not in anything built this phase. See
[cerebrate-infer's README](../cerebrate-infer/README.md#real-bug-found-and-fixed-a-dead-peer-can-wedge-the-whole-worker-stage-5-phase-4)
for the full writeup: a VM restart while a connection was open left the
worker permanently wedged (no accept-timeout, single-threaded serial
design), fixed with a 30s `SO_RCVTIMEO`, and verified by triggering a
real VM restart and watching the full external path recover
automatically in ~16 seconds with no manual intervention.

### LAN exposure investigated, not fully closed (documented, accepted)

`cerebrate-infer`'s own port (8765, on the Android host) is still
directly LAN-reachable, bypassing this whole Phase 4 path. Two narrower
fixes (`SO_BINDTODEVICE` on the AVF interface; `AF_VSOCK`) were tested
and empirically ruled out — see cerebrate-infer's README for the full
investigation. Accepted as an architectural looseness rather than fixed,
consistent with this project's own established threat model (LAN/Tailscale
reachability is the trust boundary; no MLServer-level auth was added for
the same reason).

### Verified (2026-09-16)

- `curl http://inference.home.arpa/v2/health/ready` → `200`, from a
  genuine external client (a Mac on the home LAN, resolving through the
  same AdGuard/Tailscale split-DNS mechanism already proven to work
  off-LAN for every other `home.arpa` service in this project).
- `GET /v2/models/cerebrate-infer` → real model metadata, through the
  full external path.
- A real Grace Hopper image submitted through `inference.home.arpa`
  returns `"military uniform"` at the same `0.8862745098039215`
  confidence as the local-only Phase 3 test — bit-for-bit identical
  result, proving the tunnel/relay/proxy chain doesn't alter the
  response.
- Confirmed each layer individually before trusting the composed chain:
  relay (`172.17.0.1:8500`) → 200; inside the Caddy container via
  `host.docker.internal:8500` → reachable; Caddy's own Host-header
  routing (`curl -H "Host: inference.home.arpa" localhost:80`) → 200;
  the real DNS name → 200.
- `ss -ltn` confirms `172.17.0.1:8500` (relay) and `127.0.0.1:8500`
  (tunnel) are both up, and separately confirms the relay port is
  **not** reachable from the LAN (`nc -z <overmind-lan-ip> 8500` fails).
- Full VM force-stop/relaunch recovery test (the same recovery procedure
  documented since Stage 3): `pixel-mlserver-tunnel.service` and
  `cerebrate-mlserver.service` both came back automatically; after the
  `SO_RCVTIMEO` fix, the full external path served a correct real-image
  classification again within ~16 seconds, unattended.

## Phase 5 — telemetry + reproducibility checkpoint (2026-09-16)

Deliberately light — this closes out Stage 5 as a checkpoint against the
plan's own success criteria, not a new round of testing. No new code.

### MLServer's built-in metrics already cover most of it

`curl http://127.0.0.1:8082/metrics` (Prometheus format, on the guest —
not exposed through the Phase 4 tunnel, which only forwards :8080)
already provides, for free, exactly what the plan asked for: per-model
`model_infer_request_success_total` / `_failure_total`, request-duration
histograms (`model_infer_request_duration_*`), and REST-layer
`rest_server_requests_total` by path/status code. Nothing custom needed
here — this was true since Phase 1, just not called out explicitly
until now.

### Supplemental Pixel telemetry: existing commands, not new code

Per the plan's own instruction ("keep this supplementation small, do
not create a parallel monitoring framework"), this is the same
`adb`-based recipe used throughout Stages 3-4 — documented here as the
canonical one-liner set, not wrapped in new tooling:

```bash
ADB="adb -s 192.168.68.60:5555"   # Overmind's independent wireless pairing

# TPU temperature + Android thermal status
$ADB shell dumpsys thermalservice | grep -A100 "Current temperatures from HAL" | grep "mName=TPU"
$ADB shell dumpsys thermalservice | grep -o "Thermal Status: [0-9]*"

# cerebrate-infer liveness (Android host, independent of the Debian guest/VM)
$ADB shell pidof cerebrate-infer

# Debian-side service liveness (from the guest itself)
sudo systemctl is-active cerebrate-mlserver.service pixel-mlserver-tunnel.service
```

Baseline snapshot at this checkpoint: TPU 28.0°C, thermal status `0`
(nominal), worker PID `24847` (the one deployed with the Phase 4
`SO_RCVTIMEO` fix), both guest-side services `active`.

### Stage 5 acceptance checklist (against the original plan's criteria)

**Functional** — from Overmind/any authorized client, via
`inference.home.arpa`: health/readiness ✓, model metadata ✓, submit a
real image ✓, receive correct labels/scores ✓, verified full-chain
execution (MLServer → adapter → `cerebrate-infer` → NNAPI → EdgeTPU →
Tensor G1) ✓.

**Operational** — runs under normal systemd supervision ✓, starts
reproducibly ✓, recovers after a Debian service/VM restart ✓ (verified
with a real restart, ~16s recovery), produces logs via `journalctl`/the
MLServer stdout log ✓, health+metrics sufficient to diagnose normal
failures ✓, no USB-connected workstation required for normal operation
✓ (everything reachable via Overmind's independent wireless ADB pairing
and the reverse tunnels).

**Reproducibility** — dependencies pinned (`requirements.txt`) ✓,
MLServer config documented (env vars, not a gitignored `settings.json`)
✓, custom runtime committed (`cerebrate_infer_runtime.py`) ✓,
systemd/sshd unit definitions committed verbatim (Phase 4 section
above) ✓, model placement documented ✓, network assumptions documented
(AVF gateway instability, Docker-bridge relay necessity) ✓, test
commands documented throughout each phase section above ✓, known
lifecycle limitations documented (LAN-reachable `cerebrate-infer` port,
investigated and accepted; the earlier wedge bug, found and fixed) ✓.

**Scope discipline** — no multi-node scheduler, model registry, or
workflow engine was built; `cerebrate-infer` remains the sole
hardware-facing boundary; the MLServer adapter stayed a thin
protocol/data-shape translator throughout all four phases.

### What this checkpoint is not

Not exhaustively soak-tested through the new Phase 4 path (Stage 4D's
hours-long saturation/soak testing was done against the pre-tunnel
local path only). Not a claim that the LAN-exposure or
one-model-only-MobileNet limitations are resolved — both are explicitly
carried forward, not hidden. This is a checkpoint reflecting real,
verified, working state today, not a declaration that Stage 5 can never
be revisited.
