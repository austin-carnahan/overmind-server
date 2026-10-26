# Design Studio checkpoint store

**Status:** PARTIAL. Spikes D and E of the
[Mac GIMP worker milestone](../../design-notes/agentic-design-studio-mac-worker-milestone-v0.1.md)
were verified on 2026-10-23. Buckminster runs its own checkpoints (it
committed `0002`). Restoring a checkpoint onto a worker that has lost its
files is **not built yet**; see the environment report's Spike E caveats.

**Agent access.** Buckminster runs this tool from its shell on Overmind.
The shell was an exec allowlist naming only this program until 2026-10-23,
and is now full, with no sudo. Committing only through this tool is now a
rule in Buckminster's `AGENTS.md`, not something the system enforces; the
`openclaw` user owns the store. The tool still validates every input that
decides where it reads or writes, as if an agent chose it: the store path is
fixed, project and staging ids are format-checked, and worker paths must be
under `/Users/dev/DesignStudio/workspaces/`. Treat any new argument the same
way.

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
- [`install-gimp-plugins`](install-gimp-plugins) runs **on the Mac** (no
  sudo). It installs [`gimp-plugins/`](gimp-plugins/) into the GIMP profile;
  restart GIMP after a first install or a new procedure or argument. Today
  that is `overmind-import-artifact`, which provides three procedures:
  - `overmind-publish`: uploads the visible composite of a region, and the
    selection as a mask, for Cerebrate, keeping the snapshot's provenance in
    the document. It needs the host's upload token in
    `plug-ins/overmind-import-artifact/overmind-import-artifact.json` (0600).
  - `overmind-import-artifact`: adds an image from the artifact service by
    URL, optionally into an object's layer group. It checks the photo's
    context, or with `snapshot=`, that the document is unchanged since the
    snapshot.
  - `overmind-make-object-group`: groups an object's layer and anchors it.
  - `overmind-seamless-blend`: a Poisson blend (GEGL seamless-clone) of a
    patch layer or group into its surroundings, limited to the patch's
    bounding box plus a margin. It's the GIMP-only **fallback**: about 100 s
    for a bed-sized region, where Cerebrate's `seamless_blend` takes about 2 s.
  - `overmind-op-status`: whether an operation started with an `op-id`
    finished, and its result.

  The installer also runs
  [`patch-gimp-agent-bridge`](patch-gimp-agent-bridge) (below).
- [`buckminster/cerebrate-gimp.md`](buckminster/cerebrate-gimp.md) is
  Buckminster's Cerebrate → GIMP recipe. Install it into its workspace with
  `sudo bash install-buckminster-cerebrate-runbook` (on Overmind).
- [`design-checkpoint`](design-checkpoint) runs **on Overmind as `openclaw`**
  and uses only the Python standard library. It pulls files with
  `openclaw nodes invoke ... file.fetch`, so the worker never needs SSH access
  to Overmind.

## Agent capabilities: named operations, never code

Agents call named GIMP operations with parameters. They never send code to
run. When an agent needs a capability GIMP lacks, it becomes a reviewed
plug-in procedure in [`gimp-plugins/`](gimp-plugins/), like the artifact
import and publish.

- **Python plug-ins are still allowed.** GIMP runs fixed, installed code
  (the bridge, our plug-ins) with its bundled Python.
- **Code-running procedures are blocked.** The GIMP Agent MCP's own Python
  tool is off (`GIMP_AGENT_ALLOW_PYTHON=0`). But its `gimp_pdb_call` could
  still reach the PDB procedures that run caller-supplied code:
  - `python-fu-eval` and `python-fu-console`;
  - the Script-Fu eval, console and text console;
  - `extension-script-fu`;
  - `plug-in-script-fu-server`, which opens a network port that runs Scheme.

  [`patch-gimp-agent-bridge`](patch-gimp-agent-bridge) makes the bridge
  refuse them. It's idempotent, and it fails loudly if the bridge's code
  changes shape. Re-run `install-gimp-plugins` after any bridge upgrade, then
  restart GIMP.
- **One bridge at a time.** The same patch makes a second bridge, for
  example from the menu item clicked again, exit if the one in the bridge
  file is alive. Without it, the second bridge took the next port and
  rewrote the file, and when it went away, clients were left pointing at a
  dead port with the live bridge unreachable.
- **Operator access stays.** The bridge's own `exec` is not an agent tool. It
  needs the bridge's local token.

## Lost responses and plug-in crashes

**Lost responses.** A call's response can be lost: a dropped connection, or a
plug-in that died.
- `overmind-seamless-blend` and `overmind-import-artifact` take an `op-id`
  and journal their progress in the document (parasite `overmind-ops`).
- `overmind-op-status(image, op-id)` reports `done` with the result,
  `started` (not finished), `failed` with the error, or `unknown`.
- Re-running with the same `op-id` after `done` returns the recorded result
  instead of repeating the work, so a retry can't duplicate layers.

**Plug-in crashes hang GIMP.** If a plug-in dies during a call, GIMP hangs
waiting for it, and only a force-quit recovers. On 2026-10-26 this froze
the interactive GIMP twice:
- the GEGL graph in the blend segfaulted, because GEGL wasn't initialised in
  the plug-in process (fixed: `Gegl.init`);
- reproduced and fixed in a throwaway headless GIMP:
  `GIMP3_DIRECTORY=<tmp> gimp-console -i -n --quit --batch-interpreter=python-fu-eval -b ...`
  (the pattern `worker-reopen-check` uses).

**Test new pixel-processing plug-in code headless first,** never in the
session someone is working in.

**The bridge's `close_image` (`gimp_close_image`) doesn't close an image that
has a window.** It calls `image.delete()`, which GIMP declines while a
display exists, and reports "closed" anyway. libgimp can't list an image's
displays, so close such windows by hand. Not patched.

## Object groups and alignment (open decision)

Agent edits keep each object in a layer group, holding its original pixels
and its repairs (see Buckminster's recipe,
[`buckminster/cerebrate-gimp.md`](buckminster/cerebrate-gimp.md)). Every
layer is still movable on its own. With the Move tool's default "Pick a layer
or guide", dragging on the canvas grabs whatever is under the cursor (a
patch, a cutout), and that member drifts out of alignment with its group.

**Decision (2026-10-26): rely on technique for now; no position locks.**
- **By hand:** select the group in the Layers panel and drag with the Move
  tool set to "Move the active layer" (or hold Shift).
- **Agents:** move groups, never members. Cmd+Z undoes a stray drag. The
  groups' anchors also let a patch be realigned.

**If we pin later.** GIMP's Lock position spreads both ways, as tested
through the PDB:
- a locked member also blocks moving its group;
- a locked group blocks moving itself and all its members.

So members can't be locked while their group stays draggable. The options
are:
1. **Pin every object group.** Unlock, move, re-lock to move it. The plug-in
   would lock the groups it creates and briefly unlock one while placing a
   patch.
2. **Pin only surfaces that never move** ("Room", walls) and leave movable
   objects unlocked.

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
