# E11 — External furniture import (2026-10-26_E11_claude-code_chair-import)

## Attempt

The public-domain Rococo armchair (a museum photo on white). Cut out with SAM 2.1 (candidate 0 covered
the whole chair, legs and arm gaps right), exported as a transparent PNG, loaded into the bedroom copy
with `gimp-file-load-layer`, sized against the nightstand at its depth, grouped, light-matched, shadowed,
and placed with `overmind-place-on-floor`: by the window, then across the room.

## Observed

The matte is clean (no studio-white fringe), the chair takes the room's warm light, sits at a believable
size, and the bed stays in front of it. Moving it again needed nothing but another placement call. The
first shadow was too faint; the first second position put the back legs in the wall.

## What helped or failed

- Light match: Multiply by the photographed colour of a known white object in the room (the nightstand),
  measured with `gimp_measure` histogram under a selection. One layer, editable.
- Size: calibrate once against a known object at its own depth; the horizon handles every later depth.
- The placement anchor is where the object's front touches the floor: leave room for its depth behind it.
- Placement rebuilds from the pristine copy: grounding layers added after the first placement are lost;
  edit the pristine copy (in "Placement originals (hidden)") instead.

## Reusable rule or open question

Import = cut out → transparent export → load as layer → calibrate size at a reference's depth → light
match (Multiply by a known white) → contact shadow (flattened silhouette + foot contact) → group → place.
Open: the chair still shows the studio's viewpoint and light direction.
