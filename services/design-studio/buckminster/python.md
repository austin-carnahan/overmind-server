# Python on Overmind (computation for design work)

You can write and run Python on Overmind with your `exec` tool. Use it whenever a step needs computation:
- geometry: homographies, vanishing points, camera estimates, corner positions;
- measuring pixels: edges, colours, mask areas;
- mask arithmetic: unions, holes, islands, polygons;
- checking a result numerically.

Apply the results to the document through GIMP's named procedures as usual.

## The environment

```text
/mnt/substrate/design-studio/python/       on the SSD; you can read and write it
  bin/uv                                   run scripts, add packages (wraps uv with this environment's settings)
  pyproject.toml, uv.lock                  what is installed
  .venv/bin/python                         Python 3.12 with numpy, scipy, opencv-python-headless, pillow,
                                           scikit-image, shapely
```

- **Run a script:** `/mnt/substrate/design-studio/python/bin/uv run --no-sync python script.py args…`
  - Or call `.venv/bin/python` directly.
- **Need another package?** `/mnt/substrate/design-studio/python/bin/uv add <package>`
  - It updates `pyproject.toml` and the lock.
  - Mention it in your report, so it can be carried into the repository.
- **Where scripts go:** keep them with the work, in the project folder under `/mnt/substrate/design-studio/projects/<project>/`.
  - Give each script a short docstring, its inputs as a JSON file, and its output as JSON.
  - A script someone can rerun is the record of how a number was found.

## The boundary

| Where | What runs there |
| --- | --- |
| **Overmind** (your `exec`) | Your Python: computation, files in your workspace and project folders. |
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
