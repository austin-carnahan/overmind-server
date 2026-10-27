# E10 — Partial concealment (2026-10-27_E10_claude-code_concealment)

## Attempt

The catalog chair (E11's cutout, reused) placed so other objects hide part of it and it hides part of
them: in front of the nightstand, behind the bed, and beside or in front of the stool.

## Observed

- **Occlusion was right in every physically valid arrangement**, from whole-group order alone:
  - the chair over the nightstand, its carved legs and the gaps under its arms open;
  - the bed's pillows over the chair's seat;
  - the chair's arm over the stool.
- **"Partly behind the nightstand" isn't possible in this room:** the nightstand is against the wall. My
  attempt put the chair inside the wall and on the stool.

## What helped or failed

- **Only object groups can occlude.** The stool was still part of the Room layer, so the chair drew over it
  regardless of depth. Cutting it out as an object group fixed that.
- **A new object group lands at the top of the stack:** placing it at its own floor anchor (scale 1.0)
  restacks it without moving it.
- **No validation:** placement checks neither the wall line nor whether the floor is free.

## Reusable rule or open question

Before arranging objects, make every object that might need to occlude something its own group
(including small things like stools), and restack new groups by placing them in place. Open: a
restack-by-depth procedure and destination validation.
