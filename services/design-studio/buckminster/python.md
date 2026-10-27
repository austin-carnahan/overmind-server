# Python on Overmind (computation for design work)

You can write and run Python on Overmind with your `exec` tool. Use it whenever a step needs computation:
- geometry: homographies, vanishing points, camera estimates, corner positions;
- measuring pixels: edges, colours, mask areas;
- mask arithmetic: unions, holes, islands, polygons;
- checking a result numerically.

Apply the results to the document through GIMP's named procedures as usual.

## The environment

```text
/mnt/substrate/design-studio/python/       on the SSD; you use it, you don't change it
  bin/uv                                   maintenance (wraps uv with this environment's settings)
  pyproject.toml, uv.lock                  what is installed
  .venv/bin/python                         Python 3.12 with numpy, scipy, opencv-python-headless, pillow,
                                           scikit-image, shapely
```

- **Run a script:** `/mnt/substrate/design-studio/python/.venv/bin/python script.py args…`
- **Need another package?** Ask for it, and say what it's for.
  - Writes under `/mnt/substrate/design-studio/` aren't yours to make; project folders belong to
    `design-checkpoint`.
  - Meanwhile, solve it with what's installed if you can.
- **Where scripts go:** in your workspace, one folder per task (for example `compute/<project>/<task>/`).
  - Give each script a short docstring, its inputs as a JSON file, and its output as JSON.
  - A script someone can rerun is the record of how a number was found. Say its path in your report.

## The boundary

| Where | What runs there |
| --- | --- |
| **Overmind** (your `exec`) | Your Python: computation, files in your workspace. |
| **The Mac** (GIMP) | Named operations only, through the GIMP tools. GIMP's code evaluators (`python-fu-eval`, Script-Fu eval, the console) stay blocked. |

Compute here; apply there with the procedures (for example `gimp-item-transform-perspective` with the corners your
script printed).

## Getting pixels into a script

- **Export a preview** from GIMP into the run's DesignStudio folder (JPEG, under 8 MB), then `file_fetch` it. Scale
  coordinates back if the preview is smaller than the document.
- **Use an artifact URL.** `overmind-publish` and Cerebrate results return signed URLs, which a script can download
  with `urllib.request`.
- **Pass coordinates you already have** (corners, polygon points) as JSON. Many steps need no pixels at all.

## Be a good neighbour

Overmind is a 4-core Raspberry Pi that also runs the home's services.
- Keep jobs short.
- Prefer NumPy and OpenCV over per-pixel Python loops.
- Start anything heavy with `nice -n 10`.
- Never run long batch jobs in parallel.
