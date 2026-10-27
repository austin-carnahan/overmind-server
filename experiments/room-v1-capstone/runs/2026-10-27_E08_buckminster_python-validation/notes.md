# E08 rerun by Buckminster with its own Python (2026-10-27_E08_buckminster_python-validation)

## Attempt

A capability check, not a new design.
- **Setup:** Buckminster got E08's method and inputs (the window trim's corners, the camera, the print's
  placement), not a script. It was asked to compute the print's corners with its own Python on Overmind, then
  apply them to a disposable copy of the bedroom through GIMP's named procedures.
- **Before the run:** the environment was provisioned (`/mnt/substrate/design-studio/python`), and its runbook
  was linked into Buckminster's workspace with a pointer in `AGENTS.md`.

## Observed

- **Pass on the first attempt, in about 8 minutes.**
  - **Calculation:** Buckminster wrote `compute.py` (with `inputs.json` and `output.json`) and ran it in the
    environment. It got a trim ratio of 1.60823 (rounded to 1.61) and edges 85.20° apart. Its corners are within
    0.04 px of E08's recorded ones.
  - **Application:** in GIMP it loaded the cutout as a layer, cropped it to its content, called
    `gimp-item-transform-perspective` with the corners, named the layer, saved and exported.
- **Checked in GIMP:**
  - the layer spans x 2662–3383 and y 792–1272, the corners' bounding box exactly;
  - the render shows the print right of the small window in the wall's perspective.
- **One deviation, reported by Buckminster itself:** its `AGENTS.md` forbids direct writes under
  `/mnt/substrate/design-studio/`, where project folders belong to `design-checkpoint`. So it kept the script in
  its workspace instead of the folder the brief named. That was the right call; the brief and the runbook were
  wrong.

## What helped or failed

- **Method plus inputs was enough.** No script was supplied; the agent derived the same mathematics.
- **The runbook conflicted with the agent's own policy** in two places:
  - where scripts go;
  - `uv add`, which writes under the same directory.

## Reusable rule or open question

E08's "Needed more" item was a homography plus metric rectification. That is now Buckminster's own code on
Overmind; it doesn't need a dedicated GIMP primitive. The same likely holds for the other geometry and
mask-arithmetic items in the digest's list (E05, E06, E12, E13). Each still needs its own run to confirm it.
