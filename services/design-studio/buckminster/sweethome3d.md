# Sweet Home 3D: rooms in 3D, edited live on the Mac

Sweet Home 3D is a floor-plan and 3D room editor running on the Mac next to GIMP. Its tools (`sweethome3d_*`)
change the **open project live**: each call shows up in the person's 2D plan and 3D view as it runs. Use it to
build or rearrange a room in 3D, try layouts, and render views to compare with a photo or bring into GIMP.

The tools exist only while Sweet Home 3D is open on the Mac. If they're missing or every call fails, ask the
person to open it. Don't keep retrying.

## The model

- **Units:** centimetres. **x** grows to the right on the plan, **y** grows **down**. Elevations and
  heights are centimetres above the floor.
- **Ids:** every object has a stable id (`wall-…`, `room-…`, `pieceOfFurniture-…`, `doorOrWindow-…`). Get them
  from `get_state` or from the call that created the object, and never guess them.
- **Camera yaw:** 0 looks south (+y), 90 west (−x), 180 north (−y), 270 east (+x). Pitch is positive
  downwards. `lookAt: {x, y, z}` aims the camera for you.
- **Catalogue:** furniture, doors and windows come from the built-in catalogue (about 180 items). Look items up
  with `list_furniture_catalog` (by `category` or `query`) and place them by **`catalogId`**. A name like
  "window" matches several items and is refused.
- **Doors and windows** go into a wall: `place_door_or_window` with `wallId` and `position` (0 = the wall's
  start, 1 = its end) fits and orients them. Windows take `elevation` (sill height, typically 80–100).
- **Other shapes:** `generate_shape` makes boxes, cylinders, arches and stairs, extrusions of a polygon, and
  cuts (union, subtract, intersect). Use it for built-ins the catalogue lacks.

## Co-editing with the person

They may be working in the same project while you do.

1. **Look first.** Call `get_state` before each change set: the person may have moved, added or deleted
   things since your last look.
2. **Checkpoint before every change set:** `checkpoint(description="before <what>")`. Your edits are **not**
   on Sweet Home 3D's Edit → Undo, so the checkpoint is the only way back. Tell the person its id.
3. **Change in one batch:** `batch_commands(commands=[{"action": "<tool>", "params": {…}}, …])`. Check its
   `failed` count and fix only the failed entries.
4. **Rolling back:** `restore_checkpoint(id=…)` restores the whole project to that point, including the
   person's own edits since then. Ask before restoring if they've been editing. Checkpoints live in memory
   and are lost when the app quits.
5. **Leave their objects alone** unless asked: add your own, and name them clearly.
6. **Never** overwrite the person's project file. `save_home` only with a `filePath` under
   `~/DesignStudio/workspaces/<project>/runs/<run>/`, and a new name each time.

`clear_scene`, `load_home` and `delete_level` aren't available to you. They replace or wipe the person's
work; ask the person to do these.

## Geometry: compute it, then send it

Compute positions with your Python on Overmind (`runbooks/python.md`): walls from measured dimensions,
furniture footprints, camera positions matching a photo. Print the result as the `commands` list for one
`batch_commands` call. Keep the script and its inputs in your workspace, as for any computation.

## Rendering and GIMP

- **Look at a view:** `render_photo` with `quality: "low"` and about 800×600 returns a JPEG in the reply.
  That takes about 12 s on the Mac.
  - Pass `x, y, z, yaw, pitch, fov` for a specific camera, or `view: "overhead"` for a bird's-eye view.
- **Final renders:** use `"medium"` or `"high"` only when asked. Rendering loads the Mac's CPU while
  GIMP is open.
- **Into GIMP:** render with `format: "png"` and a `filePath` under the run's DesignStudio folder. Then
  load it as a layer with `gimp_gimp_pdb_call("gimp-file-load-layer", {"image": id, "file": path})` and
  `gimp-image-insert-layer`. Both programs are on the Mac, so the file path is enough; no upload is needed.
- **The plan:** `export_plan_image` (PNG) or `export_svg`, also to the run folder.

## When something fails

- **The first call after a long pause fails:** sessions expire after 30 idle minutes, and the connection
  reconnects on its own. Retry that call once.
- **A placement is refused:** the error names the problem, for example an ambiguous name (it lists the
  candidates' ids), or an unknown id (call `get_state`).
