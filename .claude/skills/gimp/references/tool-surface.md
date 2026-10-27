# Tool surface

The GIMP Agent MCP server (gimp-agent-mcp 0.5.0) publishes 38 tools; with its Python tool off
(`GIMP_AGENT_ALLOW_PYTHON=0`) `gimp_run_python` is not among them. Tool names below are the server's;
your client prefixes them (`gimp_gimp_*` in OpenClaw, `mcp__gimp__gimp_*` in Claude Code).

**When this applies:** choosing a tool for a job, calling the PDB, or diagnosing a failed call.

## Which tool for which job

| Job | Tools |
| --- | --- |
| Orient | `gimp_status`, `gimp_list_images`, `gimp_image_info` (full layer tree with ids, offsets, sizes, modes, masks), `gimp_context` (selected layers, selection bounds) |
| Open, save, export | `gimp_open`, `gimp_export` (extension picks the format; `.xcf` saves the master), `gimp_new_image` (scratch documents), `gimp_close_image` |
| Layers and groups | `gimp_layer` (`new`, `set` name/visible/opacity/mode/x/y/lock, `move` dx/dy, `reorder` position/parent_id, `duplicate`, `merge_down`, `delete`, `scale`, `add_alpha`, `crop_to_content`, `info`) |
| Selections | `gimp_select` (rect, ellipse, color, alpha of a layer, item, all/none/invert, grow/shrink/feather/border; op replace/add/subtract/intersect). Polygons and anything else: `gimp_pdb_call` ([PDB calls](pdb-calls.md)) |
| Masks | `gimp_layer_mask` (`add` from selection/alpha/white/black/copy, `apply`, `remove`, `enable`/`disable`, `show`/`hide`) |
| Pixels | `gimp_draw` (fills, shapes), `gimp_adjust` (brightness/contrast, hue/saturation, curves, desaturate, blur, sharpen, ...), `gimp_apply_filter` (any GEGL op; `mode="append"` keeps it editable, `"merge"` bakes it), `gimp_layer_effects` / `gimp_layer_effect` (edit appended effects) |
| Canvas | `gimp_canvas` (scale, crop, resize, rotate, flip, merge_visible, flatten: all bake) |
| Text and vectors | `gimp_text`, `gimp_list_fonts`, `gimp_path` (create, select, stroke, fill) |
| Inspect and verify | `gimp_render` (`region`, `layer_id`, overlays incl. `points`), `gimp_measure`, `gimp_snapshot` + `gimp_render_compare` |
| Anything else | `gimp_pdb_search`, `gimp_pdb_describe`, `gimp_pdb_call` |
| Packaged jobs | `gimp_list_recipes`, `gimp_run_recipe`, `gimp_batch_recipe` (tested jobs shipped with the server, not arbitrary code) |
| Multi-step undo | `gimp_edit_batch` (no PDB calls inside) |
| Cut-out without a model server | `gimp_remove_background` (needs the server's optional segmentation extra) |
| Help | `gimp_help(topic)` |

## Conventions

- `gimp_pdb_call(name, args)`: arguments keyed by the procedure's parameter names; images and items as
  ids; enums by nick (`"replace"`, `"multiply"`, `"luminance"`); colours as strings. Each call is one
  undo group.
- Coordinates are image pixels. A layer's `x`/`y` in `gimp_image_info` are its offsets.
- GIMP keeps layer names unique: a copy of "Bed" becomes "Bed #1". Rename after copying.
- `gimp_layer(action="new")` always creates at the top level; move it into a group with
  `gimp_layer(action="reorder", layer_id=…, parent_id=<group>, position=0)`.
- `gimp-item-transform-flip-simple` and other transforms act on the **selection** if one is active (they
  float it): `gimp-selection-none` first when you mean the whole item.
- Procedures taking a **drawables array** (e.g. `plug-in-tile`) fail through `gimp_pdb_call` on GIMP 3.2
  (`set_core_object_array` error): find another route (tiling = duplicate the layer at offsets).
- `gimp-item-transform-matrix` clips every point whose projective w is negative: a homography that is right
  up to sign can return an **empty** layer. Normalise the matrix so w > 0 over the layer (multiply by -1).
- A projective transform whose source maps toward the horizon produces an enormous layer: GIMP can grind for
  many minutes and exhaust memory (E13 v2: 11 GB of swap; GIMP had to be restarted). Clip the source to the
  part that maps inside (a margin around) the canvas before transforming.
- `gimp_layer(action="reorder", position=…)` is the position in the parent's final list: when moving a layer
  down within the same group, recompute the index after it leaves its old slot.
- Avoid `gimp-group-layer-merge` on a freshly duplicated group: once (E05) it merged the document's whole top
  level into one layer. To get one layer of an object, select its members' alpha and cut from the source
  layer instead.
- **Bringing a file in as a layer:** `gimp_pdb_call("gimp-file-load-layer", {"image": id, "file": path})`,
  then `gimp-image-insert-layer`. To hand a cutout from one image to another, hide the other layers,
  `gimp_export` it as PNG (alpha is kept) and load that.
- **Working on a copy of a document:** there is no file-copy tool. Open the original, `gimp_export` it
  to the copy's `.xcf` path before editing, and from then on export only to that path. GIMP's title bar
  may still show the original's name: never save with GIMP's own Save there.
- `gimp_measure` reads **one layer** (the selected one unless you pass `layer_id`), not the composite: to
  check what the canvas shows, render it. `kind="histogram"` respects the selection, which makes it the
  way to measure a region's colour (mean/median per channel).
- Multiply, Divide and the LCh modes blend in linear light (verified to within 1 level), so colours for
  such layers should be computed in linear light too.
- A selection made from polygons is antialiased: expect a 1–2 px soft edge. Account for it when you
  compare pixels "outside" a region.

## Restrictions in this installation

- Procedures that run caller-supplied code are refused through `gimp_pdb_call`: `python-fu-eval`,
  the Python and Script-Fu consoles, `plug-in-script-fu-eval`, the Script-Fu server. Use named
  operations.
- Clipboard procedures (`gimp-edit-copy`/`paste`) reject the layer lists the bridge passes. To copy
  part of a layer: duplicate it, add alpha, add a mask from the selection, apply the mask, crop to
  content.
- Only one bridge runs at a time; a second start reports the running one and exits.

## Known failure modes

- **A call times out or the response is lost.** The operation may still have completed. Inspect
  (`gimp_image_info`, `gimp_render`) before repeating anything; Overmind's own procedures also keep an
  operation journal (`overmind-op-status`).
- **`gimp_close_image` doesn't close an image that has a window** in GIMP 3.2. Leave it, or ask the
  person to close it.
- **Unsaved images block quitting GIMP** with a dialog. Save or confirm before any restart.
- **Some GEGL operations aren't usable as filters** (e.g. `gegl:seamless-clone` is "hidden"); the
  error says so. Look for a server-side alternative rather than retrying.
- **Whole-canvas pixel operations can take minutes** on a 12 MP image and time the call out. Work on a
  bounding box, or crop a working copy.

## This installation's extra procedures

Overmind adds PDB procedures named `overmind-*` (artifact publish/import for Cerebrate, object groups,
blending, floor placement, operation status). Their contracts and safety rules are in the integration
adapter: `services/design-studio/buckminster/cerebrate-gimp.md` in the overmind-server repository.

## Environment-dependent alternatives

Some agents have capabilities beyond these tools; others don't. They are **not** steps in this skill:
use them only where your environment provides them, and record it when you do.

- **Claude Code on the Mac:** Python with the bridge client (including the bridge's `exec` op, which the
  MCP server doesn't expose), and local image processing (NumPy, OpenCV) on renders or exports.
- **Buckminster:** a non-sudo shell on Overmind (not on the Mac that runs GIMP).

When a task needed one of these, record which and why, and whether a named MCP operation or a small
reusable primitive could do it instead. That is how missing capabilities get found.

## Related

[PDB calls](pdb-calls.md) · [layers and modes](layers-and-modes.md) · [selections](selections.md) ·
[masks and channels](masks-and-channels.md)
