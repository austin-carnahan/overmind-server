# Cerebrate ⇄ GIMP: tool contracts

How Cerebrate (`cerebrate__*`) and GIMP (`gimp_gimp_*`, plus Overmind's `overmind-*` PDB procedures)
connect: the exact calls, what they return, and what to do when one refuses. **What to edit and why**
(scene structure, choosing masks, protecting objects, rebuilding surfaces, placement, shadows) is in
the `interior-scene-editing` skill; general GIMP technique is in the `gimp` skill
(`.claude/skills/` in the overmind-server repository).

Tool names here are OpenClaw's. Other clients prefix the same tools differently (Claude Code:
`mcp__gimp__gimp_*`, `mcp__cerebrate__*`).

**Pass references, never pixels.** Give Cerebrate a file path or an artifact URL; give GIMP outline
points or an artifact URL. Don't fetch, base64 or view image bytes just to move them.

## 1. Point Cerebrate at the image

- **An untouched document:** pass the project source's path. Cerebrate reads design-studio sources
  directly: `/mnt/substrate/design-studio/projects/<project>/sources/<sha256>.<ext>` (`project.json`,
  `sources[].file`). Results are in the photo's pixels, which match the document only while it has the
  same size and hasn't been cropped or scaled (`gimp_gimp_image_info`).
- **An edited document:** publish what it shows now:

  ```
  gimp_gimp_pdb_call(name="overmind-publish", args={"image": <id>, "mode": "image", "format": "jpeg"})
  ```

  Returns `[snapshot, image_url, mask_url, x, y, width, height]`. Pass `image_url` to any Cerebrate
  tool; with `mode: "image"` results are in document coordinates. Other modes: `selection` (the
  inpainting window around the selection, ≥ 512 px), `bounds` (the selection's box plus `margin`),
  `region` (`x, y, width, height`). `source` publishes one layer's or group's own composite instead of
  the canvas.

Results carry `artifact://` URIs and `url`s; either can go back in as an input (e.g. a mask to `inpaint`).
URLs expire with their artifacts (24 h): call again rather than reuse an old one.

## 2. Cerebrate tools

`cerebrate__list_capabilities` once, to see what can run now. Then:

| Tool | Gives | Notes |
| --- | --- | --- |
| `detect_objects` | boxes, labels (80 categories) | `target="prompt-free-segmentation"` finds more, odd labels |
| `detect_by_text` | boxes for phrases (OWLv2) | then `segment_region` on the box |
| `segment_region` | masks for boxes | `target="box-refinement"` (EdgeSAM, fast) or `"box-refinement@quality"` (SAM 2.1); `candidates=true` returns its three masks per box |
| `segment_by_text` | masks for phrases (EfficientSAM3) | second opinion; `threshold` |
| `inpaint` | an RGBA patch + `offset`, `context` | MI-GAN, 512 px window; mask grown 7 px by default |
| `seamless_blend` | a blended RGBA patch + `offset` | Poisson blend on Overmind's CPU; `destination` required |
| `estimate_depth` | a depth map artifact | data for reasoning, not a layer |
| `embed_image` | an embedding | |

Every mask has **`polygons`**: rings `{"hole": bool, "points": [x0, y0, x1, y1, ...]}`, in order. Labels
are often wrong: name layers from what you asked for or see.

## 3. Outline → GIMP selection

Replay the rings in order, one call each:

```
gimp_gimp_pdb_call(name="gimp-image-select-polygon", args={"image": <id>, "operation": <op>, "segs": <ring.points>})
```

`op` is `"replace"` for the first ring, `"add"` for each later outer ring, `"subtract"` for a hole.
Large regions can have 20+ rings; skipping holes or reordering gives the wrong selection.

## 4. Cut out, group, move, place

`gimp-edit-copy`/`paste` reject the bridge's layer lists. Instead:

1. `gimp_gimp_layer(action="duplicate", layer_id=<working layer>)`, then `add_alpha`
2. `gimp_gimp_layer_mask(layer_id=<new>, action="add", type="selection")`, then `action="apply"`
3. `gimp_gimp_layer(action="crop_to_content")`, then `set` its name; `gimp-selection-none`
4. **Group it before moving it:**
   `gimp_gimp_pdb_call(name="overmind-make-object-group", args={"image": <id>, "layer": <cutout>, "name": "Bed"})`
   returns the group (pass-through). It records where the cutout sat in the photo, which is how later
   patches find the object after it moves. Grouping after a move breaks that.
5. Move: `gimp_gimp_layer(action="move", layer_id=<group>, dx=…, dy=…)`. Several groups in one undo
   step: `gimp_gimp_edit_batch` with one `layer` `move` step each.

**Place on the floor** (move to another depth, rescaled):

```
gimp_gimp_pdb_call(name="overmind-set-floor-horizon", args={"image": <id>, "x0": …, "y0": …, "x1": …, "y1": …})
gimp_gimp_pdb_call(name="overmind-place-on-floor",
                   args={"image": <id>, "object": <group>, "x": <floor x>, "y": <floor y>, "scale-adjust": 1.0})
```

Returns `[group, report]`: the **new group id** (the old one is gone) and JSON (`scale`,
`perspective_scale`, `anchor`, `stacking`). Refuses without a horizon, without an anchored original, or
for a destination above the horizon. The first placement hides a pristine copy in "Placement originals
(hidden)"; leave it there.

## 5. Patches: inpaint → layer

**On an edited document (the default once anything has changed):**

1. Select the region, then `overmind-publish` with `{"image": <id>, "mode": "selection"}`.
2. `cerebrate__inpaint(image=<image_url>, mask=<mask_url>)`
3. Import into the repaired object's group, with the snapshot:

   ```
   gimp_gimp_pdb_call(name="overmind-import-artifact",
                      args={"image": <id>, "url": <patch.url>, "x": <offset x>, "y": <offset y>,
                            "name": "Lamp removed", "target": <layer or group>, "snapshot": <snapshot>})
   ```

   Offsets are the snapshot's. It refuses if the document no longer shows exactly what was published
   ("the document changed … since it was published"): publish a new snapshot and retry once, then
   report. **One snapshot, one repair.**

**On an untouched document:** `inpaint(image=<source path>, mask=<mask>)`, then import with
`"context-url": <context.url>` instead of `snapshot` (photo offsets; the plug-in adds the group's
movement). `target` is the object repaired; a lone layer gets a group (`"group-name"`). Refusals,
**don't `force`, report:** *context mismatch* (pixels changed, or wrong place), *can't verify* (wrong
target), *scaled or transformed* (the group was resized; use the snapshot route).

## 6. Blend a reconstruction

1. `gimp-image-select-item` with `{"operation": "replace", "item": <rebuilt group>}`.
2. `overmind-publish` `{"mode": "bounds", "margin": 48, "source": <the surface group, e.g. Room>}` →
   `[snapshot, image_url, mask_url, x, y, width, height]`.
3. `overmind-publish` `{"mode": "region", "x":…, "y":…, "width":…, "height":…, "source": <destination>}`
   → second value is `destination_url`. The destination is the original photo layer, or a temporary
   group (photo + surface band) when a protected object borders the area.
4. `gimp-selection-none`, then `cerebrate__seamless_blend(image=image_url, mask=mask_url, destination=destination_url)`.
5. `overmind-import-artifact` `{"url": patch.url, "x": offset x, "y": offset y, "name": "… (blended)",
   "target": <rebuilt group>, "snapshot": <snapshot>, "op-id": "<unique>"}`.

## Lost responses

If a call's response is lost (timeout, dropped connection), don't re-run it. Ask
`overmind-op-status` with `{"image": <id>, "op-id": "<the id>"}`: *done* → use its result; *started* or
*failed* → report it. Re-running with the same `op-id` after *done* is safe (same layer).

## Gotchas

- Omit optional `gimp_gimp_pdb_call` arguments instead of passing `null` (`parent=null` fails on
  `gimp-image-insert-layer`).
- Named operations only: GIMP's code evaluators (`python-fu-eval`, Script-Fu eval, console and server)
  are blocked. If GIMP can't do something through its procedures, say so; it becomes a reviewed
  plug-in, not code you send.
- A model may need to start or wait for memory on the Pixel: up to a few minutes. "No capacity" means
  the phone is busy: retry later, don't loop.
- Previews you `file_fetch` must be under 8 MB: export a JPEG (a full-size PNG is ~10 MB). Don't
  `file_fetch` the source photo (refused by read policy); look at your own exported preview.
