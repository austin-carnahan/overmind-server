# E05 — Simulated 90-degree rotation (2026-10-27_E05_claude-code_rotation)

## Attempt

Several objects and approaches (scope widened by the user): mirror (A), face swap with a guessed ratio
(C2D), a camera-based 3D face rearrangement (C3D), and leaving symmetric objects alone (D). Objects: the
bed, the nightstand with its lamp, the stool, and the external cabinet asset.

## Observed

The bed turned 90 degrees reads as the same bed seen side-on; the nightstand re-posed against the left
wall, drawers into the room, lamp on top, is convincing. The stool and the cabinet asset are the failure
cases: an open frame bakes the background into its faces; a frontal product shot can't give a camera.

## What helped or failed

- Two perpendicular baselines (the baseboards) give the camera: f 2393 px, 12 deg tilt; verticals within 6 px.
- Fit boxes from floor contacts (hems, legs), not from the tops of fabric-covered objects.
- Hidden faces: use the opposite face, mirrored. Small objects on top: move them as sprites anchored in 3D.
- GIMP clips a projective transform whose w is negative: normalise the matrix's sign.
- Avoid gimp-group-layer-merge on duplicated groups (one run lost the document's top level); cut from the
  photo with a translated selection instead.

## Reusable rule or open question

Choose by object: solid box + receding room geometry → C3D; symmetric → D; frontal asset → A; open frame or
ornate → don't rotate (or A). Open: a quad-to-quad warp primitive would make C3D possible without code.
