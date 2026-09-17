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
