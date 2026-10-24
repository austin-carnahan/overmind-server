# Design Studio checkpoint store

**Status:** PARTIAL. Spike D of the
[Mac GIMP worker milestone](../../design-notes/agentic-design-studio-mac-worker-milestone-v0.1.md)
was verified on 2026-10-23: one checkpoint committed and every failure test
rejected. Commits are run by the operator; Buckminster cannot call them yet.

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
- [`design-checkpoint`](design-checkpoint) runs **on Overmind as `openclaw`**
  and uses only the Python standard library. It pulls files with
  `openclaw nodes invoke ... file.fetch`, so the worker never needs SSH access
  to Overmind.

## Publishing a checkpoint

1. On the worker, put `document.xcf`, `preview.png`, and the output of
   `worker-reopen-check document.xcf` (saved as `worker-validation.json`) in
   an outbox folder under `~/DesignStudio/workspaces/<project>/outbox/<n>/`.
   That is the only tree `file.fetch` may read.
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

## What "verified" means

| Check | Catches |
| --- | --- |
| Each file's sha256 on the worker (reported by `file.fetch`) matches the sha256 on Overmind | Transfer corruption |
| Required files present; manifest schema and project match | Incomplete packages |
| Files match the manifest at verify time **and again at commit time** | Changes made after verification |
| Structural XCF parse without GIMP: header, canvas, layer names, kinds, offsets, opacity, and every tile pointer inside the file with the expected tile count | Malformed or truncated XCFs, even when their hashes are honest |
| `worker-validation.json` layer order matches the parse, and its `xcf_sha256` matches the manifest | A reopen check run on a different file |
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
