# Placement and compositing

**When this applies:** moving, resizing or duplicating an object in the room, keeping it in the right
depth order, completing the parts a move reveals, and grounding it with a shadow.

## Which objects can move [demonstrated]

An object group is a copy cut from the photo: its original pixels are still in the room underneath. An
object is **movable** only once its footprint has been rebuilt ([surface reconstruction](surface-reconstruction.md));
moving any other object leaves its original behind (seen as a duplicate). Treat the rest as **fixed**.
Objects it supports (a lamp on a nightstand) move with it.

## Moving

- **Same depth (sideways along the floor):** `gimp_layer(action="move")` on the group. One undo step;
  everything in the group follows. [demonstrated]
- **Several objects together:** one `gimp_edit_batch` of `layer` `move` steps, one per group: one undo
  step for all. [demonstrated: four groups, one Ctrl+Z]
- **Nearer or farther: place it on the floor.** A plain move keeps the size, which is wrong at another
  depth. With the floor horizon recorded (`overmind-set-floor-horizon`, two points on the floor's
  vanishing line), `overmind-place-on-floor` with the destination where the object's bottom should touch
  the floor:
  - scales the whole group by (destination's distance below the horizon) / (its floor anchor's), times
    an optional `scale-adjust` for a human correction; lands the anchor exactly; restacks the group by
    depth (in front of clearly farther objects, behind clearly nearer ones, ties keep their order);
  - always starts from a hidden pristine copy, so repeated placements never degrade; returns the **new
    group id**;
  - [demonstrated] three placements of the bed (0.99, 1.40, 0.78): anchors within 0.5 px, parts within
    0.9 px of their scaled offsets, sizes plausible against the nightstand.
- The horizon itself comes from the room's geometry ([surface reconstruction](surface-reconstruction.md)) **[gap]**.

**Limits** [demonstrated]: a uniformly scaled cutout keeps the side it showed in the photo, so long moves
look wrong; the horizon's tilt is the weakest input (a 2° tilt made a 1% size error on a sideways move);
depth order compares lowest points, which says little for objects at about the same depth; supported
objects should take their support's depth.

## Hidden parts of a moving object [demonstrated]

A move can reveal parts that were hidden behind something that stays (the bed's skirt behind the rug, or
under the comforter's end where the nightstand stood). Continue the object's own texture: a duplicate of
its original layer, shifted along the part's own edge, kept inside the revealed region grown ~5 px into
the visible part, placed at the bottom of the group.

Choose the shift by how well the copy matches the real object where they overlap, not just by whether
the source lies on the object: on the bed, coverage alone picked an offset that pulled comforter fabric
into the gap. Measuring the match is easier with image arrays **[gap]**; by eye, try a few offsets along
the edge and compare renders.

## Contact shadow [demonstrated]

A cut-out object floats once moved. Recover its real shadow instead of painting one:

1. Zone: the floor around the object inside its footprint (footprint minus the object, floor only).
2. In a temporary group: a copy of the photo cut to the zone, and above it a copy of the rebuilt room
   (merge a duplicate of the Room group: `gimp-group-layer-merge`) cut to the zone, in **Divide** mode:
   the group shows photo ÷ clean floor, i.e. the shadow.
3. Merge the temporary group, `gimp-drawable-desaturate` (luminance: per-channel ratios gave a yellow
   cast), blur ~6 px (`gegl:gaussian-blur`), set the layer to **Multiply**, and put it at the bottom of
   the object's group. The group must be **pass-through** (new object groups are).

With the object in place it reproduces the photo (mean difference under 1 level). It moves and scales
with the group. Limit: it is the shadow of the old spot, including other objects' shadows there.

## Related

[scene and objects](scene-and-objects.md) · [surface reconstruction](surface-reconstruction.md)
