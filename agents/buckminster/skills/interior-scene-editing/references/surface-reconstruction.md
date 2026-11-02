# Surface reconstruction

**When this applies:** an object moves or is removed and the wall, baseboard and floor behind it must
appear. Small holes (a lamp, clutter, marks) are an inpainting job; furniture-sized ones are this.

## Why not inpaint [demonstrated]

Cerebrate's `inpaint` (MI-GAN, 512 px window) fills small and medium holes well. Behind a moved bed it
produced a colour smear. Rebuilding from the room's own surfaces, then blending, gave continuous walls,
baseboards and floor.

## The procedure

1. **Footprint and protection** first ([scene and objects](scene-and-objects.md#protection)). The blend's
   edge must land on clean surface, or it drags dark or light pixels in.
2. **Surface masks from the room's lines** [demonstrated; geometry is [gap]]: trace each baseboard's top
   and bottom edges (line fits to 0.5 px); the baseboards' tops meet at the wall corner. Split the
   footprint into wall (above the baseboard top), baseboard, and floor (below its bottom), per wall.
3. **Walls and baseboards: copies shifted along their own line** [demonstrated]: a duplicate of the
   photo, moved along that wall's baseboard direction to a clean stretch, kept inside the surface's
   mask (`gimp_layer` move, then mask from selection). Choose sources clear of vents and window light.
4. **Floor: a perspective-correct move on the floor plane** [demonstrated; geometry is [gap]]: the two
   baseboards' vanishing points give the floor's vanishing line; a translation in the rectified floor
   plane becomes one 3×3 matrix (`gimp-item-transform-matrix` on a duplicate of the photo).
   - One move rarely finds clean floor for the whole footprint: the main piece covers the whole floor
     mask; small extra pieces from other moves go on top, feathered ~24 px into it.
   - **Sources must be valid floor** [demonstrated]: below the baseboard, away from the footprint, away
     from stationary objects **and their contact shadows** (else their shadow is copied in), clear of
     vents, and bounded by everything the lines don't describe: doorframes, a side wall (a piece copied
     from the right wall gave a grey wedge).
5. **Blend** (next section).
6. **Keep it editable**: Walls / Baseboard / Floor groups inside "Behind the <object> (rebuilt)", with
   the blended layer on top. Never merge them.

Ask the user before attempting steps 2–4 by hand: they are slow and approximate without the geometry.

## Blending [demonstrated]

Copied pieces don't match the light at their edges; a single gain per piece gave a colour cast. Use
Cerebrate's Poisson blend (`seamless_blend`, ~2 s):

- **image**: the surface group's own composite (not the canvas: objects in front must not get in),
  over the footprint's bounds plus a margin;
- **mask**: the footprint;
- **destination**: the **original photo** over the same region. With the reconstruction as the
  destination nothing blends: the blend matches the destination in a ring inside the mask.
- **Along a protected object** the destination must show surface, not the object: in a ~15 px band
  inside the protected object next to the footprint, use the main floor piece's texture (a temporary
  group: photo copy + that band layer, at the bottom of the stack; remove it afterwards). Without it the
  floor hazes toward the rug's white.
- The result is clipped to the footprint (its alpha is the mask); import it above the raw pieces.

The calls and their arguments: the adapter's "Blend a reconstruction" section.

**When the footprint changes** (a trimmed seam, a correction): add the piece, delete the blended layer,
and run the blend again over the new footprint. [demonstrated]

**Extra floor pieces** blended on their own must use their floor neighbours as the destination edge,
and their own pixels elsewhere; a destination of "everything around" pulled an unfilled white sheet in.
Feathering them into the main piece is simpler and was good enough. [experimental]

## Accepted limits

- Seams fade but can remain where a source is much darker than its surroundings (a soft band along the
  footprint's bottom edge in the bedroom).
- Anything never visible (an outlet behind the bed) can't come back.
- The geometry is per-room and manual; it isn't automated or available as a tool yet.

## Related

[scene and objects](scene-and-objects.md) · [placement and compositing](placement-and-compositing.md)

## Ghosts on a lit wall with a baseboard [demonstrated, E13 v3]

A residue patch spanning wall, baseboard and floor (where furniture was removed):
- **Plain wall: MI-GAN.** A copy shifted along the wall carries a different light level and shows as a rectangle.
- **Floor: a copy shifted along the floor plane**, feathered ~40 px.
- **Baseboard: map the band onto the band.** Use a 4-point warp whose corners sit on the baseboard's top and
  bottom edges, **measured on pixel columns** on both sides of the patch. Fitted room lines are ~10 px off
  locally (lens bending), which shows as steps at the joins.

