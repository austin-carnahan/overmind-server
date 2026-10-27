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

## Bringing in an outside object [demonstrated, E11]

A catalog or product photo of furniture, into the room as a movable object:

1. **Work from a derived copy** of the original (scale a large original down in GIMP and export it); keep
   the original untouched.
2. **Cut it out:** find it (`detect_by_text`), segment it with SAM 2.1 candidates and pick the one that
   covers the whole object including thin legs ([scene and objects](scene-and-objects.md)). Replay all
   rings: holes inside furniture (under an armrest) are real. Export the cutout as a transparent PNG (hide
   the background layer, `gimp_export`): that file is the reusable extracted object.
3. **Load it into the room** as a layer (`gimp-file-load-layer`, then `gimp-image-insert-layer`; crop to
   content).
4. **Calibrate its size once** against a known object at that object's depth: scale it so its height
   relates to, say, the nightstand's as their real heights do, and put its floor contact at the
   nightstand's floor contact. Placement on the floor handles every later depth.
5. **Group it** (`overmind-make-object-group`), then add, inside the group:
   - **room light**: a Multiply layer filled with the photographed colour of a known white object in the
     room (the nightstand's median, measured with `gimp_measure` histogram while it's selected), masked to
     the object. One editable layer turns studio light into the room's;
   - **contact shadow**: the silhouette filled black, flattened to the footprint's depth (~18% of the
     height), blurred, ~85%; plus a foot-contact layer (the bottom ~7% of the silhouette, lightly
     blurred, ~75%), both at the bottom of the group.
6. **Place it** with `overmind-place-on-floor`. The destination is where its **front** touches the floor:
   leave room for its depth behind it, or its back legs land in the wall.

**Edits after placement:** every placement rebuilds the group from its pristine copy ("Placement
originals (hidden)"), so layers added to a placed group are lost at the next placement. Add grounding and
light **before the first placement**, or edit the pristine copy and place again.

Limits: the object keeps the viewpoint and light direction of its source photo; choose sources shot from
roughly the room camera's height and angle.

## Mirroring or duplicating an object [demonstrated, E04]

- **Where a mirror is plausible:** a flipped copy shows the opposite side of the object, which is right
  only on the other side of the camera's view axis (an object right of centre shows its left side; its
  mirror belongs left of centre), at a similar distance from the wall.
- **Take supported objects along:** cut the object and what sits on it (nightstand + lamp) into one group.
- **Complete what the original hid before flipping:** the mirror shows it. In E04 the stool had hidden the
  nightstand's lower side panel; a copy of the visible panel shifted across filled it (stop short of
  edges and rails, whose shadows come along otherwise).
- Flip the group with `gimp-item-transform-flip-simple` (horizontal, auto-center) **with no selection
  active**, add grounding, then place it with `overmind-place-on-floor`.
- Limit: the lighting is mirrored too (the shaded side may now face the window).

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
