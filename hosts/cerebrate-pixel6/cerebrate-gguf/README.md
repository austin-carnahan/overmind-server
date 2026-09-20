# cerebrate-gguf

**Naming note:** `cerebrate-infer`/`cerebrate-generate` name what the
worker *does* (classify, generate); `cerebrate-gguf` names the artifact
format/runtime lane instead, which breaks that pattern. Kept as-is for
now since renaming mid-implementation isn't worth the churn, but if this
worker's scope grows beyond "one Granite-Docling GGUF model," revisit the
name — `cerebrate-multimodal` or `cerebrate-vlm` fit the existing
what-it-does convention better than `cerebrate-gguf` does.

Doclet Service V3 Stage 2 (see the
[implementation design doc](../../../design-notes/Doclet%20Service%20—%20Implementation%20Design%20V3.md#stage-2--cerebrate-gguf--supervisor-extension--acceptance-test)).
A persistent-transport wrapper around `llama-mtmd-cli`, the sibling of
[`cerebrate-infer`](../cerebrate-infer/README.md) and
[`cerebrate-generate`](../cerebrate-generate/README.md) in Cerebrate's
worker family — but a different shape from both: it binds and listens
immediately like they do (so `cerebrate-supervisor`'s readiness probe and
lifecycle work identically), but does the actual work by **forking a
fresh `llama-mtmd-cli` process per request** rather than holding a model
loaded in-process the whole time.

That shape is deliberate, not a shortcut: `llama-server`'s own multimodal
serving path is confirmed broken for Granite-Docling
([experiments/docling](../../../experiments/docling/README.md)'s decisive
`/completion` test, reproducing upstream `llama.cpp#16601`).
`llama-mtmd-cli --image` is the only path with proven-correct output, and
it's a one-shot CLI tool, not a server — so this worker exists to give it
a stable TCP lifecycle without touching (or trusting) `llama-server`'s
broken serving code at all.

## Wire protocol

Request: `[4B BE image_len][image bytes][4B BE prompt_len][prompt bytes]`.
`image_len == 0` means a text-only request (no `--image` passed to
`llama-mtmd-cli`) — kept general per the design's "future compatible GGUF
models reuse this worker" goal, even though Granite-Docling always sends
an image today.

Response: the same typed-frame protocol `cerebrate-generate` uses
(`FRAME_DATA` / `FRAME_DONE` / `FRAME_ERROR`), with exactly one
`FRAME_DATA` covering the whole output — `llama-mtmd-cli` isn't invoked in
a streaming mode here, unlike `cerebrate-generate`'s native streaming.

## `llama-mtmd-cli` and its shared libraries are not staged flat

Model/mmproj GGUF paths are client-supplied via `cerebrate-supervisor`'s
`START` command and therefore subject to its flat-`/data/local/tmp`-only
`model_path_is_approved()` check. `llama-mtmd-cli` itself and its `.so`
dependencies are **not** client-supplied — this worker hardcodes their
path (`/data/local/tmp/llamacpp/`, the same layout the
[experiments/docling](../../../experiments/docling/README.md) build
already deployed) and doesn't need them subject to that check.
`LD_LIBRARY_PATH` for the `llama-mtmd-cli` child combines both directories
(`/data/local/tmp/llamacpp:/data/local/tmp`) since `cerebrate-supervisor`
sets the latter for this worker's own launch, not the former.

## `cerebrate-supervisor` protocol extension: `mmproj`

`cerebrate-supervisor` is otherwise frozen since Phase B; this is the
deliberate, bounded exception the design doc calls for. `cerebrate-gguf`
needs two GGUF paths (model + multimodal projector) where every existing
worker needed at most one model plus a fixed two-value enum (`backend`),
so the wire protocol gained one new optional key rather than overloading
either existing one:

```text
START
worker: gguf
model: /data/local/tmp/granite-docling-258M-bf16.gguf
mmproj: /data/local/tmp/mmproj-model-f16.gguf

```

Same flat-file validation, same idempotent START/STOP, same
config-conflict detection (a running `gguf` worker refuses a `START`
with a different `model` *or* `mmproj` until `STOP`ped), same crash
detection via `waitpid(WNOHANG)`, same pre-flight orphan-port check — all
reused as-is, not reimplemented for this worker.

## Build and deploy

```bash
NDK=~/Library/Android/sdk/ndk/27.1.12297006
CLANGXX=$NDK/toolchains/llvm/prebuilt/darwin-x86_64/bin/aarch64-linux-android24-clang++
"$CLANGXX" -o cerebrate-gguf cerebrate-gguf.cc -Wall -O2

adb push cerebrate-gguf /data/local/tmp/cerebrate-gguf
adb shell chmod +x /data/local/tmp/cerebrate-gguf

# GGUF files must be flat in /data/local/tmp (cerebrate-supervisor's
# model_path_is_approved), not under llamacpp/ where the CLI binary and
# its shared libraries live:
adb shell cp /data/local/tmp/llamacpp/granite-docling-258M-bf16.gguf /data/local/tmp/
adb shell cp /data/local/tmp/llamacpp/mmproj-model-f16.gguf /data/local/tmp/
```

## Acceptance test: reproduced the proven CLI output, through the supervisor

Per the design doc's hard acceptance gate: `cerebrate-gguf` must
reproduce `llama-mtmd-cli`'s already-proven DocTags output for the known
test image from [experiments/docling](../../../experiments/docling/README.md)
(a real line chart, `test-figure.png`) — and specifically **through
`cerebrate-supervisor`**, not by invoking the wrapper directly.

```text
START
worker: gguf
model: /data/local/tmp/granite-docling-258M-bf16.gguf
mmproj: /data/local/tmp/mmproj-model-f16.gguf
->
OK: started pid=27768 port=8768
```

Request sent to port 8768 (prompt: `"Convert this page to docling."`):

```text
<doctag><picture><loc_0><loc_0><loc_500><loc_500><line_chart></picture>
</doctag>
```

Byte-identical structure to the original CLI result, and the timing
matches too: **102.4s** here (**103.5s** on a second run through the
supervisor) versus the original experiment's **1m44.560s** — all within
the same ~99%-vision-encoding-bound profile already characterized there.
Passed twice: once invoking the compiled binary directly, once again
through `cerebrate-supervisor`'s `START`, confirming the wrapper adds no
observable behavior difference for the supervised path the production
service will actually use.

## Failure/recovery characterization (Stage 2, same discipline as Phase B Stage 3)

Deliberately broken, not just described, matching
[`cerebrate-supervisor`](../cerebrate-supervisor/README.md)'s own Phase B
Stage 3 precedent:

- **Missing/invalid `mmproj`** — `START` without an `mmproj` field, with a
  path outside the flat staging directory, or with a nonexistent file all
  produce the expected `ERROR:` response and leave the worker `STOPPED`,
  not partially started.
- **Config-conflict while running** — `START`ing the same worker with a
  different (but existing) `model`/`mmproj` while already running is
  correctly refused (`ERROR: ... already running with a different
  configuration ... STOP first`), not silently ignored or double-started.
- **Idempotent START** — issuing the identical `START` twice while
  running returns `OK: already running ... (idempotent)`, matching every
  other worker.
- **Crash detection** — `kill -9` on the running `cerebrate-gguf`
  process is correctly reflected as `EXITED exit_code=-9` on the next
  `STATUS`/`LIST` (via `cerebrate-supervisor`'s existing `waitpid(WNOHANG)`
  reaping), and a subsequent `START` succeeds cleanly.
- **Crash mid-request (real gap, found and recorded, not fixed here)** —
  killing `cerebrate-gguf` while its `llama-mtmd-cli` child is actively
  running (confirmed via `ps` showing the child mid-generation) does
  **not** kill the child: it reparents to `init` (PID 1) and keeps
  running to completion untracked by anything, then exits cleanly on its
  own (~100s later, confirmed by polling `ps` until it disappeared — no
  permanent zombie, no runaway process). `cerebrate-gguf` itself briefly
  becomes a zombie, correctly reaped by the supervisor's next `reap_all()`
  call (triggered by any subsequent command). The one real, persistent
  cost: the temp request image
  (`/data/local/tmp/cerebrate-gguf-req-<pid>-<n>.png`) is never cleaned
  up, since the code path that `unlink()`s it never runs when the parent
  is killed before the child returns. Confirmed via a live test (kill mid-request, observed the
  leaked file, removed it manually). Not fixed as part of this stage —
  same category as `cerebrate-supervisor`'s own documented "no
  orphan-worker adoption" and "no automatic respawn-on-crash" gaps: a
  real, bounded, understood limitation of the "no scheduler, deliberately
  minimal" design, worth a periodic stale-file sweep if crashes turn out
  to be frequent in practice, not worth solving speculatively now.

## Stage 4 fixes, found via a real 29-minute production run (2026-09-18)

Two real bugs, both found only because a genuine multi-item Docling Serve
job (not a single isolated test) exercised paths nothing before it had:

**Fd-leak: every spawned `llama-mtmd-cli` held a duplicate of the
listening socket.** `run_llama_mtmd_cli()`'s `fork()` never closed the
inherited `srv` (listening) and `client` (current connection) fds before
`execl()` — the exact pitfall `cerebrate-supervisor.cc`'s own header
comment already documents for its *own* worker-launch fork, reintroduced
here in a second fork/exec path. Invisible under normal operation (the
real `cerebrate-gguf` process is still also listening), but once it dies
(crash, `kill -9`, or the already-documented "crash mid-request" case
above), the orphaned `llama-mtmd-cli` child keeps port 8768 bound —
confirmed directly via `netstat`, which attributed the listening socket
to the orphaned CLI process by PID. This is what made
`cerebrate-supervisor`'s pre-flight orphan check correctly *refuse* a
fresh `START` after a kill ("port 8768 already has an unmanaged
listener"), even though the real intent was a clean restart. Fixed by
adding `g_listen_fd`/`g_current_client_fd` globals (matching
`cerebrate-supervisor.cc`'s own naming) and closing both in the forked
child before `execl()`. Verified directly: `kill -9` on `cerebrate-gguf`
mid-request now leaves **no** listener on 8768 (confirmed via `netstat`
showing only a `TIME_WAIT` entry), and a fresh `START` succeeds
immediately, no manual intervention needed.

**`--mmproj` was never passed for a text-only request.** Found via the
first-ever real exercise of this branch (this code has claimed to
support text-only requests since Stage 2, but every real caller until
this test always sent an image): `llama-mtmd-cli` requires `--mmproj`
unconditionally, even with no `--image`, and fails immediately with
`ERR: Missing --mmproj argument` without it. Fixed by always passing
`--mmproj` in both branches of the `execl()` call — a real mmproj path is
always available regardless of whether a given request carries an image,
since `cerebrate-supervisor` requires one for any `needs_mmproj` worker
at `START` time.

## Known operational constraint carried into Stage 3

A real Granite-Docling request takes **~100 seconds**, almost entirely
vision encoding on this device (see
[experiments/docling](../../../experiments/docling/README.md)'s timing
breakdown). `inference.home.arpa` (Stage 3) and Docling Serve's own
`picture_description_api.timeout` (default 20s, per
[experiments/doclet-service Stage 1](../../../experiments/doclet-service/stage1-picture-description-api/README.md))
must both be configured well above that, or every real enrichment call
will time out before `cerebrate-gguf` ever returns.
