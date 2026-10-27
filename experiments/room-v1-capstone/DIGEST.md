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
| E13 Camera shift | partial → pass (v2) | v1: 2.5D ray-cast, coherent to ~25°, 26–51% holes. v2 (user direction): the 45° view faked in GIMP — painted wall + door, texture copies, framing — convincing |

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

| Need | Seen in | Today |
| --- | --- | --- |
| Map points from a wall rectangle / quad-to-quad warp (homography in the plug-in) | E05, E06, E08 | NumPy |
| Destination validation: behind a wall line, overlapping another footprint | E09, E10 | judgement |
| Restack a group by depth without moving it | E10 | place at its own anchor |
| Read a group's placement record (destination, scale) | E02 | the agent's memory |
| Mask set operations (union, fill small holes, drop islands, colour within a region) | E12 | NumPy |
| Displace by a map (prints following folds) | E03 | not available |
| `gimp_measure` on the composite | E01 | renders |
| Box rotation / reprojection of the room from the camera model | E05, E13 | NumPy reference in `tools/rotation/` |
| `plug-in-tile` and other drawable-array procedures through the bridge | E03 | duplicate layers |

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

These are good candidates for the baseline subset:
- **Should transfer:** E01, E04, E07, E11.
- **Likely to show the restricted architecture's cost:** E06/E08 (geometry) and E12 (mask arithmetic).

Freeze the skills with a tag before the replay (README, "Comparison protocol").
