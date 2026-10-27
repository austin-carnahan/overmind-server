# E04 — Basic mirroring (2026-10-26_E04_claude-code_mirror-nightstand)

## Attempt

Compared segmenters first (user: be open to other models): SAM 2.1 candidates, EdgeSAM, EfficientSAM3
text. Cut nightstand + lamp from the room photo into one group, flipped it, grounded it, placed it on
the other side of the camera's view axis near the corner, at the original's distance from the wall.

## Observed

A matching pair on the back wall; the copy is smaller for its depth (x0.88), grounded, with its lamp.
The mirrored copy revealed the side panel's lower corner, which the stool had hidden; continuing the panel
fixed it (attempts 2-3). The copy's lighting is mirrored: its shaded side faces the window.

## What helped or failed

- Models: SAM 2.1 c0 and the existing EdgeSAM cutout were best; EfficientSAM3 found nothing from text.
  Loose boxes pull cast shadows into masks; a tight box keeps them out.
- Mirroring is plausible only where the geometry is symmetric about the camera's view axis: an object
  right of centre shows its left side; its mirror belongs left of centre.
- Flip with no selection active (`gimp-item-transform-flip-simple` floats the selection otherwise).

## Reusable rule or open question

Before mirroring, complete anything the original hid (continue its texture), because the mirror shows
it. Open: correcting the flipped lighting (a gradient or curves on the side panel).
