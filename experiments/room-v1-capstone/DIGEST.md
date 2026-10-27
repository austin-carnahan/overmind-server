# Room V1 capstone — digest (Claude Code, exploratory run)

All 13 experiments ran on 2026-10-26/27 on copies of `bedroom-v1.xcf`. The reference file is unchanged
(hash checked). Each run's `run.yaml` and `notes.md` hold the evidence. The skills evolved in focused
commits, listed in each record's `skill_updates`.

| Exp | Result | In one line |
| --- | --- | --- |
| E01 Wall recolour | pass | All three walls; lift + LCh Color; masks from the room's own edges |
| E02 Furniture recolour | pass | Pillows and skirt recoloured in the pristine copy, so the colour survives moves |
| E03 Pattern replacement | partial | Real-scale print in perspective per face; it doesn't follow folds |
| E04 Mirroring | pass | Mirrored nightstand + lamp across the view axis; hidden panel completed |
| E05 90° rotation | pass (solid furniture) | Camera from the baseboards; box re-facing for the bed and nightstand; fails on open frames and frontal shots |
| E06 Perspective warp | pass | Curtains placed via the window trim's homography |
| E07 Duplication | pass | Independent copy without re-segmentation; pixel-identical re-placement |
| E08 Wall art | pass | Reference rectangle with its measured aspect, not a guessed one |
| E09 Overlap/ordering | pass | Depth stacking right whenever the placement was physically possible |
| E10 Concealment | pass | Whole-group order suffices; only object groups can occlude |
| E11 Furniture import | pass | Catalogue chair: cut out, light-matched, grounded, placed, moved again |
| E12 Hard extraction | pass | One model, several prompts; MI-GAN removed the cable; cropped base hidden behind the bed |
| E13 Camera shift | v1, v2 partial → v3 pass | v1: 2.5D ray-cast, coherent to ~25°, 26–51% holes. v2 (faked in GIMP): misaligned edges from a bad camera, camera outside the room. v3: camera re-derived and verified, view kept inside the room, planes clipped in 3D, photographed doorway reused, fan as a sprite — coherent 45° view (pending review) |

## Worked unchanged (repeatable from the skills)

- **Object groups:** one group per object, pristine copies, and `overmind-place-on-floor` (scale, anchor,
  depth order, identical re-placement). Also: edits go in the pristine copy, and grounding goes in before
  the first placement.
- **Recolour:** a Divide lift + LCh Color layer, masked per surface (walls, fabric).
- **Imports:** cut out → transparent export → load as layer → calibrate size at a reference's depth →
  Multiply light by a known white's photographed colour → shadow → place.
- **Masks:** SAM 2.1 candidates picked by coverage; tight boxes per thin part; MI-GAN for thin occluders
  and small objects.
- **Flat items on a wall:** a real rectangle on the same wall, its true aspect, then
  `gimp-item-transform-perspective`.

## Needed judgement

- **Masks:** choosing candidates (always on an overlay) and drawing wall boundaries from the room's edges.
- **Placement:** destinations that leave room for an object's depth, keep clear of walls and other
  objects, and hide a cropped base.
- **Look:** light-match strength (softer next to windows), when to stop on seams, and which rotation
  method suits which object.

## Missing primitives (observations; each record has the detail)

**Revised 2026-10-27.** Buckminster now writes and runs its own Python on Overmind. In the
[E08 rerun](runs/2026-10-27_E08_buckminster_python-validation/notes.md) it computed the homography and metric
rectification itself, within 0.04 px of E08, and applied the result through GIMP's named procedures. So
**computation is no longer a tool to build.** What remains for GIMP-side primitives is work *inside the
document*, and one transport gap: getting pixels computed on Overmind back into GIMP.

| Need | Seen in | Claude Code used | Buckminster now |
| --- | --- | --- | --- |
| Map points from a wall rectangle / quad-to-quad warp (homography) | E05, E06, E08 | NumPy | **its own code** (validated: E08) |
| Box rotation / reprojection of the room from the camera model | E05, E13 | NumPy reference in `tools/rotation/` | its own code (untested) |
| Mask set operations (union, fill small holes, drop islands, colour within a region) | E12 | NumPy | its own code on the masks' polygons or PNGs, applied as selections (untested) |
| Destination validation: behind a wall line, overlapping another footprint | E09, E10 | judgement | its own code on footprints (untested) |
| `gimp_measure` on the composite | E01 | renders | its own code on an exported preview (untested) |
| Restack a group by depth without moving it | E10 | place at its own anchor | GIMP primitive still (a document operation) |
| Read a group's placement record (destination, scale) | E02 | the agent's memory | GIMP primitive still |
| Displace by a map (prints following folds) | E03 | not available | GIMP primitive, or computed pixels **if** they can be brought back into GIMP |
| `plug-in-tile` and other drawable-array procedures through the bridge | E03 | duplicate layers | GIMP-side fix still |
| **New: computed pixels back into GIMP** | — | the Mac's file system | open: Buckminster can fetch from the Mac (`file_fetch`) but has no write path back. An upload to the artifact store + `overmind-import-artifact` would close it. |

## Limitations that belong in the skills

- **Gone for good:**
  - Cutouts keep their source viewpoint and light direction; mirrored copies keep mirrored light.
  - Anything never photographed (backs of objects, a near wall, the ceiling beyond the frame) stays a hole.
- **Approximate:**
  - The room camera from short baselines is only approximate on far walls; local rectangles are better.
  - Fabric prints stay flat across folds.

## For the comparison with Buckminster

The run records separate MCP use from everything else:
- **Shared MCP tools only:** most edits ran on them alone (E02, E04, E07, E09, E10, E11 almost entirely).
- **Needed more:** numerical geometry (E05, E06, E08, E13) and mask arithmetic (E12).

Since 2026-10-27 Buckminster has Python on Overmind, so "needed more" no longer means "out of reach". The
comparison now measures:
- whether the agent recognises when to compute;
- whether it writes correct code;
- whether it hands the results to GIMP well.

The question is no longer which tools the architecture lacks. Candidate subset:
- **Should transfer:** E01, E04, E07, E11.
- **Computation by its own code:** E06 (E08 is already validated), E05, and E12 (the mask arithmetic, plus the
  pixel-transport gap if it needs computed pixels).

Freeze the skills with a tag before the replay (README, "Comparison protocol").
