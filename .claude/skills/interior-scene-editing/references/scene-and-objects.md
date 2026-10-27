# Scene and objects

**When this applies:** setting up a room document, finding and cutting out furniture, deciding what
moves and what stays.

## Document structure [demonstrated]

```text
Rug                         an object group in front (stays)
Bed                         an object group: its original cutout + parts + continued parts + shadow
  Pillow (left)
  Pillow (right)
  Bed (original)
  Bed skirt behind the rug (continued)
  Contact shadow (from the photo)        Multiply; the group is pass-through
Nightstand, Lamp            object groups (stationary until their footprints are rebuilt)
Room                        surfaces
  Behind the bed (rebuilt)  Walls / Baseboard / Floor pieces + the blended result
  Room (original)           the photo, as the working base
Original photograph         hidden, untouched
```

- One group per logical object; parts (pillows) and repairs are members. New object groups come from
  `overmind-make-object-group` (pass-through, anchored for later patches): group a cutout **before**
  moving it.
- Surfaces get their own groups inside Room; repairs to a surface go in its group.
- Order the top level by depth: nearer objects above farther ones.

## Analyze before cutting

List: structural surfaces and their boundary lines (baseboards, wall corner, window), each piece of
furniture and its parts, what each object occludes and is occluded by, contact shadows, and which
objects the edit moves. An object resting on another (a lamp on a nightstand) is **supported by** it and
must move with it. [demonstrated on the lamp: left behind unless included]

## Finding objects

- Named things: `detect_by_text` ("a wicker lamp"), then `segment_region` on its box. The default when
  you know what you want. [demonstrated]
- `detect_objects` for a prompt-free inventory (80 common categories). [demonstrated]
- `segment_by_text` as a second opinion only: it has returned the ceiling fan as "lamp" and the whole
  bed as "pillow". [demonstrated]
- Labels are often wrong ("vase" for a lamp): name layers from what you asked for or see.

## Getting the whole object's mask [demonstrated]

1. `segment_region(image, boxes=[box], target="box-refinement@quality", candidates=true)`: SAM 2.1
   returns three candidates per box (roughly whole, part, sub-part).
2. **Pick the candidate that covers the object without spilling onto neighbours**, judged on an
   overlay, not by score or size. Bed: candidate 1 (99% body, 98% pillows; the top score left the
   pillows out). Rug: candidate 0 with a box padded ~15 px (the tight box missed its tail). Lamp:
   candidate 0 (candidate 1 spilled onto its wall shadow).
3. Fill enclosed holes (select the mask, `gimp-selection-flood`).
4. Subtract the masks of stationary objects that touch it.
5. Segment parts the mask misses (pillows) on their own and cut each as its own layer in the group.
6. Fallback only: union two models' masks (EdgeSAM + SAM 2.1) when no candidate covers the object.

Simple compact objects: EdgeSAM (`box-refinement`) is fine and faster.

## Recover before generating [demonstrated]

Pixels a mask missed are still in the photo: fix the mask and cut them as "(recovered pixels)". Only
what the photo never showed may be generated, and only if it becomes visible (e.g. a bed's skirt hidden
behind a rug, revealed by the move). Continue the object's own texture first ([placement and
compositing](placement-and-compositing.md#hidden-parts-of-a-moving-object)); MI-GAN filled the bed's
skirt with floor.

## Protection

Before rebuilding anything, classify pixels near the moving object [demonstrated]:

- **known foreground**: stationary objects (rug, nightstand, stool): protected, never overwritten;
- **structural surface**: what the rebuild may replace;
- **uncertain band**: within ~10 px of both the moving object and a protected one. Inspect it.

The rebuild area (the footprint) is the moving object and its parts, grown ~22 px for edge fringe, plus
its contact shadow (~50 px on the floor side), **minus** protected objects. Every protected object that
overlaps the footprint gets its own group above the reconstruction, or the rebuilt floor covers it.

**The seam between a protected and a moving object** [experimental]: the protected mask can hold the
moving object's pixels (the rug's mask held 1,087 px of grey bed skirt, invisible until the bed moved).
In the uncertain band, look for pixels that match the moving object, not the protected one (there: the
skirt was much darker than the fleece). Clear them from the protected layer, add them to the footprint,
and rebuild under them. In GIMP: a by-colour or threshold selection intersected with the band; a
per-pixel brightness rule is easier with image arrays **[gap]**.

## Related

[surface reconstruction](surface-reconstruction.md) · [placement and compositing](placement-and-compositing.md)
