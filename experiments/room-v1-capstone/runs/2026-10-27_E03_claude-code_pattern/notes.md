# E03 — Material and pattern replacement (2026-10-27_E03_claude-code_pattern)

## Attempt

The floral jacquard (Poly Haven, CC0) on the bed skirt, inside the bed's pristine copy: real-scale
repeat, then perspective per face, then shading carried over from the old skirt.

## Observed

The print reads at a believable scale and turns the corner in perspective; the skirt keeps its broad light
and shadow. It does not ripple with the folds, so the fabric looks stiffer than the original.

## What helped or failed

- Flat tiling over a 3D object looks like wallpaper; warp a strip onto each face instead (corners from a
  gridded render).
- Shading: a desaturated copy of the object, median-blurred to remove its old pattern, in Multiply,
  divided by its median grey.
- Clear the selection before transforms (they act on the selection otherwise).
- `plug-in-tile` fails through `gimp_pdb_call`; tile by duplicating layers.

## Reusable rule or open question

Material swap = per-face perspective + median-blurred shading. Open: making the print follow folds
(a displacement by the shading map) — not possible through the current tools.
