# Surface appearance

**When this applies:** changing what a surface looks like while keeping it in place: repainting a wall
(and, as the capstone continues, recolouring fabric or replacing a material).

## Repainting a wall [demonstrated, E01]

**The mask** is most of the work:

1. Segment the wall with SAM 2.1 candidates ([scene and objects](scene-and-objects.md)). A large surface
   splits where the light changes: give it more than one box (upper and lower wall) and combine the best
   candidates.
2. Replay only the **outer** rings: the holes in a wall mask are mostly texture speckle and would leave
   pinholes. Subtract the real holes explicitly: windows **with their trim**, furniture against the wall
   (its object groups' alpha), anything standing in front (a stool).
3. Bound it by the room's lines: corner, ceiling line, baseboard top. Cut a few px above the baseboard,
   and add a strip to the corner if the segmentation stops short.
4. Keep the paint **2 px off** bright neighbours (grow the keep-out before subtracting), then feather the
   mask 2 px. Brightening a wall brightens any trim pixel inside the mask into a glowing line; a wider
   keep-out leaves a visible rim of the old colour instead.
5. Save the result as a channel ("Back wall (paint mask)") so every paint layer can use it.

**The colour:** one pass-through group per paint colour, inside the surface's group, containing:

- a **lift**: a grey layer in **Divide** mode, grey = 1 / k in linear light, where
  k = luminance(new paint) / luminance(old paint) (e.g. ×1.9 for Clary Sage over a mid grey);
- above it, the **swatch** colour in **LCh Color** mode: it takes hue and chroma from the swatch and keeps
  the lifted lightness, which carries all the photo's shading.

Both layers use the wall channel as their mask. Variants toggle by group visibility.

**What fails** (worth knowing so you don't retry it):

- Per-channel ratios (new paint / old paint in Multiply + Divide layers) carry the photo's colour cast:
  under warm light sage came out tan; referenced to the photographed wall itself, the ratios reached 11×
  and blew the wall out.
- Lifting the room's median wall to the swatch's own brightness over-exposes it: a paint chip is
  photographed in good light, the room isn't.
- Paint layers in Overlay/Color modes alone keep the old wall's dark lightness and look muddy.

**Old paint colour:** needed for k. A neutral sampled from a clean patch of the wall works; record it.

Limits: the wall's photographed colour cast remains in its shading; walls seen through gaps in furniture
(stool openings) keep the old colour unless masked by hand.

## Related

[scene and objects](scene-and-objects.md) · the gimp skill's [layers and modes](../../gimp/references/layers-and-modes.md)
