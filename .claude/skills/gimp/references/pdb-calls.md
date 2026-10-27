# PDB calls

> Adapted from AI-SKILL-gimp's `pdb-reference.md` and `pdb-recipes-*.md` (see [UPSTREAM.md](../UPSTREAM.md)):
> the same GIMP 3 procedures, rewritten as `gimp_pdb_call` arguments instead of Script-Fu or Python.
> Examples marked ✓ were called with exactly these arguments on GIMP 3.2.6 (2026-10-26).

GIMP's Procedural Database (PDB) exposes most operations as named procedures. Call them with
`gimp_pdb_call(name, args)`: arguments keyed by parameter name, images and items as ids, enums by nick,
colours as strings. Results come back as `{"values": [...]}`, items as `{"id": ...}`.

**When this applies:** an operation has no dedicated `gimp_*` tool (polygon selections, item reordering,
groups, transforms, most color procedures), or you need its exact contract.

## Discover the installed contract

`gimp_pdb_search("image select")` finds procedures by words in their names; `gimp_pdb_describe(name)`
gives the installed arguments, types, enum choices and return values. Do this before calling a
procedure you haven't used: availability and signatures depend on the installation, GIMP 3 renamed
many 2.10 procedures (e.g. `gimp-drawable-brightness-contrast`), and a menu label is not a procedure
name (there is no `gimp-drawable-hue-chroma` just because **Colors > Hue Chroma** exists). A GEGL
operation needn't have a PDB wrapper at all: use `gimp_apply_filter` for those.

## Layers and groups

```text
✓ gimp-group-layer-new      {"image": 1, "name": "Bed"}                       → values[0] = the group
✓ gimp-image-insert-layer   {"image": 1, "layer": 12, "parent": 9, "position": 0}   (omit parent: top level)
✓ gimp-image-reorder-item   {"image": 1, "item": 12, "parent": 9, "position": 0}    (0 = top of that parent)
✓ gimp-image-remove-layer   {"image": 1, "layer": 12}
✓ gimp-group-layer-merge    {"group-layer": 9}                               → values[0] = the merged layer
```

A group's own mode matters: Normal composites its members by themselves first; **pass-through** lets a
member's blend mode (Multiply, Divide, ...) act on what's below the group. Set it with
`gimp_layer(action="set", layer_id=<group>, mode="pass-through")`. Merging a group bakes it: duplicate
it first if you need the group afterwards.

## Selections

```text
✓ gimp-image-select-polygon {"image": 1, "operation": "replace", "segs": [x0, y0, x1, y1, ...]}
                            (operation: replace | add | subtract | intersect; subtract a hole ring)
✓ gimp-image-select-item    {"image": 1, "operation": "replace", "item": 12}   (a layer's alpha, a path, a channel)
✓ gimp-selection-grow       {"image": 1, "steps": 12}
✓ gimp-selection-feather    {"image": 1, "radius": 24.0}
✓ gimp-selection-none       {"image": 1}
  gimp-image-select-round-rectangle {"image": 1, "operation": "replace", "x": 10, "y": 10, "width": 200,
                                     "height": 80, "corner-radius-x": 20, "corner-radius-y": 20}
```

Also available (describe first): `gimp-selection-shrink`, `-border`, `-sharpen`, `-invert`, `-all`,
`-flood` (removes holes), `-bounds`, `-save` (to a channel), `gimp-image-select-color`,
`gimp-image-select-contiguous-color`, `gimp-image-select-ellipse`, `gimp-image-select-rectangle`.
Common cases are quicker with `gimp_select`.

## Pixels inside a selection

```text
✓ gimp-drawable-edit-clear  {"drawable": 12}       (clears the selected part to transparency)
```

`gimp_draw(action="fill_selection")` fills it. To cut part of a layer out as its own layer, see
[tool surface](tool-surface.md#restrictions-in-this-installation).

## Transforms

```text
✓ gimp-item-transform-matrix {"item": 12, "coeff-0-0": a, "coeff-0-1": b, "coeff-0-2": c,
                              "coeff-1-0": d, ..., "coeff-2-2": i}          → values[0] = the transformed item
  gimp-item-transform-scale  (x0, y0, x1, y1 of the new bounds), gimp-item-transform-rotate,
  gimp-item-transform-perspective, gimp-item-transform-flip-simple
  gimp-image-scale           {"image": 3, "new-width": 800, "new-height": 600}
```

Transforming a group transforms its members together. Each transform resamples: keep an untransformed
copy and transform from it again, rather than transforming a transformed layer repeatedly.
`gimp-item-transform-matrix` takes a 3×3 projective matrix (source → destination), e.g. a perspective
move on a floor plane.

## Colors and tone

```text
✓ gimp-drawable-desaturate  {"drawable": 12, "desaturate-mode": "luminance"}
  gimp-drawable-brightness-contrast {"drawable": 12, "brightness": 0.1, "contrast": 0.0}   (-1.0 .. 1.0)
  gimp-drawable-levels, gimp-drawable-curves-explicit, gimp-drawable-curves-spline,
  gimp-drawable-hue-saturation, gimp-drawable-color-balance, gimp-drawable-threshold (0.0 .. 1.0),
  gimp-drawable-invert, gimp-drawable-equalize, gimp-drawable-posterize
```

`gimp_adjust` covers the common ones without discovery, and `mode="append"` keeps them editable.
Curves take a vector of samples (no separate count argument in GIMP 3).

## Related

[tool surface](tool-surface.md) · [layers and modes](layers-and-modes.md) · [selections](selections.md) ·
[colors and adjustments](colors-and-adjustments.md)
