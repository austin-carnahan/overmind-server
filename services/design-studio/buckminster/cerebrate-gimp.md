# Cerebrate → GIMP: masks, cutouts and patches

Cerebrate (`cerebrate__*`) finds and outlines things in a photo, and repaints
regions. GIMP (`gimp_gimp_*`) is where the result lands. **Pass references,
never pixels.** Give Cerebrate a file path. Give GIMP outline points, or an
artifact URL. Don't fetch, base64 or view image bytes just to move them.

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

## 4. Cut out to a layer, move it

`gimp-edit-copy`/`paste` can't be called through `gimp_gimp_pdb_call`: it
rejects layer lists. Do this instead:

1. `gimp_gimp_layer(action="duplicate", layer_id=<base layer>)`
2. `gimp_gimp_layer(action="add_alpha", layer_id=<new>)`
3. `gimp_gimp_layer_mask(layer_id=<new>, action="add", type="selection")`
4. `gimp_gimp_layer_mask(layer_id=<new>, action="apply")`. Skip this to keep
   the mask editable.
5. `gimp_gimp_layer(action="crop_to_content", layer_id=<new>)`, then `set`
   the name, then `move` (dx, dy).
6. `gimp_gimp_pdb_call(name="gimp-selection-none", args={"image": <id>})`

The original stays in the base layer. To leave a clean background behind a
moved object, inpaint its region (step 5).

## 5. Remove or repaint → patch layer

1. `cerebrate__inpaint(image=<source path>, mask=<mask_png uri or url>)`.
   The mask is grown 7 px by default.
2. The result is `patch.url`, `offset [x, y]` and `size`: an RGBA patch
   covering only the filled pixels.
3. Place it:

   ```
   gimp_gimp_pdb_call(name="overmind-import-artifact",
                      args={"image": <id>, "url": <patch.url>, "x": <offset x>, "y": <offset y>,
                            "name": "lamp removed"})
   ```

   GIMP fetches the patch itself, from the artifact service only. You never
   handle its bytes.

Inpaint one modest object at a time. It runs on a window around the mask, so
a huge mask gives a softer fill. URLs expire with the artifacts (24 h). Call
again rather than reusing an old one.

## Gotchas

- Omit optional `gimp_gimp_pdb_call` arguments instead of passing `null`. For
  example, `parent=null` fails on `gimp-image-insert-layer`.
- A model may first need to start or wait for memory on the Pixel: up to a few
  minutes. "No capacity" means the phone is busy. Retry later, don't loop.
- Depth: `cerebrate__estimate_depth` returns a map artifact. It's data for
  reasoning (what's in front), not a layer.
