# Cerebrate → GIMP: masks, cutouts and patches

Cerebrate (`cerebrate__*`) finds and outlines things in a photo, and repaints
regions. GIMP (`gimp_gimp_*`) is where the result lands. **Pass references,
never pixels.** Give Cerebrate a file path. Give GIMP outline points, or an
artifact URL. Don't fetch, base64 or view image bytes just to move them.

## 0. Document structure: one group per object

Each object or surface is a **layer group** ("Bed", "Room", "Walls"). Inside
a group are the object's original pixels and its repairs, each on its own
layer. **The group is the object.** Move, scale, hide or fade the group, not
its members, unless the user asks for detailed work.

- **The original photo.** Keep it at the bottom: duplicate the base layer,
  name the copy "Original photograph", hide it, and move it to the bottom.
- **Working layer.** Edit the visible base layer, renamed for what it is,
  e.g. "Room".
- **Never merge or flatten repairs** unless the user asks. They stay
  toggleable and editable.
- **Move groups, never members.** Every layer is movable on its own, so moving
  a member (a cutout, a patch, "Room (original)") pulls it out of alignment
  with the rest of its object. Move a member only when the user asks for
  that one piece. Nothing is position-locked to stop this.

## 1. Point Cerebrate at the image: the photo, or what the document shows now

- **An untouched document:** pass the project source's path. Cerebrate reads
  design-studio project sources directly:
  `/mnt/substrate/design-studio/projects/<project>/sources/<sha256>.<ext>`.
  The path is in `project.json` under `sources[].file`. Results come back in
  the photo's pixels, which line up with the document only while it has the
  same size and hasn't been cropped or scaled. Check with
  `gimp_gimp_image_info`.
- **A document that has been edited** (anything moved, removed or repaired):
  **publish a snapshot** of what it shows now:

  ```
  gimp_gimp_pdb_call(name="overmind-publish", args={"image": <id>, "mode": "image", "format": "jpeg"})
  ```

  It returns `[snapshot, image_url, mask_url, x, y, width, height]`. Pass
  `image_url` to any Cerebrate tool. With `mode: "image"` the snapshot is the
  whole canvas, so results are in document coordinates. For inpainting, use
  `mode: "selection"` (step 5).

Results also carry `artifact://` URIs and `url`s. Either can be passed back
as an input, for example a mask to `inpaint`.

## 2. Find and outline

Call `cerebrate__list_capabilities` once to see what can run right now. Then
use one of these:

- **`cerebrate__detect_objects`**: no prompt. The default model has 80 common
  categories and reliable labels. `target="prompt-free-segmentation"` finds
  more objects, but its labels are odd.
- **Named things: `cerebrate__detect_by_text`, then
  `cerebrate__segment_region`.** Boxes from phrases (OWLv2), then precise masks
  for those boxes (EdgeSAM). This is the default when you know what you want:
  "a wicker lamp" found the bedroom lamp exactly (0.67).
- **`cerebrate__segment_by_text`**: masks straight from phrases
  (EfficientSAM3). It missed the lamp: presence 0.74, but no instance at the
  default threshold. At `threshold: 0.3` it returned the ceiling fan as "lamp"
  and the whole bed as "pillow". Use it as a second opinion, and check what
  comes back.

**Getting a whole object's mask (furniture with parts, like a bed with its
pillows):**
1. Run `cerebrate__segment_region(image, boxes=[<detector box>], target="box-refinement@quality", candidates=true)`.
   SAM 2.1 returns three masks per box: roughly whole object, part,
   sub-part.
2. **Pick the candidate that covers the object you mean,** not the highest
   score. On the bed, the top-scoring one left out the pillows; candidate 1
   was the whole bed (99% body, 98% pillows). Check the overlay.
3. Fill enclosed holes: select the mask, then `gimp-selection-flood`.
4. Subtract the masks of stationary objects that touch it (a rug, a
   nightstand) with `"operation": "subtract"`.
5. Parts that need their own layers (pillows): segment their boxes too, and
   cut them as separate layers in the object's group.
6. Only if no candidate covers the object: combine two models' masks
   (EdgeSAM plus SAM 2.1). That's the fallback, not the default.

For simple objects (a lamp), EdgeSAM (`box-refinement`) is fine and faster.

**Objects have parts.** Segment parts the main mask misses (pillows on a
bed) on their own, and keep each as its own layer **inside the object's
group**, so they move together.
- **Before moving:** cut the parts and group everything.
- **Already moved:** cut each part from the original photo, then
  `gimp_gimp_layer(action="move")` it by the group's move: the main
  cutout's current position minus its mask's bounding-box corner (from
  Cerebrate's result).

**Recover before generating.** Pixels a mask missed are still in the photo.
Fix the mask (union two models' masks; fill enclosed holes) and cut the
missing pixels as a "(recovered pixels)" layer. Only pixels the photo
never showed can be made up, and only if they become visible. Even then,
first try continuing the object's own texture (a shifted copy along its
edge). MI-GAN fills with background, not more object.

**Protect what stays in front.** Anything that overlaps the area you rebuild
and isn't moving (a rug against the bed) gets its own object group above
the reconstruction. Otherwise the rebuilt floor covers it.

Labels are often wrong (the wicker lamp came back as "vase" and "ornament").
Name layers from what you asked for or what you see, not from the model's
label. Every mask has **`polygons`**: rings `{"hole": bool, "points": [x0, y0,
x1, y1, ...]}`, in order.

## 3. Outline → GIMP selection

Replay the rings in order, one call each:

```
gimp_gimp_pdb_call(name="gimp-image-select-polygon",
                   args={"image": <id>, "operation": <op>, "segs": <ring.points>})
```

`op` is `"replace"` for the first ring, `"add"` for each later outer ring, and
`"subtract"` for a hole. Large regions can have 20 or more rings. Skipping
holes or reordering rings gives the wrong selection.

## 4. Cut out to an object group, then move the group

`gimp-edit-copy`/`paste` can't be called through `gimp_gimp_pdb_call`: it
rejects layer lists. Do this instead:

1. `gimp_gimp_layer(action="duplicate", layer_id=<working layer>)`
2. `gimp_gimp_layer(action="add_alpha", layer_id=<new>)`
3. `gimp_gimp_layer_mask(layer_id=<new>, action="add", type="selection")`
4. `gimp_gimp_layer_mask(layer_id=<new>, action="apply")`
5. `gimp_gimp_layer(action="crop_to_content", layer_id=<new>)`, then `set`
   its name to "Original <object> cutout".
6. `gimp_gimp_pdb_call(name="gimp-selection-none", args={"image": <id>})`
7. **Group it now, before moving it:**

   ```
   gimp_gimp_pdb_call(name="overmind-make-object-group",
                      args={"image": <id>, "layer": <cutout id>, "name": "Bed"})
   ```

   The group records where the cutout sat in the photo. That's how later
   patches find the object after it moves. Grouping after a move breaks this.
8. Move it: `gimp_gimp_layer(action="move", layer_id=<group id>, dx=…, dy=…)`.

The object's pixels are still in the working layer underneath. To leave a
clean background behind a moved object, inpaint that region of the working
layer (step 5).

**Moving it nearer or farther: place it on the floor instead.** A plain move
keeps its size, so it only looks right at the same depth. Once the document
has a floor horizon (`overmind-set-floor-horizon`, two points on the floor's
vanishing line), call:

```
gimp_gimp_pdb_call(name="overmind-place-on-floor",
                   args={"image": <id>, "object": <group id>, "x": <floor x>, "y": <floor y>, "scale-adjust": 1.0})
```

- **What it does:** (x, y) is where the object's bottom should touch the
  floor. The whole group (parts, shadow) is scaled for that depth and moved
  there, then restacked in front of farther objects and behind nearer ones.
- **What it returns:** the **new group id** (use it from now on) and a report
  with the scale.
- **If it looks too small or large,** call it again with the same x, y and
  `scale-adjust` (e.g. 1.1). Every placement starts from the object's
  pristine copy, so nothing degrades.
- **What it can't do:** it doesn't change the viewing angle: an object
  moved a long way still shows the side it showed in the photo. Objects
  that sit on others (a lamp on a nightstand) need placing with their
  support.

## 5. Remove or repaint → patch layer

**On an edited document, use a snapshot (the default once anything has
changed):**

1. Select the region to fill (step 3's polygon rings, or any GIMP selection).
2. `gimp_gimp_pdb_call(name="overmind-publish", args={"image": <id>, "mode": "selection"})`
   returns `[snapshot, image_url, mask_url, x, y, width, height]`: the window
   around the selection as it looks now, and the selection as a mask.
3. `cerebrate__inpaint(image=<image_url>, mask=<mask_url>)`
4. Place the patch, in the repaired object's group, with the snapshot:

   ```
   gimp_gimp_pdb_call(name="overmind-import-artifact",
                      args={"image": <id>, "url": <patch.url>, "x": <offset x>, "y": <offset y>,
                            "name": "Lamp removed", "target": <layer or group id>, "snapshot": <snapshot>})
   ```

   The offsets are the snapshot's; the plug-in adds its origin. It first
   checks that the document still shows exactly what was published there.
   If it says *"the document changed … since it was published"*, someone
   edited that area, or you already used this snapshot. Publish a new one and
   run again, once; if it happens again, report it. **One snapshot, one
   repair.**

**On an untouched document, the photo works directly:**

1. `cerebrate__inpaint(image=<source path>, mask=<mask_png uri or url>)`.
   The mask is grown 7 px by default.
2. The result is `patch.url`, `offset [x, y]` and `size`: an RGBA patch
   covering only the filled pixels.
3. Place it **in the group of what it repairs**:

   ```
   gimp_gimp_pdb_call(name="overmind-import-artifact",
                      args={"image": <id>, "url": <patch.url>, "x": <offset x>, "y": <offset y>,
                            "name": "Lamp removed", "target": <layer or group id>,
                            "context-url": <context.url>})
   ```

   - **target** is the object being repaired. Pass its group, or any layer in
     it, and the patch goes into that group above it. A working layer that
     isn't grouped yet (e.g. "Room") gets a group around it on first use; add
     `"group-name": "Room"`, and the layer becomes "Room (original)".
   - **Offsets** stay the photo's. If the group has moved since it was
     grouped, the plug-in adds that movement.
   - **The check.** Before placing, it compares the photo's pixels around the
     fill (`context`) with what the target shows there. It returns the new
     layer and its group.
   - GIMP fetches both files itself, from the artifact service only. You never
     handle their bytes.

   **If it's refused, don't `force`; report it.**
   - *"context mismatch"*: the target's pixels changed since the photo, or the
     patch would land in the wrong place.
   - *"can't verify"*: the wrong target.
   - *"scaled or transformed"*: the group was resized since it was grouped.

   In all three cases the photo no longer matches the document. Use the
   snapshot route above instead.

Inpaint one modest object at a time. The inpainting model works at 512 px,
on small and medium holes:
- **Lamps, clutter, marks:** fine.
- **A furniture-sized hole** (e.g. the floor and wall behind a moved bed):
  comes out as a colour smear. Don't present it as done.
  - **Better:** rebuild it from the room's own surfaces, then blend (step 6).
  - **The geometry is manual so far:** surfaces, lines and floor
    perspective, described in `models/field-notes.md`, "Large holes". Ask the
    user before attempting it.
- **Cast shadows** aren't in an object's mask. Add the shadow's area to the
  mask, or report what's left.

URLs expire with the artifacts (24 h). Call again rather than reusing an old
one.

## 6. Blend a reconstruction into its surroundings

When you've rebuilt an area from copied pixels (layers in a group, e.g.
"Behind the bed (rebuilt)"), their light and colour won't match the edges.
Blend them with Cerebrate's Poisson blend, about 2 s on overmind:

1. Select the rebuilt area:
   `gimp_gimp_pdb_call(name="gimp-image-select-item", args={"image": <id>, "operation": "replace", "item": <rebuilt group>})`
2. Publish **the reconstruction**: the surface group's own composite, not the
   canvas, so objects in front don't get in:
   `overmind-publish` with `{"mode": "bounds", "margin": 48, "source": <e.g. the Room group>}`.
   It returns `[snapshot, image_url, mask_url, x, y, width, height]`.
3. Publish **the original** over the same region:
   `overmind-publish` with `{"mode": "region", "x":…, "y":…, "width":…, "height":…, "source": <the original layer>}`.
   It returns `destination_url` as its second value.
   **If a protected object (a rug) borders the rebuilt area,** the blend
   would pull the surface toward the object's colour (a haze along it).
   Publish instead a temporary group at the bottom of the stack, where it
   can't change the canvas. It holds a copy of the original and, above it,
   the main surface copy cut to a 15 px band inside the protected object,
   next to the rebuilt area. Remove the group after the import.
4. `gimp-selection-none`, then
   `cerebrate__seamless_blend(image=image_url, mask=mask_url, destination=destination_url)`.
   The destination must be the original: with the reconstruction there,
   nothing blends.
5. Import the patch above the raw layers, never merging them:
   `overmind-import-artifact` with
   `{"url": patch.url, "x": offset x, "y": offset y, "name": "… (blended)", "target": <rebuilt group>, "snapshot": <snapshot>, "op-id": "<unique>"}`.

**If a call's response is lost** (a timeout or a dropped connection), don't
re-run it. Ask `overmind-op-status` with `{"image": <id>, "op-id": "<the id>"}`:
- *done*: use its result;
- *started* or *failed*: report it.

Re-running with the same `op-id` after *done* is safe; it returns the same
layer.

## Gotchas

- Previews you `file_fetch` must be under 8 MB: export a JPEG. A full-size PNG
  is about 10 MB.
- Don't `file_fetch` the source photo. Cerebrate reads it from the project
  store by path, and `file_fetch` refused it anyway (read policy). Look at
  your own exported JPEG preview instead.

- Omit optional `gimp_gimp_pdb_call` arguments instead of passing `null`. For
  example, `parent=null` fails on `gimp-image-insert-layer`.
- Named operations only: GIMP's code evaluators (`python-fu-eval`, Script-Fu
  eval, console and server) are blocked. If you need something GIMP can't do
  through its procedures, say so; it becomes a reviewed plug-in, not code you
  send.
- A model may first need to start or wait for memory on the Pixel: up to a few
  minutes. "No capacity" means the phone is busy. Retry later, don't loop.
- Depth: `cerebrate__estimate_depth` returns a map artifact. It's data for
  reasoning (what's in front), not a layer.
