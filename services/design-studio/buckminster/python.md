# Python on Overmind (computation for design work)

You can write and run Python on Overmind with your `exec` tool. Use it whenever a step needs computation:
- geometry: homographies, vanishing points, camera estimates, corner positions;
- measuring pixels: edges, colours, mask areas;
- mask arithmetic: unions, holes, islands, polygons;
- checking a result numerically.

Apply the results to the document through GIMP's named procedures as usual.

## The environment

```text
/mnt/substrate/design-studio/python/       on the SSD; yours to manage
  bin/uv                                   add packages, sync (wraps uv with this environment's settings)
  bin/overmind-artifact                    move images to and from GIMP (see "Co-editing" below)
  pyproject.toml, uv.lock                  what is installed
  .venv/bin/python                         Python 3.12 with numpy, scipy, opencv-python-headless, pillow,
                                           scikit-image, shapely
```

- **Run a script:** `/mnt/substrate/design-studio/python/.venv/bin/python script.py args…`
- **Need another package?** `/mnt/substrate/design-studio/python/bin/uv add <package>`
  - It updates `pyproject.toml` and the lock.
  - Mention it in your report, so it can be carried into the repository.
  - This directory is the one exception to "nothing under `/mnt/substrate/design-studio/`": project folders
    there still belong to `design-checkpoint`.
- **Where scripts go:** in your workspace, one folder per task (for example `compute/<project>/<task>/`).
  - Give each script a short docstring, its inputs as a JSON file, and its output as JSON.
  - A script someone can rerun is the record of how a number was found. Say its path in your report.

## The boundary

| Where | What runs there |
| --- | --- |
| **Overmind** (your `exec`) | Your Python: computation, files in your workspace and in the Python environment. |
| **The Mac** (GIMP) | Named operations only, through the GIMP tools. GIMP's code evaluators (`python-fu-eval`, Script-Fu eval, the console) stay blocked. |

Compute here; apply there with the procedures (for example `gimp-item-transform-perspective` with the corners your
script printed).

## Co-editing: pixels from GIMP to Python and back

The person may be editing the same document in GIMP while you work. Move pixels as snapshots, so neither of you
overwrites the other.

1. **Publish** what you need from the live document:
   - call `overmind-publish` with `mode` `"region"` (x, y, width, height), `"bounds"` or `"selection"`;
   - use `"image"` only when you truly need the whole canvas;
   - add `source=<group>` for one group's own pixels.

   It returns `snapshot` and `image-url` (plus `mask-url` for the selection).
2. **Download it:** `bin/overmind-artifact get <image-url> in.png`.
3. **Compute** with your script. Write the result as a PNG (RGBA for anything that should be partly transparent),
   the same size as the snapshot, or with its offset inside it.
4. **Upload it:** `bin/overmind-artifact put out.png <name>`. This prints JSON with `url`.
5. **Import it:** `overmind-import-artifact` with
   - `url`, and `x`, `y` in the snapshot's coordinates (0, 0 = its corner);
   - `snapshot=<the snapshot>`, `name`, and an `op-id`;
   - `target=<object layer or group>` when the result belongs to an object.

   The new layer lands exactly where it was computed, as one undo step for the person.

**Rules for working alongside the person:**
- **Refused import:** the person changed that area since you published. Publish again, recompute and import. Never
  use `force` unless they ask for it.
- **Publish small:** a snapshot of the whole canvas is refused after an edit anywhere; a small region only after an
  edit there.
- **Add, don't overwrite:** add your results as new, clearly named layers (or into the object's group). Leave the
  person's layers alone unless asked.
- **Lost response:** ask `overmind-op-status` with the op-id before trying again.

**Limits:** uploads are PNG or JPEG, up to 32 MB each, 500 a day. They're kept 24 h.

## Other ways to get pixels into a script

- **Pass coordinates you already have** (corners, polygon points) as JSON. Many steps need no pixels at all.
- **Fetch a preview** you exported from GIMP into the run's DesignStudio folder (JPEG, under 8 MB) with
  `file_fetch`. Scale coordinates back if the preview is smaller than the document.

## Be a good neighbour

Overmind is a 4-core Raspberry Pi that also runs the home's services.
- Keep jobs short.
- Prefer NumPy and OpenCV over per-pixel Python loops.
- Start anything heavy with `nice -n 10`.
- Never run long batch jobs in parallel.
