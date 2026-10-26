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

## 1. Point Cerebrate at the photo

Cerebrate reads design-studio project sources directly:
`/mnt/substrate/design-studio/projects/<project>/sources/<sha256>.<ext>`.
The path is in `project.json` under `sources[].file`.

- Masks come back in that photo's pixels. They line up with the GIMP document
  only if the document has the same size and hasn't been cropped or scaled.
  Check with `gimp_gimp_image_info`.
- Results also carry `artifact://` URIs and `url`s. Either can be passed back
  as an input, for example a mask to `inpaint`.

## 2. Find and outline

Call `cerebrate__list_capabilities` once to see what can run right now. Then
use one of these:

- **`cerebrate__detect_objects`**: no prompt. The default model has 80 common
  categories and reliable labels. `target="prompt-free-segmentation"` finds
  more objects, but its labels are odd.
- **`cerebrate__segment_by_text`**: phrases, e.g. `["wicker lamp", "rug"]`.
  Use this when you know what you want.
- **`cerebrate__detect_by_text`** then **`cerebrate__segment_region`**: boxes
  from phrases, then precise masks for those boxes.

**Check that each mask covers the whole object before using it.** EdgeSAM
given a bed's box outlined the comforter and left out the pillows. Add the
missing parts: segment their boxes too and add their rings to the selection,
or retry with `target="box-refinement@quality"`.

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

## 5. Remove or repaint → patch layer

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

   A patch computed from the original photo doesn't fit any of these.
   Inpainting the document's *current* pixels isn't available yet.

Inpaint one modest object at a time. The inpainting model works at 512 px,
on small and medium holes:
- **Lamps, clutter, marks:** fine.
- **A furniture-sized hole** (e.g. the floor and wall behind a moved bed):
  comes out as a colour smear. Don't present it as done; tell the user that
  area needs another approach.
- **Cast shadows** aren't in an object's mask. Add the shadow's area to the
  mask, or report what's left.

URLs expire with the artifacts (24 h). Call again rather than reusing an old
one.

## Gotchas

- Previews you `file_fetch` must be under 8 MB: export a JPEG. A full-size PNG
  is about 10 MB.

- Omit optional `gimp_gimp_pdb_call` arguments instead of passing `null`. For
  example, `parent=null` fails on `gimp-image-insert-layer`.
- A model may first need to start or wait for memory on the Pixel: up to a few
  minutes. "No capacity" means the phone is busy. Retry later, don't loop.
- Depth: `cerebrate__estimate_depth` returns a map artifact. It's data for
  reasoning (what's in front), not a layer.
