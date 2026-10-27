# E13 v2 — the 45° view, faked convincingly in GIMP (2026-10-27_E13v2_claude-code_painted-45)

## Attempt

Redone after the user's review of v1:
- **The black right wall** is painted: its own colour, a gradient toward the corner, baseboards, and a
  door unit painted front-on and warped onto the wall where the photo implies it stands.
- **Walls, floor and ceiling** are each a GIMP layer warped by one matrix. Flat painted areas are covered
  by shifted copies of their own texture.
- **Furniture:** the bed as a box with real pillows as sprites; the nightstand, lamp and stool likewise.
- **The view is framed** to its convincing part.

## Observed

A believable room from 45° around: back wall with its window, the big window wall, the bed seen
end-on, nightstand and lamp, and now a right wall with a door. Compared with v1 (ray-cast, half the
frame black), it reads as a photograph of a room. Up close, the door is a little graphic and there is a
floor seam at the lower right.

## What helped or failed

- **The right wall's colour came from the narrow strip the photo does show.** It's warmer than the other
  walls because it faces the windows.
- **The door's position:** the rays to the casing graze the wall, so it can't be triangulated. The
  casing's contact with the floor gave its position; its size came from the ceiling height.
- **Shifted texture copies:** fine once each copy's source is bounded. An unbounded one mapped toward the
  horizon and hung GIMP (11 GB of swap) until it was restarted.
- **Small slips:**
  - layer order inside a group (the door ended up under the wall paint);
  - a brightness/contrast pass turned the dark door grey.

## Reusable rule or open question

For a new viewpoint:
- warp what the photo saw;
- paint what it didn't (sampled colour + gradient + grain);
- build known fixtures (doors, trim) front-on and warp them in;
- continue textures with shifted copies;
- frame the convincing part.

Open: softness and wear on painted elements; Poisson-blend the copy seams.
