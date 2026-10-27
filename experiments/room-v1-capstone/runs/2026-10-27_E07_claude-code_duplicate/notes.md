# E07 — Object duplication (2026-10-27_E07_claude-code_duplicate)

## Attempt

A second, matching nightstand-with-lamp on the other side of the view axis (near the corner), made as an
independent object without any model calls, then placed, moved and placed back with
`overmind-place-on-floor`. Three attempts; the mechanics passed from the first, the look by the third.

## Observed

- **The pair reads as a matched set:** the copy is smaller for its depth (×0.884), grounded, mirrored, and
  sits behind the bed's pillows.
- **Every check passed numerically:**
  - the copy re-placed at A after a move to B is pixel-identical to its first placement;
  - the original Nightstand group didn't change by a single pixel;
  - the depth stacking put the copy behind the bed, rug and original nightstand.

Renders: `attempt1-place-A.png` (jagged edge) → `attempt2-place-A.png` (panel completed, shadow strip) →
`place-A.png` (clean), and `place-B.png` (moved).

## What helped or failed

- **No re-segmentation needed:** selecting the existing nightstand and lamp layers' alpha and cutting from
  the photo gives a fresh layer, and a fresh anchor, for the copy.
- **Supported objects go with their support:** nightstand + lamp as one group.
- **Mirroring exposes the original's hidden side,** so the E04 fixes must come first:
  - continue the panel the stool hid;
  - trim the wall-shadow strip the old cutout included.

  Skipping them (attempt 1) repeats E04's flaws.
- **Grounding goes in before the first placement:** the shadow layers ride along and survive every
  re-placement.

## Reusable rule or open question

**Duplicating an object:**
1. Select its existing cutouts' alpha (and its supported objects').
2. Cut from the photo and make a new group.
3. Complete what was hidden and trim stray shadow; mirror if it goes across the view axis.
4. Ground it.
5. Place it with `overmind-place-on-floor`.

Open: the mirrored copy's lighting is mirrored too (its shaded side faces the window).
