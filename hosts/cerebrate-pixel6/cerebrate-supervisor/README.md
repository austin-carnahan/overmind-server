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

## Image transport release: photo in, final results out, EdgeSAM served (deployed 2026-10-25)

One restart for both transport steps and EdgeSAM's release. Phone side:
the uint8-capable worker (`cerebrate-hetero` `7554324e`) and the four config
files with `input_uint8` (repo `cerebrate-hetero/configs/`); the supervisor
is unchanged (`bad5bed3` = the default build of the current source). Guest
side: `opencv-python-headless==5.0.0.93` in the MLServer venv, and the
checkout with the photo hooks, postprocessing, labels and `edgesam3x-box`
back in `models/`. The new configs must not reach the running worker build
(`fad6e56c` rejects the unknown keys), so they're staged under `.transport`
names and moved into place only with the worker stopped.

**Runbook**

1. Pre-flight: staged `.transport` files verified by hash; `LIST` recorded;
   guest checkout clean.
2. `sudo systemctl stop cerebrate-mlserver`; STOP any worker still running
   through the supervisor (MLServer's shutdown doesn't).
3. Phone: keep `cerebrate-hetero` and the four `.conf` as `*.combined`
   (rollback), move the `.transport` files into place, verify hashes.
4. Guest: unpack the OpenCV wheel into the venv's `site-packages` (the venv
   has no pip; a wheel is a zip) and check `import cv2` with the venv's
   Python.
5. Guest: `git pull --ff-only`.
6. `sudo systemctl start cerebrate-mlserver`: seven models READY, including
   `yoloe-v8s-pf` and `edgesam3x-box`.
7. Gate (roll back on any failure): `mlserver_result_test.py` against
   production gRPC (8081) — YOLOE result mode equal to the validated
   postprocessing 8/8 and raw mode bit-identical 8/8; EdgeSAM result mode
   8/8 and cached 8/8; MLServer peak memory flat per request; MobileNet 795;
   catalog valid; temperatures; both slots idle-stop after ten minutes.

**Rollback** (to the YOLOE-only service of 2026-10-25): stop MLServer and
STOP the workers; on the phone move the `*.combined` files back; in the guest
check out `196f8d0`; start MLServer. OpenCV can stay (unused) or be removed
(its `cv2/`, `opencv_python_headless*` entries in `site-packages`). Rollbacks A
and B above remain available behind that.

### Deploy record (2026-10-25, 05:49–05:51 UTC)

1. Pre-flight: `.transport` files verified by hash; guest clean at `196f8d0`;
   `LIST`: `infer`, `generate`, `gguf`, `graph3` RUNNING, hetero slots
   STOPPED.
2. 05:49:24 MLServer stopped; the four workers STOPPED through the
   supervisor.
3. Phone: `cerebrate-hetero` (`fad6e56c`) and the four configs kept as
   `*.combined`; `7554324e` and the uint8 configs moved into place, hashes
   verified.
4. Guest: OpenCV wheel (`10818d91…`) unpacked into the venv's
   `site-packages` (`cv2/`, `opencv_python_headless.libs/`, its dist-info;
   nothing pre-existing touched); `import cv2` → 5.0.0.
5. Guest `git pull` → `03aade6`.
6. 05:50:25 MLServer active, seven models READY including `edgesam3x-box`.
   **MLServer downtime ~61 s.**
7. Gate — **PASS** (`mlserver_result_test.py` on production gRPC): YOLOE
   result mode = the validated postprocessing 8/8, raw mode bit-identical
   8/8, responses ~25 KB, round trip 280 ms; EdgeSAM result mode 8/8, cached
   8/8, photo + 1 box 438 ms, cached box 121 ms, 96 boxes in a 144 KB
   response; both workers started on demand from the compilation cache
   (2.2 s); MobileNet 20/20; catalog valid; TPU 35 °C, GPU 36 °C. MLServer's
   peak rose to +107 MB during the test's **raw-mode** EdgeSAM requests
   (raw tensors still go through MLServer's list encoding) and stayed there
   through the 24- and 96-box result requests: raw mode is a debug path,
   not for many boxes. Idle stop: `hetero1` and `hetero2` both STOPPED at
   06:01:53, ten minutes after the gate's last requests, every model still
   READY.


## Registry serving: profiles file, admission, eight GPU slots (prepared 2026-10-25, deploy scheduled)

The [model registry](../../../models/README.md) needs a slot per served model
without recompiling the supervisor for each one. The supervisor therefore
reads an optional, deployment-owned **profiles file**,
`STAGING_DIR/cerebrate-profiles.conf`
([this directory's copy](cerebrate-profiles.conf)), once at startup:

```text
slot    <name> <port> <binary>                                  [ready_timeout_ms]
profile <name> <slot> <declared model file> <worker config>     [min_free_mb]
```

- Every name is a flat file in the staging directory, the same
  least-privilege rule as the compiled-in paths.
- A file slot runs `cerebrate-hetero` profiles exactly like `hetero1` and
  `hetero2` do. It may not reuse a compiled-in name or port.
- A client still picks only a profile by name; the commands and files stay
  the deployment's.
- Without the file nothing changes.
- A malformed file is FATAL at startup, so the supervisor doesn't start.
  `scripts/validate-model-catalog` parses this copy and checks it against
  the registry; run it before every deployment of the file.
- The READY line gains `file_profiles=N`, and LIST answers with up to 8 KB.

**Admission.** `min_free_mb` makes START refuse while `MemAvailable` is below
it:

```text
ERROR: profile <p> needs <n> MB free, the device has <m> MB; stop another worker first
```

MLServer surfaces this as the request's error, and the model stays READY. Each
floor is the profile's measured free-memory drop plus 1 GB. That keeps a start
from taking the phone below about 1 GB free; below that, the low-memory killer
starts reaching for the Debian VM. Verified: OWLv2 was refused while
EfficientSAM3 held memory, then served once EfficientSAM3 was unloaded.

**Slots.** One model per process. The eight slots use ports 8774–8782 and skip
8777, the side-by-side test supervisor's control port. The `models/variants.yaml`
`serving` blocks name these slots and profiles. Two validated configurations
are deliberately left out (`serving_blocked` in the registry, decision
2026-10-25): EfficientSAM3's FP32 default, which is too large for the phone,
and SAM 2.1's reduced-precision variant, which is unresolved at 0.963 worst
mask IoU. Their worker configs stay in the repo for reproduction.

| Slot | Port | Profiles (floor MB) | MLServer endpoint (on demand) |
| --- | --- | --- | --- |
| `gpu-depth` | 8774 | `depth-anything-v2-small-fast` (1300), `-default` (1300) | `depth-anything-v2-small` → fast |
| `gpu-migan` | 8775 | `mi-gan-512-fast` (1200), `-default` (1300) | `mi-gan-512` → fast |
| `gpu-dinov2` | 8776 | `dinov2-s14-default` (1200) | `dinov2-s14` |
| `gpu-yoloe11s` | 8778 | `yoloe-11s-pf-default` (1500) | `yoloe-11s-pf` |
| `gpu-sam2` | 8779 | `sam2.1-hiera-tiny-default` (2000) | `sam2.1-hiera-tiny` → default (FP32, exact) |
| `gpu-rfdetr` | 8780 | `rf-detr-seg-nano-fast` (1200), `-default` (1300) | `rf-detr-seg-nano` → fast |
| `gpu-esam3` | 8781 | `efficientsam3-rvm-fast` (3400) | `efficientsam3-rvm` → fast |
| `gpu-owlv2` | 8782 | `owlv2-b16-default` (3000) | `owlv2-b16` |

**Builds.**

| Binary | sha256 | What it is |
| --- | --- | --- |
| [`cerebrate-supervisor`](cerebrate-supervisor), this directory | `05ad7e0d…6756` | The default build of the current source, reproducible with the Deploy section's command. |
| Test build | `e71f5fe4…0229143` | `-DCONTROL_PORT=8777 '-DSTAGING_DIR="/data/local/tmp/cerebrate-stage"'`; every test ran against it. |
| Deployed supervisor | `bad5bed3` | The build in production today. |
| `cerebrate-hetero` | `e06a906e…1c1c` | The graph-mode worker: [`CMakeLists.fragment.txt`](../cerebrate-hetero/CMakeLists.fragment.txt) against the committed source. Its legacy pipeline is bit-identical to the deployed `7554324e` (60/60). |

**Recovery: [`pixel-supervisor-watchdog`](pixel-supervisor-watchdog)** runs
on overmind-01 from a systemd timer (units in the
[overmind-01 README](../../overmind-01/README.md)). Each run:

1. If the control port isn't listening, it stops orphaned on-demand workers.
2. It restarts the supervisor with the detached command.
3. After that restart, and only then, it asks MLServer to load every model
   that isn't READY.

**It only recovers what adb can reach.** After an Android reboot, `adb tcpip`
mode is off. Until someone re-enables it by hand (USB or wireless
debugging), neither this watchdog nor `pixel-vm-watchdog` can do anything.
Recovery after a reboot is therefore not unattended, and not yet tested on a
real reboot.

It never touches a running supervisor, and starts the supervisor at most once
per 2 minutes. That bound means a broken binary or profiles file can't turn
into a restart loop: the watchdog logs the supervisor's last lines and waits.

Tested side by side: `SUPERVISOR_DIR=/data/local/tmp/cerebrate-stage
SUPERVISOR_PORT=8777`, test MLServer URL. After a `kill -9` of the supervisor,
the run cleared the orphan, brought the supervisor back and reloaded the
models, and the next request served. A worker killed on its own is restarted
by the adapter on the next request, which it retries once.

### Deployment runbook (window required; nothing below has run in production)

Expect about a minute of MLServer downtime. It is the same shape as the
image-transport release. The existing endpoints don't change: the same seven
models, the same configs for `hetero1` and `hetero2`. The eight new endpoints
are promoted afterwards, one at a time, without a restart (the operations
runbook covers it:
[`runbooks/cerebrate-pixel6-models.md`](../../../runbooks/cerebrate-pixel6-models.md#promote-a-staged-endpoint)).

**Pre-flight.** None of this affects production and it can be done before the
window.

**Pre-flight status (2026-10-25): all done.** Release candidate
`cerebrate-registry-rc1`, pushed with authorization.

- On the phone, verified by sha256:
  - `cerebrate-hetero.registry` (`e06a906e`);
  - `cerebrate-supervisor.registry` (`05ad7e0d`);
  - `cerebrate-profiles.conf`, with 11 profiles;
  - the 11 configs.
- The eight models' device files pass `check-artifacts --device` (28/28).
- The store passes `check-artifacts --store` (46/46).
- The Pillow wheel on the guest is `8bf295fe`.

**Rollback set preserved:**

- On the phone, `/data/local/tmp/rollback-transport-2026-10-25/`:
  - the running `cerebrate-supervisor` (`bad5bed3`) and `cerebrate-hetero`
    (`7554324e`);
  - the four YOLOE/EdgeSAM configs;
  - `SHA256SUMS`.
- In the guest, `~/rollback-transport-2026-10-25/`:
  - `mlserver17-venv.tar.gz`, the whole venv: Pillow 12.3.0, OpenCV
    5.0.0.93, MLServer 1.7.1;
  - the package list;
  - `cerebrate-mlserver.service`;
  - the checkout commit (`8015575`).
- Both are also copied to the Mac under
  `~/Backups/cerebrate/rollback-transport-2026-10-25/`.
- The converted models are backed up and a restore was tested
  ([models README](../../../models/README.md#artifact-store-mntmodels-on-overmind-01)).

**Gate principle (decision 2026-10-25):** the existing production models
must behave exactly as before the cutover: MobileNet, YOLOE and EdgeSAM,
bit for bit where the gate says so. Any failure aborts the window and rolls
back. No promotion happens in the cutover window unless that gate passed.

1. The branch is pushed, which needs authorization, so the guest can fast-forward.
2. Phone, model files: `scripts/stage-model depth-anything-v2-small mi-gan-512
   dinov2-s14 yoloe-11s-pf sam2.1-hiera-tiny rf-detr-seg-nano efficientsam3-rvm
   owlv2-b16`, run from a checkout on overmind-01. These were already staged on
   2026-10-25; confirm with `scripts/cerebrate-models check-artifacts --device`.
3. Phone, binaries and configs:
   - Push `cerebrate-hetero.registry` (`e06a906e`) and
     `cerebrate-supervisor.registry` (`05ad7e0d`), then `chmod +x` them.
   - Push the 11 new `*.conf` that the profiles file names, from
     `../cerebrate-hetero/configs/`. None replaces a deployed config.
     `efficientsam3-rvm-default.conf` and `sam2.1-hiera-tiny-fast.conf` stay
     in the repo only (serving_blocked).
   - Push `cerebrate-profiles.conf`. The running supervisor never reads it.
   - Verify every hash on the device.
4. Guest: the Pillow 13.0.0 wheel (sha256 `8bf295fe…6c0d`, in
   `~/cg-test/stage/`) is present. Its pin and the reason are in
   [`mlserver/requirements.txt`](../mlserver/requirements.txt). Only the new
   models' photo paths depend on it; YOLOE and EdgeSAM resize with OpenCV.
5. Record `LIST`. The guest checkout must be clean (`8015575` today).
   `scripts/validate-model-catalog` must pass.

**Window.**

1. If `pixel-supervisor-watchdog.timer` is installed, stop it. Otherwise it
   relaunches the old supervisor mid-swap.
2. In the guest, run `sudo systemctl stop cerebrate-mlserver`. STOP every
   worker still running, then check that `LIST` shows them all STOPPED.
3. On the phone:
   1. `cp cerebrate-supervisor cerebrate-supervisor.transport`
   2. `cp cerebrate-hetero cerebrate-hetero.transport`
   3. Kill the supervisor whose `/proc/<pid>/exe` is
      `/data/local/tmp/cerebrate-supervisor`. The test supervisor in
      `cerebrate-stage/` has the same name.
   4. Move the two `.registry` files into place.
   5. Relaunch with the Deploy section's `nohup setsid` command.

   Its log's READY line must end `file_profiles=11`, and `LIST` must show the
   eight `gpu-*` slots STOPPED.
4. In the guest, swap Pillow:
   1. Move the venv's `PIL/`, `pillow-12.3.0.dist-info/` and `pillow.libs/`
      out of `site-packages` to `~/pillow-12.3.0-backup/`.
   2. Unpack the 13.0.0 wheel into `site-packages`. The venv has no pip, and
      a wheel is a zip.
   3. `import PIL; PIL.__version__` with the venv's Python must print 13.0.0.
5. In the guest, run `git pull --ff-only`. The adapter gains the new hooks and
   the one retry, and `held-models/` gains the eight new endpoints, which
   MLServer doesn't load.
6. Run `sudo systemctl start cerebrate-mlserver`. The same seven models must
   be READY, and none of the new ones.
7. Gate. Roll back on any failure.
   - `mlserver_result_test.py` against production gRPC:
     - YOLOE: result mode equal to the validated postprocessing 8/8, and raw
       mode bit-identical 8/8.
     - EdgeSAM: result mode 8/8, and cached 8/8.

     This is the first time EdgeSAM's photo path runs through the new adapter.
     Its hook code is unchanged.
   - MobileNet returns 795.
   - `LIST` shows the four pinned workers RUNNING and every `hetero*` and
     `gpu-*` slot STOPPED.
   - Temperatures.
   - Idle stop: checked once, at this cutover, because the adapter and the
     supervisor both changed. `hetero1` and `hetero2` stopped ten minutes after
     the gate. It is not part of later gates (see the runbook's
     [checkpoint checks](../../../runbooks/cerebrate-pixel6-models.md#checkpoint-only-checks)).
8. Install the watchdog on overmind-01:
   1. `install -m 755 pixel-supervisor-watchdog /usr/local/bin/`
   2. Add the two units from the overmind-01 README.
   3. `sudo systemctl daemon-reload && sudo systemctl enable --now
      pixel-supervisor-watchdog.timer`.

   `journalctl -u pixel-supervisor-watchdog` must show quiet runs, with no
   start.

**Rollback** to the image-transport release:

1. Stop the watchdog timer and MLServer, then STOP the workers.
2. On the phone:
   1. Kill the supervisor.
   2. `mv cerebrate-supervisor.transport cerebrate-supervisor`
   3. `mv cerebrate-hetero.transport cerebrate-hetero`
   4. Relaunch the supervisor.
3. In the guest:
   1. Check out `8015575`.
   2. Move Pillow 13's three entries out of `site-packages` and the 12.3.0
      backup back in. If the venv is in doubt, restore it whole instead:
      `rm -rf ~/mlserver17-venv && tar -C ~ -xzf
      ~/rollback-transport-2026-10-25/mlserver17-venv.tar.gz`. It must go back
      to the same path, because the scripts embed it.
   3. Start MLServer.

If the `.transport` copies from step 3 of the window are missing, the same
binaries and configs are in `/data/local/tmp/rollback-transport-2026-10-25/`.
Check them against its `SHA256SUMS`.

The new configs, the profiles file and the model files are inert without the
new supervisor; `bad5bed3` doesn't read the profiles file. The earlier rollbacks
above remain available behind this one.

**Go/no-go at the window:** proceed only with at least 3 GB free on the phone
and both TPU and GPU below 45 °C, and only if nothing else (TPU compiles,
curate jobs) is scheduled on the phone.

### Deploy record: registry-serving cutover (2026-10-25, 19:29–19:31 UTC)

Authorized by the user ("roll this out").

1. **Pre-flight** as recorded above (`cerebrate-registry-rc1`). The baseline
   gate ran on the old production just before the window and passed:
   - YOLOE result 8/8, raw 8/8;
   - EdgeSAM result 8/8, cached 8/8;
   - MobileNet 795.
2. **19:29:14.** MLServer stopped. `infer`, `generate`, `gguf`, `graph3`,
   `hetero1` and `hetero2` were STOPPED through the supervisor, and `LIST`
   showed all STOPPED.
3. **Phone.** The `.transport` copies were made (`bad5bed3`, `7554324e`), the
   supervisor (pid 11557, exe verified) was killed, and the `.registry`
   builds were moved into place (`05ad7e0d`, `e06a906e`) and relaunched.
   READY: `…,gpu-esam3,gpu-owlv2 file_profiles=11`, with 16 slots STOPPED.
4. **Guest, Pillow.** Pillow 12.3.0 moved to `~/pillow-12.3.0-backup/`, and
   the 13.0.0 wheel was unpacked (144 entries). PIL 13.0.0 and cv2 5.0.0
   import.
5. **Guest, checkout.** `git pull --ff-only` → `f815068`.
6. **19:30:18.** MLServer active, with the same seven models READY.
   **MLServer downtime ~64 s.**
7. **Gate: PASS.**
   - YOLOE: result mode 8/8 equal to the validated postprocessing; raw 8/8
     bit-identical; round trip 295 ms, worker 92 ms (baseline 273 / 91).
   - EdgeSAM: result 8/8, cached 8/8. Photo + 1 box 427 ms; cached 115 ms;
     96 boxes in a 144 KB response.
   - MobileNet 795.
   - MLServer's peak after the gate is 246 MB, the same as the previous
     process (247 MB).
   - `LIST`: the pinned workers RUNNING and every `gpu-*` slot STOPPED.
   - 2.5 GB free; TPU and GPU at 31 °C; the catalog validates.
   - Idle stop (checked at this checkpoint only): `hetero1` and `hetero2`
     STOPPED at 19:41:48.
8. **Watchdog.** The files were staged on overmind-01 and a dry run (no
   sudo) exited quietly against the new supervisor. The install needs the
   user's sudo.

Rollback is not needed. The `.transport` files, the rollback set and the
Pillow backup stay in place until the promotions are done.
