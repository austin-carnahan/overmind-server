# cerebrate-supervisor

Phase B Stage 1 of the
[Operational Model Catalog v4](../../../design-notes/cerebrate_pixel6_operational_model_catalog_v4.md):
the missing execution channel between the Debian guest (where MLServer
runs) and the Android host (where `cerebrate-infer`/`cerebrate-generate`
actually run).

## The problem this solves

MLServer's `load()`/`unload()` today can only *connect* to a worker that
already exists — there is no way for anything running in the guest to
actually start or stop an Android-host process. That's not a missing
line of code in the adapters; it's a missing execution channel entirely.
The guest has no SSH/ADB server on the Android side to exec into, and the
unprivileged `shell` user ADB always launches as can't reach
`/dev/vsock` either (`Permission denied` — see
[cerebrate-infer/README.md](../cerebrate-infer/README.md#why-this-still-binds-000)).
The one proven transport is AVF-gateway TCP, the same path
`cerebrate-infer`/`cerebrate-generate` already use for inference calls.

`cerebrate-supervisor` is a small, purpose-built control service on that
same transport (port **8767**) — not a general remote shell. It only
knows about two fixed worker types with fixed binaries and fixed ports,
and only accepts model paths inside one fixed staging directory.

## Protocol

One command per connection. Client sends a command line, then zero or
more `key: value` lines, terminated by a blank line or EOF. Server sends
exactly one text response, then closes.

```text
START
worker: generate
model: /data/local/tmp/SmolLM2_135M_Instruct.litertlm
backend: cpu

STOP
worker: infer

STATUS
worker: infer

LIST
```

`worker` is `infer` or `generate` — nothing else is recognized. `backend`
(`cpu` or `gpu`) is required for `generate`, ignored for `infer`. Ports
are **never** client-supplied; each worker type has one fixed port
(`infer` 8765, `generate` 8766) baked into the supervisor.

Responses are single lines like `OK: started pid=1234 port=8765`,
`OK: already running pid=1234 port=8765 (idempotent)`,
`ERROR: model path not approved: ...`, or (for `LIST`) one status line
per worker. `START`/`STOP` are idempotent by design: starting an
already-running worker with the same configuration, or stopping an
already-stopped one, succeeds harmlessly rather than erroring — this is
what makes restart/recovery logic simple to build on top of later.

## Least-privilege model-path check

A model path must be a flat file directly inside `/data/local/tmp/` —
no `..`, no subdirectories, nothing outside that one directory. This
matches [`scripts/stage-model`](../../../scripts/stage-model)'s existing
flat staging layout exactly; the supervisor doesn't invent a new one.
Verified directly: a `..` traversal attempt, a subdirectory path, and a
path outside `/data/local/tmp/` were all tried and rejected.

## What Stage 1 actually found

### 1A/1B — the protocol works, and there was a real fork/exec bug

`START`, `STOP`, `STATUS`, and `LIST` were all exercised against the real
device and the two real production models (not a mock), including the
error paths (bad worker name, bad model path, bad backend, missing
fields, unknown command) and idempotency (`START` twice, `STOP` twice).

One real bug surfaced during testing, not left latent: the first
implementation forked a worker process while the just-`accept()`ed
control-connection socket (and the listening socket) were still open.
`fork()` duplicates all open file descriptors, and `execl()` doesn't
close non-`FD_CLOEXEC` ones — so the exec'd worker silently held a
duplicate of the client connection open for its **entire lifetime**.
Every command that didn't fork (`STOP`, `STATUS`, `LIST`) worked
instantly; every `START` call hung forever, because the client's
read-until-EOF response loop never saw EOF while that duplicate fd was
still open somewhere. Fixed by closing both fds in the child immediately
after `fork()`, before `setsid()`/`execl()`. Re-verified after the fix:
`START` now returns in ~1-2s (dominated by NNAPI/LiteRT-LM init), not by
hanging.

Crash detection was verified with a real `kill -9` against a running
`generate` worker mid-test, not simulated: `STATUS` correctly reported
`EXITED pid=... exit_code=-9`, and a subsequent `START` recovered
cleanly.

### 1C — supervisor bootstrap: solved for "survives this SSH/ADB session ending," not for "survives a reboot"

Launching via a single `adb shell 'cmd &'` invocation reproduces the
same problem already documented in
[cerebrate-infer/README.md](../cerebrate-infer/README.md#deploy) — a
backgrounded process died when that invocation's connection ended. The
fix here goes one step further than "keep a foreground `adb shell`
session open forever" (today's pattern for `cerebrate-infer`/
`cerebrate-generate`, which is itself a standing liveness dependency on
an interactive session): `nohup setsid` plus fully redirecting all three
standard fds away from the adb pty/pipe:

```bash
adb shell 'cd /data/local/tmp && LD_LIBRARY_PATH=/data/local/tmp nohup setsid ./cerebrate-supervisor > supervisor.log 2>&1 < /dev/null &'
```

Verified empirically: the supervisor stayed alive and reachable over TCP
from a completely separate connection while the original launching `adb
shell` invocation was still hung (a separate, known adb quirk — the
invocation itself doesn't return promptly even though the backgrounded
process is fully detached; this is cosmetic, not a liveness problem).
Killing the local end of that original invocation did not kill the
supervisor.

**Not solved, and deliberately not required for this stage**: surviving
an Android reboot. There is no init-level service on stock, unrooted
Android that this project can install into — `nohup setsid` only
detaches from the *current session*, it does not persist across a
reboot. Today, after a reboot, the supervisor (and thus both workers)
must be relaunched via the command above through ADB — exactly the
manual-intervention story already accepted for `cerebrate-infer`/
`cerebrate-generate`, not a regression. A real fix here is a minimal
Android foreground-service host wrapping the native supervisor binary —
real engineering, explicitly deferred rather than bolted on early.

## Explicitly not built

- **No arbitrary command execution** — only two fixed worker types, two
  fixed binaries, two fixed ports.
- **No orphan-worker adoption.** If the supervisor itself is killed and
  relaunched, workers it previously started keep running (reparented to
  `init`), but the new supervisor process has no memory of them — its
  in-memory state starts at `STOPPED` for everything, confirmed exactly
  in Phase B Stage 3 below. `STATUS`/`LIST` are wrong until an operator
  reconciles it. `START` against an orphaned port is caught and refused
  with a clear error (Stage 3 fix, see below) rather than silently
  reporting false success — but there is still no automatic adoption; a
  human has to find and kill the orphan (or just use it as-is) before
  a tracked restart is possible. A future version could scan for a
  process already bound to a worker's fixed port at startup and adopt
  its PID; not built here.
- **No automatic respawn-on-crash.** `STATUS` reports `EXITED`
  accurately; nothing restarts it automatically. Per the Phase B design
  discussion, this is intentional for Stage 1/2 — Stage 3 characterizes
  real failure modes before deciding which worker classes (if any)
  should auto-restart versus stay down until explicitly requested.

## Phase B Stage 3 — failure/recovery characterization (2026-09-17)

Per the Phase B design discussion: break things deliberately and record
reality, rather than deciding recovery behavior in advance. All tests run
against the real device and real production models.

### Worker crash mid-request — clean, fast failure; MLServer readiness was stale (found and fixed)

Killed `cerebrate-generate` (`kill -9`) while it was actively streaming a
real generation response. The client-facing failure was immediate and
clean: `IncompleteReadError` → `ConnectionError: ... unreachable
mid-stream` → HTTP 500, no hang. `cerebrate-supervisor`'s own `STATUS`
correctly reported `EXITED exit_code=-9` right away.

But MLServer's `/v2/repository/index` kept reporting the model `READY`
indefinitely — `self.ready` is only ever set once, at `load()` time nothing
rechecked it afterward. This directly contradicts the intended shape
("worker crashes → supervisor records EXITED → **MLServer sees model
unhealthy**"), so it was fixed, not just noted: both adapters now set
`self.ready = False` at the exact point they give up on a connection for
good (after retries are exhausted, not on the first transient blip).
Re-verified: after a confirmed-dead connection, `/v2/repository/index`
correctly reports `UNKNOWN` instead of a stale `READY`; a subsequent
`load()` call restarts the worker via the supervisor and restores `READY`
with a genuinely fresh PID.

Recovery today is **exactly one explicit `load()` call**, not automatic —
matching the deliberate choice not to auto-restart behind MLServer's back
until real operational needs justify it (see "Explicitly not built"
above). A full `systemctl restart cerebrate-mlserver` also self-heals a
crashed worker for free, since MLServer's own startup calls `load()` for
every configured model.

### Supervisor crash: workers survive untouched, but a real false-success bug was found and fixed

Killing `cerebrate-supervisor` itself confirmed the documented gap above:
both workers kept running and serving correctly (reparented to `init`,
completely unaffected), but a freshly relaunched supervisor reported both
as `STOPPED` — its in-memory bookkeeping starts empty, as expected.

Testing what `START` does against that stale state surfaced a real,
more dangerous bug, not just the already-known staleness: `START`
reported `OK: started pid=19382` for a **brand-new forked child that had
already failed with `EADDRINUSE` and exited** — because the readiness
check (`connect_probe`, a plain TCP connect to the fixed port) can't
distinguish "my new child is now serving" from "an unrelated orphan was
already listening the whole time." `cerebrate-infer`'s model/NNAPI-delegate
load takes 1-2 real seconds before it ever calls `bind()`; the orphan was
already answering on the port from the very first readiness check, so
`START` declared victory using someone else's socket while its own child
silently died moments later. `STATUS` right after showed the truth
(`EXITED exit_code=1`) — but only *after* the caller had already been told
`OK`.

Fixed with a pre-flight check: before forking at all, if our own
bookkeeping says a worker isn't running but its fixed port already
answers a connection, `START` now refuses outright
(`ERROR: port 8765 already has an unmanaged listener ...`) instead of
proceeding. Re-verified against the exact same orphan scenario: no
phantom child is spawned, the real orphan is left alone and undisturbed,
and the caller gets an honest, actionable error instead of a lie.

### Full Debian guest VM restart: fully self-healing, zero manual intervention beyond the relaunch itself

Force-stopped the Terminal app (`am force-stop
com.android.virtualization.terminal`) — confirmed the entire guest VM
(`crosvm`) died, while all three Android-host processes
(`cerebrate-supervisor`, `cerebrate-infer`, `cerebrate-generate`) were
completely unaffected, exactly as the architecture intends. Relaunched it
(`am start -n
com.android.virtualization.terminal/.new2.ui.MainActivity`) and waited
for a full fresh boot.

`pixel-tunnel.service`, `cerebrate-mlserver.service`, and
`pixel-mlserver-tunnel.service` all came back active on their own —
systemd `enable`d units, no operator action beyond the one Terminal-app
relaunch. MLServer's fresh startup `load()` calls re-ran
`_discover_avf_gateway()` and reconnected to the *same still-running*
Android-host workers (confirmed via request IDs continuing to increment
on the same long-lived `cerebrate-infer` process, never restarted) — a
real end-to-end classification succeeded immediately after boot, no
manual reconnection step anywhere.

### Not independently tested this stage

`START`/`STOP` idempotency and a nonexistent-model-path failure were
already verified in Stages 1-2 and weren't re-run here. Swapping to a
genuinely *different* model on the same worker (e.g. `STOP` a running
model, `START` a different one) is mechanically identical to the
"already running with a different configuration" guard already exercised
in Stage 2 — not re-tested with a second real model, since the catalog
only has one model per worker type today; real coverage of that path
comes with Phase E.

## Deploy

```bash
NDK=~/Library/Android/sdk/ndk/27.1.12297006
CLANGXX=$NDK/toolchains/llvm/prebuilt/darwin-x86_64/bin/aarch64-linux-android24-clang++
"$CLANGXX" -o cerebrate-supervisor cerebrate-supervisor.cc -Wall -O2

adb push cerebrate-supervisor /data/local/tmp/
adb shell chmod +x /data/local/tmp/cerebrate-supervisor
# libc++_shared.so is already staged at /data/local/tmp/ from cerebrate-infer's deploy
adb shell 'cd /data/local/tmp && LD_LIBRARY_PATH=/data/local/tmp nohup setsid ./cerebrate-supervisor > supervisor.log 2>&1 < /dev/null &'
```

Swapping the binary on a live device with production workers running
requires draining first: `STOP` every running worker via the *old*
supervisor (their config is not persisted anywhere else, so record
`LIST`'s output first), `kill` the old supervisor process, deploy the new
binary, relaunch, then `START` each worker again with the same config —
otherwise the new supervisor's pre-flight orphan-port check will
correctly, but inconveniently, refuse to manage a port a still-running
old worker never released. Done this way for the Stage 2 deploy below
with zero disruption to `infer`/`generate`.

## Doclet Service V3 Stage 2: `gguf` worker + `mmproj` field

See [`cerebrate-gguf`](../cerebrate-gguf/README.md) for the full
worker-side writeup (acceptance test, failure/recovery characterization).
On the supervisor side: one new `WorkerSlot` (`gguf`, port 8768) and one
new optional wire-protocol key (`mmproj`), needed because
`cerebrate-gguf` takes two GGUF paths (model + multimodal projector)
where every existing worker needed at most one model plus a fixed
two-value `backend` enum. Reuses every existing mechanism unchanged: flat-
file validation, idempotent START/STOP, config-conflict detection (now
comparing `mmproj` too when the slot needs it), crash detection, and the
pre-flight orphan-port check.

## Segmentation and Labeling Lane Step 1: `graph1`–`graph3` slots (2026-10-23)

**Deployed 2026-10-23** (see the deploy record at the end of this section). Three
identical slots for [`cerebrate-graph`](../cerebrate-graph/README.md), the
general-purpose ONNX Runtime worker, on fixed ports **8769, 8770, 8771**. One
model per process stays the rule (catalog v4 Section 8), so a pipeline that
needs a detector, a SAM encoder, and a SAM decoder resident at once uses three
slots. No wire-protocol change.

Two internal generalizations came with it:

- **Per-slot backend lists.** The hardcoded `cpu|gpu` check became an
  allowed list on each slot: `generate` keeps `cpu,gpu`; the graph slots
  accept `cpu,nnapi,nnapi16,xnnpack,webgpu`.
- **Per-slot readiness timeout.** `START` waits up to 120 s for a graph slot
  (large ONNX models and NNAPI compilation load slowly) and 15 s for the
  existing slots, unchanged. The supervisor is single-threaded, so other
  commands queue behind a slow graph `START`.

The `LIST` response buffer grew to 2 KB for six status lines.

Tested on the Mac with a scratch copy pointing `STAGING_DIR` at a local
directory and running the macOS build of `cerebrate-graph`: bad backend
(rejected, listing the allowed set), path outside staging (rejected), two
graph slots started concurrently with different backends, idempotent
`START`, configuration conflict, `generate` still rejecting graph backends,
`LIST`, crash detection (`kill -9` → `EXITED exit_code=-9`), `STOP`.

### Deploy record (2026-10-23)

Drain-and-swap per [Deploy](#deploy), driven from `overmind-01` over its
wireless ADB pairing and the supervisor's LAN port:

1. Recorded `LIST` (all three workers `RUNNING`, configs as in the catalog).
2. Pushed the new binary as `cerebrate-supervisor.new` (sha256 `908f5620…48fd9`)
   and copied the running one to **`cerebrate-supervisor.prev`** (`b1fa7d1e…15c4`)
   as the rollback.
3. `STOP` `gguf`, `generate`, `infer` through the old supervisor; killed it;
   moved the new binary into place; relaunched with the `nohup setsid`
   command above. It came up as `workers=infer,generate,gguf,graph1,graph2,graph3`.
4. `START` each worker with its recorded config — all `OK` on fresh PIDs.

Verified afterward through MLServer: `cerebrate-infer` classifies,
`cerebrate-generate` generates, `cerebrate-gguf` reports ready (not
exercised with a full Granite-Docling request). Total worker downtime was
seconds. **Rollback:** drain the same way, `mv cerebrate-supervisor.prev
cerebrate-supervisor`, relaunch, and `START` the three workers (the graph
slots disappear with it).

## Segmentation and Labeling Lane Step 2B: `hetero1` slot (prepared 2026-10-24, deploy scheduled)

**Built and tested side by side with production; not yet deployed.** One
slot for [`cerebrate-hetero`](../cerebrate-hetero/README.md) (TPU + GPU
pipeline worker) on fixed port **8772**. No wire-protocol change: the
slot's `backend` names one of a fixed set of **profiles** compiled into the
supervisor, and each profile carries its declared model and its complete
command line. A client still picks only among fixed configurations, never
a path or an argument:

| Profile (`backend`) | `model` must be | Worker command (after the port) |
| --- | --- | --- |
| `yoloe-v8s-fast` | `yoloe-v8s-pf-backbone-tpu-fp32.tflite` | `tpu+gpu libtensorflowlite_jni.so <backbone> yoloe-v8s-pf-head-gpu.tflite fp16acc32 yoloe-v8s-pf-gpu-nhwc.tflite fp16acc32` |
| `yoloe-v8s-default` | `yoloe-v8s-pf-gpu-nhwc.tflite` | `gpu yoloe-v8s-pf-gpu-nhwc.tflite fp32` |

All paths are flat files in `/data/local/tmp` (the approval rule is
unchanged; the files were copied out of the spike's `hetero/`
subdirectory). `START` refuses an unknown profile, a model other than the
profile's, or a missing profile file, before forking. The worker gets
`LD_LIBRARY_PATH=/data/local/tmp/litert-2.3.0:/data/local/tmp` (LiteRT 2.3
first) and `CEREBRATE_HETERO_PROFILE`/`CEREBRATE_HETERO_MODEL`, which its
DESCRIBE reports as `backend`/`model` — exactly what the MLServer graph
adapter checks. Other changes: `backend` widened from 8 to 32 characters
(profile names); `CONTROL_PORT` overridable at build time
(`-DCONTROL_PORT=8777`) for a side-by-side test instance; slot initializers
spell out the two new optional fields.

### Tests (2026-10-24, side by side with production)

A test build on control port 8777 ran next to the production supervisor
(8767), touching only `hetero1` (nothing else listens on 8772); the
production supervisor, its workers (same PIDs throughout) and MLServer were
untouched.

- [`hetero_supervisor_chain.py`](../cerebrate-hetero/tests/hetero_supervisor_chain.py):
  unknown profile, profile/model mismatch, subdirectory path, and a graph
  slot given a hetero profile — all refused. Each profile: `START` (fast
  5.3 s incl. TPU compile, default 1.5 s), `STATUS`, DESCRIBE reports the
  declared model and profile, the eight photos' outputs **bit-identical** to
  the hand-launched validated runs (all five outputs, max difference 0),
  idempotent `START`, the other profile refused while running, `STOP`.
- Through a test MLServer instance (its own ports, adapter copy pointed at
  8777) with on-demand residency — see the
  [MLServer README](../mlserver/README.md#segmentation-and-labeling-lane-step-2b--on-demand-residency-yoloe-v8s-pf-prepared-2026-10-24-deploy-scheduled):
  cold start on the first request, idle stop, kill recovery, unload.
- TPU/GPU/big cores 31–32 °C during the runs.

### Scheduled deploy runbook

Superseded by the combined YOLOE + EdgeSAM deployment below (same window,
newer worker and supervisor builds); its rollback A returns to this
YOLOE-only state.

## Test builds

`CONTROL_PORT` and (since 2026-10-25) `STAGING_DIR` are `#ifndef`-guarded:
`-DCONTROL_PORT=8777 '-DSTAGING_DIR="/data/local/tmp/edgesam/worker"'` gives a
side-by-side supervisor whose fixed profiles, worker binary, configs and logs
all live in a test directory (symlinks to the staged model files satisfy the
flat-path rule). The default build is unchanged: byte-identical to the
deployed `bad5bed3`.

## Combined deployment: YOLOE + EdgeSAM (deployed 2026-10-25, YOLOE served)

**Deployed 2026-10-25 03:43–03:45 UTC** (record at the end of this section).
**Decision 2026-10-24: the window releases YOLOE; EdgeSAM stays staged** — its worker profiles,
supervisor slot and files ship (inert), but its MLServer model waits in
`mlserver/held-models/` until the image-transport work removes MLServer's
per-request memory cost (see "MLServer memory per image request" below). One worker binary
(`cerebrate-hetero` build `fad6e56c`), **one process per model**:

| Slot | Port | Profiles (fixed `--config` file in /data/local/tmp) | MLServer model |
| --- | --- | --- | --- |
| `hetero1` | 8772 | `yoloe-v8s-fast` (TPU + GPU, GPU mixed fallback), `yoloe-v8s-default` (GPU fp32) | `yoloe-v8s-pf` (fast, on demand) |
| `hetero2` | 8773 | `edgesam3x-fast` (TPU trunk + GPU neck + GPU box decoder, exact GPU encoder fallback), `edgesam3x-default` (GPU fp32) | `edgesam3x-box` (fast, on demand) |

Each slot accepts only its own model's profiles. Every profile is a config
file ([`cerebrate-hetero/configs/`](../cerebrate-hetero/configs/)) with the
persistent NNAPI compilation cache (`/data/local/tmp/nnapi-cache`, already
populated by the tests, so the first production start is warm) and the
validated GPU fallback. The YOLOE request/response API and outputs are
unchanged. Workers bind only after every model is compiled, and MLServer's
adapter confirms model and profile by DESCRIBE before serving.

**Staged on the device** (hashes verified): `cerebrate-hetero` (`fad6e56c`,
the combined build) and `cerebrate-hetero.yoloe-only` (`bfcb8e8b`, the
previous build, kept for rollback A); the four `.conf` files; EdgeSAM's
four `.tflite` files and five decoder constants (hashes in
`models/catalog.yaml`); the YOLOE files from the earlier staging. The new
supervisor binary is this directory's `cerebrate-supervisor` (`bad5bed3`).

### Tests (2026-10-24, test supervisor on 8777, test MLServer on 18080–18082)

| Test | Result |
| --- | --- |
| [`edgesam_supervisor_chain.py`](../cerebrate-hetero/tests/edgesam_supervisor_chain.py) | 14/14: each slot refuses the other model's profiles; `edgesam3x-fast` START 46.4 s cold (empty cache, directory created), **2.5 s** from the cache, outputs bit-identical across the restart; masks vs the original: fast worst IoU 0.9441 / mean 0.99830 (the validated chain), default exact (1 px); worker-side image + 1 box 193–197 ms fast, 313 ms default; a cached box 52–57 ms |
| [`hetero_supervisor_chain.py`](../cerebrate-hetero/tests/hetero_supervisor_chain.py) (YOLOE, config profiles) | both profiles bit-identical to the validated outputs (8/8); START 6.1 s cold, ~2.2 s cached |
| [`mlserver_combined_test.py`](../cerebrate-hetero/tests/mlserver_combined_test.py) | both on-demand models READY with no workers; first requests start them from the cache; YOLOE and EdgeSAM outputs bit-identical to the direct runs, EdgeSAM cache hit identical; idle stop after the window, restart on the next request; EdgeSAM worker `kill -9` → one failed request, model stays READY, next request restarts it; unload → all slots STOPPED, refcounts 0; pinned canary unaffected |
| contention, supervisor-launched deployment configs + production MobileNet ([`hetero_contention3.py`](../cerebrate-hetero/tests/hetero_contention3.py)) | all outputs correct, no fallbacks, no MobileNet resets; EdgeSAM worker p50 195 → 248 ms, YOLOE p50 78 → 86 ms (p99 225), MobileNet p99 5.4 → 32 ms |
| rollback A rehearsal: supervisor from `aa1d8cd` (test build) + `cerebrate-hetero.yoloe-only` | 16/16, YOLOE bit-identical in both profiles, `hetero2` unknown; combined build restored and verified |

Found: **MLServer's gRPC endpoint caps requests at 4 MB** by default — YOLOE's
image (4.9 MB) and EdgeSAM's (12.6 MB) are over it; REST is unaffected
(see step 4 below). Production processes, models and the guest checkout
were unchanged throughout.

### MobileNet under TPU contention (accepted tradeoff)

With both heterogeneous workers busy, production MobileNet stays correct on
every response, its median is unchanged (2.5 ms round trip), and its p99
rises from ~5 ms to ~32–37 ms: its requests queue behind EdgeSAM's 128 ms
TPU job, since the driver runs one TPU job at a time. A lock between our
workers changes nothing (measured), so scheduling stays as it is.
Accepted 2026-10-24: MobileNet has no latency target, and the tail only
appears while EdgeSAM is encoding. Revisit if a caller needs a MobileNet
latency bound (options then: a TPU-time budget per EdgeSAM request, or
splitting EdgeSAM's TPU stage).

### Runbook (combined)

Expected MLServer downtime about a minute; a restart is required (the adapter
module changed).

1. Record `LIST` from the production supervisor (expected: `infer`,
   `generate`, `gguf`, `graph3` RUNNING).
2. In the guest: `sudo systemctl stop cerebrate-mlserver`; confirm `LIST`
   shows everything STOPPED; `STOP` anything left.
3. Swap the supervisor: push this directory's binary as
   `cerebrate-supervisor.new` (`bad5bed3`); copy the running one
   (`908f5620…48fd9`) over `cerebrate-supervisor.prev`; kill the old
   supervisor; move the new one into place; relaunch with the `nohup
   setsid` command. Its READY line must list `…,graph3,hetero1,hetero2`.
4. **gRPC message limit (approved 2026-10-24):** add
   `Environment=MLSERVER_GRPC_MAX_MESSAGE_LENGTH=33554432` (32 MiB) to
   `/etc/systemd/system/cerebrate-mlserver.service`, then `sudo systemctl
   daemon-reload`. Verified with full-size payloads on a test instance:
   YOLOE 4.9 MB in / 4.6 MB out and EdgeSAM 12.6 MB in / 7.3 MB out
   (28 boxes) pass, bit-identical. Clients must raise their own receive
   limit (gRPC's client default, 4 MiB, refuses YOLOE's response).
5. In the guest: `git pull --ff-only` (the adapter and `yoloe-v8s-pf`;
   `edgesam3x-box` arrives under `held-models/`, which MLServer doesn't load).
6. `sudo systemctl start cerebrate-mlserver`.
7. Verify (the window's gate):
   - repository index all READY including `yoloe-v8s-pf`, and no
     `edgesam3x-box`;
   - `LIST` shows the four workers RUNNING and `hetero1`, `hetero2` STOPPED;
   - full-size gRPC through production with a client receive limit of
     32 MiB: `mlserver_grpc_limits.py`'s YOLOE case, or the first YOLOE
     lines of `mlserver_combined_test.py infer 127.0.0.1:8081 <gateway>
     8767 /home/droid/cg-test/hetero /home/droid/cg-test/edgesam` (stop it
     before its EdgeSAM lines, or run the YOLOE function alone) → outputs
     identical to the validated run, `hetero1` RUNNING with `load_us`
     ~2.2 s (from the cache);
   - MobileNet classifies 795; the catalog validates (task defaults and
     fallbacks resolve to served profiles); a temperature reading;
   - ten minutes later `hetero1` is STOPPED again.

**Rollback A — to the YOLOE-only build** (rehearsed): stop MLServer,
confirm every slot STOPPED; kill the supervisor; install the supervisor
binary from commit `aa1d8cd` (`git show
aa1d8cd:hosts/cerebrate-pixel6/cerebrate-supervisor/cerebrate-supervisor`,
`0921ae22…068a`) and relaunch; `cp cerebrate-hetero.yoloe-only
cerebrate-hetero`; in the guest check out `aa1d8cd`; start MLServer.

**Rollback B — to the pre-deployment state:** stop MLServer, confirm every
slot STOPPED; kill the supervisor; `mv cerebrate-supervisor.prev
cerebrate-supervisor`; relaunch; in the guest check out `248c6e3`; start
MLServer. Staged files and the compilation cache are inert without the
slots. In either rollback the gRPC limit line can stay (it only raises a
cap) or be removed with another `daemon-reload`.

**Go/no-go at the window:** if full-size gRPC requests fail or model
readiness is inconsistent, roll back rather than switch clients to REST.

### MLServer memory per image request (decided: EdgeSAM held)

MLServer 1.7 converts every tensor to a Python list, even raw gRPC bytes
(`mlserver/raw.py` `inject_raw` unpacks into lists; responses go through
`NumpyCodec`'s `.tolist()`), so its memory scales with element count, not
bytes. Measured on a test MLServer (gRPC, raw bytes; peak resident memory
over a 124–129 MB idle baseline, transient):

| Request | Peak increase |
| --- | --- |
| YOLOE, full-size image | +125–133 MB |
| EdgeSAM, image + 1 box | +196 MB |
| EdgeSAM, image + 24 boxes | +279 MB (~3.6 MB per extra box) |
| EdgeSAM, image + 120 boxes | the guest's OOM killer killed the test instance (production MLServer unaffected: same PID, no restart) |

The guest has ~530–650 MB available beside production MLServer: one
request of either model fits, but overlapping large requests (two EdgeSAM,
or EdgeSAM with many boxes beside YOLOE) could get production MLServer
OOM-killed (systemd restarts it; every MLServer model would be down for the
restart). The fix belongs to the transport work: an image sent as a
compressed BYTES tensor (MLServer keeps BYTES as bytes) and compact mask
outputs. **Decided 2026-10-24: YOLOE ships in the window (one request's
+125–133 MB fits; no consumer sends concurrent YOLOE requests yet);
EdgeSAM's MLServer model waits for the transport fix** — no production
consumer uses it yet, so serving it now would add risk without benefit.

### Deploy record (2026-10-25)

Run from the Mac over overmind-01's ADB pairing and the guest, per the
runbook:

1. Pre-flight: staged files re-verified by hash; running supervisor
   `908f5620`, deploy binary `bad5bed3`; guest clean at `248c6e3`,
   fast-forwardable to `a3b4fc3`. `LIST`: `infer`, `generate`, `gguf`,
   `graph3` RUNNING (configs as in the catalog / model settings).
2. 03:43:30 `systemctl stop cerebrate-mlserver`. **MLServer's shutdown
   left all four workers running** (its unloads didn't STOP them), so they
   were stopped through the supervisor, as the runbook allows.
3. Supervisor swapped: `908f5620` saved as `cerebrate-supervisor.prev` (rollback
   B), `bad5bed3` in place, READY with `…,graph3,hetero1,hetero2`.
4. Unit: `Environment=MLSERVER_GRPC_MAX_MESSAGE_LENGTH=33554432` added
   (previous unit saved as `/home/droid/cerebrate-mlserver.service.pre-hetero-2026-10-24`),
   `daemon-reload`.
5. Guest `git pull --ff-only` → `a3b4fc3`.
6. 03:44:39 MLServer active: six models READY including `yoloe-v8s-pf`, no
   `edgesam3x-box`; the pinned models restarted their workers through the
   new supervisor on fresh PIDs. **MLServer downtime ~70 s.**
7. Gate — **PASS**: 8/8 full-size YOLOE requests through production gRPC
   (32 MiB client limit; 4.9 MB in, 4.6 MB out) bit-identical to the
   validated outputs, backend 1 (TPU + GPU), worker 78–81 ms, round trip
   ~0.6 s; `hetero1` started on demand from the compilation cache
   (`load_us` 2.16 s); MobileNet 20/20 classified 795; catalog valid;
   TPU 24 °C, GPU 25 °C, big cores 29 °C. Idle stop: `hetero1` STOPPED at
   03:55:37, ten minutes after the last gate request, with every model
   still READY.

Rollback A (YOLOE-only build) and B (pre-deployment, `.prev` + guest
`248c6e3` + the saved unit) remain available.

