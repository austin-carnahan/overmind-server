# E06 — Perspective warping (2026-10-27_E06_claude-code_perspective)

## Attempt

Two curtain panels from the window-dressing asset hung from the existing rod over the big window, on the
oblique left wall. Corners two ways: A along the image lines (linear), B through the window trim's own
homography.

## Observed

B looks right: the near panel larger, the far one foreshortened, tops on the rod, the trim half covered.
A's far panel is too wide, as if it faced the camera. After softening the room-light layer the curtains read
cream, as in the asset, and sit in the room's light.

## What helped or failed

- The global camera (E05) tilted this wall's horizontals by ~4 deg; the window trim, a real rectangle on the
  same wall, is the better local reference.
- An exported cutout keeps its whole canvas: crop the loaded layer to content before warping.
- `gimp-item-transform-perspective` takes the four target corners; only their positions need computing.

## Reusable rule or open question

Planar items on a wall: find a real rectangle on that wall (window, door, frame), work in its rectified
coordinates, warp with transform-perspective. Open: a tool to map rectangle coordinates to image points.
