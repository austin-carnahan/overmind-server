# E13 v3 — the 45° view on a corrected camera (2026-10-27_E13v3_claude-code_corrected-camera)

## Attempt

A third pass after the v2 review. That review flagged four things: walls and ceiling all over the place, a near
room that looked extended, the closet door in the wrong place, and the fan gone.

- **The camera was the real problem.** v1 and v2 took the walls' vanishing points from the top and bottom edges of
  the baseboards. Those lines are only ~90 px apart, so where they meet was badly off. The old camera put the
  ceiling at 1.16, 1.30 or 1.49 camera heights depending on which corner it was measured at. v3 takes each
  wall's vanishing point from its floor line and ceiling line. That gives f 1598 (was 2393) and a single
  ceiling height, 1.69–1.70 everywhere. The vertical vanishing point it predicts matches the one measured from
  the door casing and window trim.
- **The camera stays in the room.** v2's orbit about the room centre put the camera 0.8 units behind the near
  wall: that was the "extended room". v3 turns the view 45° and stands against the near wall.
- **Planes clipped in 3D:** each room rectangle is cut to the new view, then to the photo's view. The source and
  target polygons share the model's edges, so the room meets at its corners by construction.
- **The door:** the photo's own grazing view of the right wall, warped, holds the real closet doorway near the
  back corner: casing, open slab, strap hinges, knob. It's kept inside the door outline, with the wall painted
  around it and a crisp casing painted front-on and laid over the opening edges.
- **The fan:**
  - **Mask:** SAM 2.1 on a box, plus two hand-drawn chains.
  - **Removal:** MI-GAN took it off the ceiling texture; its shadow on the ceiling stays.
  - **Placement:** one upright sprite at its canopy, scaled by distance. The user's tip: a fan looks alike from
    any side.
- **Furniture:** v2's boxes, carried into the new camera through their image corners. Faces nearly edge-on to
  the new camera are painted, not warped. The bed's cut is reduced to its main outline, and the pillows are
  nudged onto the bed.

## Observed

The room reads as one space photographed from the window-side end of the near wall:
- the left window wall and the back wall with its small window meet the ceiling cleanly;
- the closet doorway sits at the corner end of the right wall;
- the fan hangs over the bed, the pillows stand up, and the lamp, nightstand, stool and rug sit where they should.

What still shows:
- the bed's right side reads a bit like a plank, and the bed looks large and slab-like;
- the doorway interior is stretched;
- the right wall is flat paint.

## What helped or failed

- **Check the camera against itself first:**
  - one ceiling height at every corner;
  - a predicted vertical vanishing point that matches measured verticals.

  Either check would have caught v2's flaw before any warping.
- **Planning previews** (PIL, the same matrices) chose the camera position in seconds, before the slow GIMP build.
- **Nightstand ghost cleanup:**
  - **Shifted copy of the wall:** showed as a darker rectangle, because the window light differs along the wall.
  - **MI-GAN on the plain wall:** clean.
  - **Baseboard:** needed its band mapped onto the band, anchored to edges measured on pixel columns. The lens
    bends the edges by ~10 px.
- **Slivers flung across the view:** both from faces near edge-on and from small stray islands in a cut. Paint the
  former and drop the latter.
- **Closing images:** `gimp-image-delete` and `gimp_close_image` both fail on an image with a window.

## Reusable rule or open question

For a nearby viewpoint:
1. Calibrate from widely separated lines (floor + ceiling), then verify (constant ceiling height, vertical
   vanishing point).
2. Keep the camera inside the room.
3. Clip planes in 3D.
4. Reuse grazing photographed detail before painting.
5. Treat symmetric fixtures as sprites.
6. Paint edge-on faces.
7. Frame.

Open: a skirt-stripe texture for edge-on bed sides, rather than flat paint.
