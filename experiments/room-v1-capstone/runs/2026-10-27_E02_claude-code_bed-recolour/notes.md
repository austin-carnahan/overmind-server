# E02 — Furniture recoloring (2026-10-27_E02_claude-code_bed-recolour)

## Attempt

Pillows to Goldenrod, the striped bed skirt to Clary Sage, as lift + LCh Color groups made **inside the
bed's pristine copy**, then the bed placed home, moved, and placed home again. Three segmenters on the
skirt.

## Observed

Mustard pillows and sage stripes with every fold and highlight; the recolour came back after each
placement. Attempt 2 grew the masks a few px to close a fringe.

## What helped or failed

- Edits to a placed object belong in its pristine copy; then every placement carries them.
- To segment the pristine copy, raise its container above the Room group and show it in place of the live
  object; at the bottom of the stack it is invisible (first try: every model scored ~0 on empty floor).
- Patterned fabric clips if lifted far: cap the lift (1.3 here).
- Models: SAM 2.1 c0 best; EfficientSAM3 "bed skirt" close behind (text works for this item, unlike E04);
  EdgeSAM missed the left end.

## Reusable rule or open question

Recolour objects in their pristine copy, with masks grown 2-3 px inside the object's own pixels. Open: no
tool reads where a group was last placed.
