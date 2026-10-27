# E13 — Modest camera viewpoint shift (2026-10-27_E13_claude-code_camera-shift)

## Attempt

A new viewpoint of the whole room from one photo:
- **The camera:** recovered from the two baseboards (E05's model), orbited about the room's centre by 12,
  25, 33 and 45 degrees, moving into the room.
- **Three methods:**
  - **A:** the photo projected onto the room's five planes.
  - **B:** A plus furniture as textured boxes and billboards.
  - **C:** B with the small objects inpainted out of the room texture first.
- **Rendering:** a small ray-caster, one RGBA layer per element, imported into GIMP as one group per view.

## Observed

- **Method C holds well at 12° and 25°:** walls, windows, baseboards and floor line up in the new
  perspective; the bed box turns as a bed would; nightstand, lamp and stool sit where they should.
- **The geometry still holds at 45°,** but half the frame is unseen (black).
- **Method A** flattens the bed onto the floor; by 25° it reads as a rug. The baseline failure, as
  expected.

## What helped or failed

- **The photographer stood in the doorway:** the camera sits just outside the near right wall's plane.
  - Orbiting out of the room smears the doorway.
  - Orbiting in puts the doorway behind the camera, which per-plane warps can't handle.
  - A per-pixel ray-caster does.
- **Holes are honest, not fixable here:** the near wall and most of the ceiling were never photographed.
  MI-GAN can't fill holes that size.
- **Breaks from about 33°:** pillows painted flat on the bed's top, and the lamp and stool as cards.
- **The Mac slept on battery** in the middle of an inpaint; reran under `caffeinate -i`.

## Reusable rule or open question

A nearby view = camera from two perpendicular baselines + room planes + furniture boxes + ray casting,
with one layer per element. Useful up to ~25° for this photo; beyond that, a generative fill for unseen
surfaces is the missing piece.
