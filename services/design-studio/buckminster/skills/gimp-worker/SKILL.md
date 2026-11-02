---
name: gimp-worker
description: Operate GIMP on the macbook-m1 worker through GIMP Agent MCP (gimp_gimp_* tools): verified setup, seeing your own work (export, file_fetch, view_image), checkpoints and restore, the launcher, network drops, and known bugs. Use before and during any GIMP work on the Mac.
---

# GIMP on the Mac worker

Verified behavior of GIMP Agent MCP on the `macbook-m1` worker. Record what
was actually observed. Mark anything inferred but untested as such.

## Setup facts (verified 2026-10-23)

- Worker node: `macbook-m1`. GIMP **3.2.6** (native Apple Silicon), GIMP
  Agent MCP **0.5.0**.
- Tools are published as `gimp_gimp_<tool>`: 38 tools. `gimp_run_python` is
  intentionally **disabled** (decided 2026-10-23). It can be enabled later if
  a task needs it.
- **Starting GIMP:** the user opens **"GIMP Agent Bridge"** (in
  `~/Applications` on the Mac). It starts GIMP with the bridge already
  listening, after about 20 s, and GIMP is independent of the node, so node
  restarts can't kill it. If GIMP was opened the normal way, the bridge
  needs **Filters → Development → Start Agent Bridge**. `gimp_gimp_status`
  shows `connected: true` and `mode: gui` when the bridge is up. If GIMP
  isn't running, ask the user to open "GIMP Agent Bridge" rather than
  calling `gimp_gimp_launch`.
- The Mac's node runs as a login service (launchd). It survives crashes and
  reconnects on its own after network drops, so a short outage means "wait
  and re-check", not "the worker is gone".
- **After a network drop mid-call,** the operation may well have completed
  on the Mac (verified 2026-10-23: a blur finished during a 25 s outage).
  Inspect before deciding; never re-run it blindly.
- If the tools are missing entirely, the Mac node is offline. If they exist
  but calls fail to connect, GIMP or its bridge is not running. Tell the
  user which one.
- **Prefer a GIMP the user started over `gimp_gimp_launch`** (verified
  2026-10-23). On macOS, `gimp_launch` starts GIMP as a child of the MCP
  server, so if the Mac's node host restarts or crashes, **GIMP and all
  unsaved work go with it**. That happened in the Spike E interruption test.
  Use `gimp_gimp_launch` only when the user asks, or when there's nothing
  unsaved to lose. Save often while running under a GIMP you launched. If you
  find GIMP gone after a disconnect, assume unsaved work in it is lost, and
  say so.
- Project working directory on the Mac: `~/DesignStudio/workspaces/<project-id>/`.

## Working with documents

- **Image and layer IDs are session-local integers.** Reopening a file gives
  new IDs (verified: layers 2/3/4 became 21/20/18 after a reopen). Look IDs
  up again after every open and after any human change.
- **With several images open, always pass an explicit `image_id`.** GIMP
  cannot reliably report which document has keyboard focus.
- `gimp_gimp_open` returns the image structure. `gimp_gimp_list_images`
  shows `file`, `dirty` and `layer_count`.

## Seeing your work (verified 2026-10-23)

`gimp_gimp_render` returns an image, but **you cannot see it**. Your tools run
inside Code Mode, whose bridge carries JSON only, so image results arrive as
`"omitted": true`. Making the render smaller doesn't help.

To actually look at the document:

1. `gimp_gimp_export` the image to a **PNG inside the project working
   directory**, for example
   `/Users/dev/DesignStudio/workspaces/<project-id>/preview-check.png`.
   Export only PNG for a look. Don't export `.xcf` unless you mean to save.
2. `file_fetch` that exact path from the `macbook-m1` node. It returns a
   local path on Overmind.
3. `view_image` on that local path. `view_image` is a direct tool, so the
   image reaches you.

`file_fetch` can only read under `/Users/dev/DesignStudio/workspaces/` on the
Mac, with a 16 MB cap. Anything elsewhere is refused by policy, by design.

Never describe how something looks unless you saw it this way. If a step
fails, say which one.

## Saving

- **Native editable save:** `gimp_gimp_export` with a path ending in
  `.xcf`. Verified: it writes a real XCF that reopens with named layers,
  opacity, positions, and **text layers still editable**.
- **Preview:** `gimp_gimp_export` with a `.png` path. It flattens a copy;
  the document keeps its layers.
- Exporting to `.xcf` renames the open document to that file.
- A 1920×1080 photo with two small overlay layers produced a 4.9 MB XCF.
  Expect more with full-canvas layers.

## Checkpoints (you run these yourself)

A checkpoint is a deliberate, verified snapshot stored on Overmind. Scratch
work does not need one. Take a checkpoint when a state is worth keeping: the
user asks, a version they like, or before a risky change.

Checkpoints go **only** through
`/opt/overmind/services/design-studio/design-checkpoint`, run with your shell
on Overmind. You could write into the store by hand; never do. Call the tool
plainly, one step per call, and read each step's output before running the
next.

1. **Package on the Mac.** For the open image, `gimp_gimp_export` to
   `/Users/dev/DesignStudio/workspaces/<project>/outbox/<n>/document.xcf`,
   then to `.../outbox/<n>/preview.png`. Use a new `<n>` each time; never
   reuse an outbox folder.
2. **Re-point the open document.** Exporting to `.xcf` makes GIMP treat the
   outbox file as the document. Export once more to the working copy (for
   example `.../<project>/document.xcf`) so later edits and ⌘S don't touch
   the outbox.
3. **Stage, verify, commit**, using the staging id that `stage` prints:

   ```text
   /opt/overmind/services/design-studio/design-checkpoint stage <project> --node macbook-m1 --src-dir /Users/dev/DesignStudio/workspaces/<project>/outbox/<n> --description "<what this state is>" --layers "<every layer name, comma-separated>"
   /opt/overmind/services/design-studio/design-checkpoint verify <project> <staging-id>
   /opt/overmind/services/design-studio/design-checkpoint commit <project> <staging-id>
   ```

4. Only after `commit` prints the new `head` may you say the checkpoint is
   committed, and you should quote its id. If any step prints `FAIL:`,
   report it exactly. Don't retry blindly and don't edit around it.

`design-checkpoint status <project>` shows HEAD, the checkpoint history, and
any failed or pending staging. It reads only Overmind, so it works while the
Mac is offline.

Project ids are lowercase letters, digits, and hyphens. Outbox paths must be
under `/Users/dev/DesignStudio/workspaces/`.

**Resuming from a checkpoint.** The committed files live on Overmind under
`/mnt/substrate/design-studio/projects/<project>/checkpoints/<id>/`, and its
`checkpoint.json` lists each file's sha256. To resume, open a Mac copy
**only if** `file_fetch` reports the same sha256. Look first at that
checkpoint's outbox `document.xcf`, then at
`~/DesignStudio/workspaces/<project>/restore/<id>/document.xcf`.

If no matching copy exists, you can't copy files to the Mac yourself. Run
`/opt/overmind/services/design-studio/design-checkpoint restore-command <project> [<id>]`,
which defaults to HEAD. Give the user its `run_on_mac` line to run in a Mac
terminal. Afterwards, check the restored file against `expect_sha256` with
`file_fetch` before opening it. Never substitute a non-matching file.

## Closing documents (known quirk)

- **`gimp_gimp_close_image` does not close a document that has a window
  open.** It reports `{"closed": N}`, but the image stays open and listed
  (verified 2026-10-23).
- Deleting the image's **display** (window or tab) closes it when the last
  display goes; this was verified through Python, which is now disabled.
- **PDB route tested 2026-10-23, blocked by bridge coercion:** With only dirty
  image 3 (`document.xcf`) listed, `gimp_gimp_pdb_call`
  `name: "gimp-display-id-is-valid", args: {"display-id": 2}, undo_group: false`
  returned `status: success, values: [true]`; IDs 1 and 3–16 returned false.
  `gimp_gimp_pdb_describe` identified `gimp-display-delete` argument `display`
  as `GimpDisplay`. Calling `gimp_gimp_pdb_call` with
  `name: "gimp-display-delete", args: {"display": 2}, undo_group: false`
  failed before invocation: `TypeError: could not convert 2 to type
  'GimpDisplay' when setting property
  'GimpProcedureConfig-gimp-display-delete.display'`. The subsequent
  `gimp_gimp_list_images` still showed dirty image 3. Thus integer IDs work
  for validity probing but **not** for the `GimpDisplay` argument through the
  current bridge; do not claim this route closes a document. A bridge fix or
  another verified display-object conversion is needed. Do not retry deletion
  blindly.
- **Root cause (bridge 0.5.0), confirmed in its source:** `close_image` calls
  `image.delete()`, which GIMP refuses while a window is open, and the PDB
  argument converter has no case for `GimpDisplay`. Both need an upstream
  fix. Until then, **ask the user to close the tab** (and say whether to
  discard), then confirm with `gimp_gimp_list_images`.
- Always confirm with `gimp_gimp_list_images` after closing. Never report a
  document as closed on the tool's word alone.
- Ask before closing a document with `dirty: true`. Closing discards
  unsaved changes.

## Edits that worked (verified)

- New layer with fill: `gimp_gimp_layer` with `action: "new"`, `image_id`,
  `name`, `width`, `height`, `x`, `y`, `fill` (hex colour).
- Layer property change: `gimp_gimp_layer` with `action: "set"`,
  `layer_id`, and for example `opacity: 55`.
- Text layer: `gimp_gimp_text` with `image_id`, `text`, `x`, `y`, `size`
  (px), `color`, `name`.
- Group several edits into one Ctrl+Z step for the human with
  `gimp_gimp_edit_batch`. It is not a transaction, and a failure part-way
  leaves earlier steps applied.

## Interruptions

- A lost connection never replays an edit automatically, and neither should
  you. After any timeout or disconnect, re-read `gimp_gimp_list_images` and
  the layer tree, compare with what was intended, then decide.
