# E12 — Difficult external extraction (2026-10-27_E12_claude-code_hard-extraction)

## Attempt

A wooden armchair with cushions from a cluttered study photo (CC BY 2.0, Andy Fogg): bookshelves, a desk,
a waste bin hiding a leg, a white cable across the seat, and the legs cut off by the frame. Extracted
and placed in the bedroom behind the bed.

## Observed

The final cutout is clean: full wooden frame, both cushions, the patterned pillow, the cable removed
without a trace, the open gaps under the arms kept open. In the bedroom it stands behind the bed, which
hides its cropped legs, at a believable size; its downward view suits this camera.

## What helped or failed

- **Models:**
  - SAM 2.1 on the whole chair gave the soft parts or the frame, never both cleanly; tight boxes per frame
    part gave clean wood.
  - EdgeSAM: no frame. EfficientSAM3: nothing.
  - So the solution was one model with several prompts, not a union of models.
- **Cable:**
  - SAM's holes alone missed the parts it had swallowed; a colour mask (near-white within the seat)
    caught the rest.
  - MI-GAN filled it perfectly: a thin occluder on a uniform cushion is its sweet spot.
- **Holes:** fill only small enclosed holes (the arm gaps are big and real).
- **Cropped base:** the anchor is the cut edge, so the object floats unless something nearer hides it.
  Here the bed did (attempt 5).

## Reusable rule or open question

Hard extractions: whole-object box for the broad parts plus tight boxes per thin part (same model);
inpaint thin occluders; fill only small holes. Hide a cropped base behind a nearer object. Open: mask
set operations through the shared tools.
