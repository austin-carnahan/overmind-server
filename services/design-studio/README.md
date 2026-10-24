# Design Studio checkpoint store

**Status:** PARTIAL. Spikes D and E of the
[Mac GIMP worker milestone](../../design-notes/agentic-design-studio-mac-worker-milestone-v0.1.md)
were verified on 2026-10-23. Buckminster runs its own checkpoints (it
committed `0002`). Restoring a checkpoint onto a worker that has lost its
files is **not built yet**; see the environment report's Spike E caveats.

**Agent access.** Buckminster's exec tool is limited by an allowlist to this
one program (`agents.entries.buckminster.tools.exec.mode: "allowlist"` plus a
Gateway approvals entry for
`/opt/overmind/services/design-studio/design-checkpoint`). Because an agent
chooses the arguments, the tool validates every input that decides where it
reads or writes: the store path is fixed, project and staging ids are
format-checked, and worker paths must be under `/Users/dev/DesignStudio/workspaces/`.
Treat any new argument the same way.

Overmind is the authority for design projects. A worker (currently the
`macbook-m1` OpenClaw node running GIMP) edits a working copy. Only a
checkpoint that Overmind has fetched, verified, and committed counts as
saved. See the [environment report](../../design-notes/agentic-design-studio-environment.md)
for the node, policy, and agent setup this depends on.

## Layout

`DESIGN_STORE=/mnt/substrate/design-studio` (on the SSD; `austin:openclaw`,
mode `2775`, so new files belong to group `openclaw`).

```text
projects/<project-id>/
  project.json            metadata, sources, checkpoint list, HEAD (atomic replace)
  sources/<sha256>.<ext>  immutable source files (0444)
  checkpoints/<NNNN-xxxxxx>/   immutable (dir 0555, files 0444)
    document.xcf  preview.png  worker-validation.json  checkpoint.json  verify.json
  staging/<UTC-time>-<rand>/   incomplete or failed; FAILED marker says why
  history/events.jsonl    append-only event log
  .lock                   one writer per project (flock)
```

There is no backup destination yet, so committed checkpoints exist only on the
SSD.

## Tools

- [`worker-reopen-check`](worker-reopen-check) runs **on the Mac**. It opens
  an XCF in a fresh headless `gimp-console` with a throwaway profile (no
  bridge) and prints JSON with the canvas size, the layer list, the GIMP
  version, and the XCF's `sha256`. That JSON becomes the package's
  `worker-validation.json`.
- [`make-gimp-launcher`](make-gimp-launcher) runs **on the Mac**. It builds
  `GIMP Agent Bridge.app`, which opens GIMP through LaunchServices with the
  bridge on. Use it instead of `gimp_launch`, which ties GIMP's lifetime to
  the node host.
- [`design-checkpoint`](design-checkpoint) runs **on Overmind as `openclaw`**
  and uses only the Python standard library. It pulls files with
  `openclaw nodes invoke ... file.fetch`, so the worker never needs SSH access
  to Overmind.

## Publishing a checkpoint

1. On the worker, put `document.xcf` and `preview.png` in an outbox folder
   under `~/DesignStudio/workspaces/<project>/outbox/<n>/`. That is the only
   tree `file.fetch` may read. Optionally add `worker-validation.json` (the
   output of `worker-reopen-check document.xcf`). It needs a shell on the
   worker, so only the operator can produce it. Agent-run checkpoints omit
   it and rely on Overmind's checks.
2. On Overmind:

   ```bash
   sudo -u openclaw bash -lc 'cd; D=/opt/overmind/services/design-studio/design-checkpoint
   $D stage  <project> --node macbook-m1 --src-dir <outbox> --description "..." --layers "A,B,C"
   $D verify <project> <staging-id>
   $D commit <project> <staging-id>
   $D status <project>'
   ```

   A new project needs `$D init <project> --node macbook-m1 --source <path>`
   first. It fetches the source file and pins it under its hash.

## Restoring a checkpoint to the worker

Normally you resume from the worker's own outbox copy, after `file_fetch`
confirms its sha256 matches the committed manifest. When that copy is gone,
restoring is an **operator step** for now. Agents can't push files to the Mac,
because `openclaw nodes invoke` passes params as a single argv string and
Linux caps one argument at 128 KB.

```bash
design-checkpoint restore-command <project> [<checkpoint>]   # default: HEAD
```

This prints a `run_on_mac` line
(`mkdir -p … && rsync -a --chmod=u+w overmind-01:<checkpoint dir>/ ~/DesignStudio/workspaces/<project>/restore/<id>/`)
and the `expect_sha256` to check afterwards. It reuses the Mac's existing SSH
access to Overmind and adds no service. Buckminster can run it and hand the
line to the user. Verified 2026-10-23 by restoring `0002-3f2f0f`; the hash
matched.

If agent-driven restore becomes worth it, the cheapest step up is a
read-only share in the existing Samba container, which the Mac keeps
mounted.

## What "verified" means

| Check | Catches |
| --- | --- |
| Each file's sha256 on the worker (reported by `file.fetch`) matches the sha256 on Overmind | Transfer corruption |
| Required files present; manifest schema and project match | Incomplete packages |
| Files match the manifest at verify time **and again at commit time** | Changes made after verification |
| Structural XCF parse without GIMP: header, canvas, layer names, kinds, offsets, opacity, and every tile pointer inside the file with the expected tile count | Malformed or truncated XCFs, even when their hashes are honest |
| If present: `worker-validation.json` layer order matches the parse, and its `xcf_sha256` matches the manifest | A reopen check run on a different file |
| `preview.png` fully decodes (chunk CRCs, zlib, exact pixel byte count) at canvas size | Broken previews |
| `parent_checkpoint_id` equals HEAD under the project lock | Two writers both building on the same HEAD |

Commit then renames the staging folder into `checkpoints/` (atomic, because
it stays on one filesystem), makes it read-only, and atomically replaces
`project.json` with the new HEAD. If a crash happens between the rename and
the HEAD write, `status` lists the checkpoint under
`unrecorded_checkpoint_dirs`; nothing assumes the HEAD write happened.

The XCF is not opened by GIMP on Overmind. That was a deliberate choice (no
GIMP on the Pi for now). The worker's fresh-process reopen, bound to the
exact file by hash, covers "does GIMP open it". If server-side GIMP is ever
wanted, run it in a container on the SSD, not as a host package.

Read-only permissions guard against accidents only. The owner can `chmod`
them back.
