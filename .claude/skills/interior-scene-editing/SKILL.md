---
name: interior-scene-editing
description: "Edit photos of rooms as layered GIMP scenes with Cerebrate: decompose a room into objects and surfaces, extract furniture with its parts, protect what stays, rebuild hidden walls/baseboards/floor behind a moved object, place objects at a new floor position with perspective scale and depth order, add contact shadows, and verify the result. Use for interior design or decorating edits on a room photo (move, remove, add, resize furniture; rebuild what was behind it). Load the gimp skill for general GIMP technique."
metadata:
  status: "seeded 2026-10-26 from the bedroom experiments (models/field-notes.md); evolves during the Room V1 capstone"
---

# Interior scene editing

A room photo becomes an editable **scene**: each object and surface is a GIMP group, the original stays
hidden underneath, and every change is a layer you can toggle. Use the **gimp** skill for GIMP technique
and tool choice, and the integration adapter `services/design-studio/buckminster/cerebrate-gimp.md` for
the exact Cerebrate and `overmind-*` call contracts. This skill says what to do and why.

Labels: **[demonstrated]** worked on a real room and was checked; **[experimental]** worked once or
partly; **[gap]** needs a capability the shared MCP tools don't have yet (see
[capability notes](#capability-notes)).

## The workflow

1. **Analyze the scene.** Structural surfaces (walls, baseboards, floor, windows), furniture, each
   object's parts, what occludes what, what will move and what stays. [Scene and objects](references/scene-and-objects.md)
2. **Extract objects** into groups, parts included, recovering pixels the mask missed before generating
   anything. [Scene and objects](references/scene-and-objects.md)
3. **Protect what stays**, especially where it touches what moves. [Scene and objects](references/scene-and-objects.md#protection)
4. **Rebuild what the move reveals** from the room's own surfaces, then blend.
   [Surface reconstruction](references/surface-reconstruction.md)
5. **Change appearance** (repaint a wall, recolour or retexture a surface) without moving it.
   [Surface appearance](references/surface-appearance.md)
6. **Place and integrate**: move or place on the floor, depth order, hidden parts, contact shadow.
   [Placement and compositing](references/placement-and-compositing.md)
7. **Verify**, then report what's demonstrated and what's approximate. [Verification](#verification)

## Principles

- **The group is the object.** Move, scale or hide groups, not members. [demonstrated]
- **Recover before generating.** Pixels the photo shows are better than any model's guess; generate
  only what was never visible, and then try continuing the object's own texture first. [demonstrated]
- **Inpainting models complete backgrounds, not objects**, and smear furniture-sized holes. [demonstrated]
- **Keep a pristine source.** The original photo stays hidden and untouched; transforms start from an
  untransformed copy. [demonstrated]
- **Non-destructive by default**: rebuilt pieces stay separate layers under their blended result. [demonstrated]
- **One reference document stays untouched**; experiment on a copy (see the gimp skill's tool surface,
  "Working on a copy").

## Verification

- **Render with the moved object hidden** to inspect the rebuilt background, and with it shown for the
  result. Compare against the photo (`gimp_snapshot` before, `gimp_render_compare` after). [demonstrated]
- **Protected pixels unchanged:** outside the rebuilt area the composite should equal the photo except a
  1–2 px antialiased edge. Compare against GIMP's own copy of the photo, not another decoder's (JPEG
  decoders differ by a few levels). [demonstrated]
- **Measure placements** with `gimp_measure(kind="bbox")` on the object's original layer: its bottom
  should sit where you put it. [demonstrated]
- **Report** limits honestly: approximate geometry, unseen viewpoints, accepted seams.

## Capability notes

The shared tools are the GIMP Agent MCP (38 tools), Cerebrate (9 tools) and Overmind's `overmind-*`
GIMP procedures. In the bedroom experiments these steps needed more than that (an operator's Python
with NumPy/OpenCV) and are marked **[gap]**: the room's line and vanishing-point geometry, the floor
source search, per-pixel mask arithmetic beyond selection add/subtract/grow, and choosing a
texture-continuation offset by measurement. An agent without such tools can do a manual approximation
(by eye, with renders) or stop and report the gap. Record which route you took.

Also missing from the tools: reading what the document stores about the room (the recorded floor
horizon, a group's placement record). `overmind-place-on-floor` reports them when it runs; keep that
report.
