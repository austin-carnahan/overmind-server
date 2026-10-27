# E01 — Wall recoloring (2026-10-26_E01_claude-code_wall-sage)

## Attempt

Mask: SAM 2.1 candidates on two boxes (the best candidate on one box stopped where the light changes),
outer rings only (holes were texture speckle), plus a band to the baseboard line and a corner strip to the
ceiling line; intersected with the wall outline; minus window, stool, nightstand and lamp grown 2 px;
feathered 2 px; saved as a channel. Colour: four approaches (run.yaml), ending with a grey Divide layer
that lifts brightness by the paint-to-paint luminance ratio and an LCh Color layer carrying the swatch.

## Observed

Clary Sage reads sage, Evergreen Fog a deeper grey-green, Goldenrod mustard; the window light, the shade
behind the nightstand and the wall texture survive. Edges at trim, nightstand, baseboard and corner are
clean. A little old wall shows through the stool's leg openings.

## What helped or failed

- GIMP's Multiply/Divide blend in linear light: predictions matched within 1 level.
- Per-channel ratios from the photographed wall carry its warm cast (tan) or explode (blue x15).
- Matching the dim wall's median to a paint chip over-exposes it.
- Anything bright inside the mask (trim edges) glows when the wall is brightened: keep the mask 2 px off
  bright neighbours and feather it.
- `gimp_measure(kind="color")` reads the selected layer, not the composite; `histogram` respects the
  selection, which is how the wall's median was measured through MCP.

## Reusable rule or open question

Recolour a surface by **lightness lift + LCh Color**, with the lift = new paint luminance / old paint
luminance. Open: estimating the old paint colour better than a sampled neutral.

## Whole room (scope widened mid-run)

The first result painted most of the back wall only, and missed its top-right triangle: I had bounded the
wall with a vertical line at the casing's position at floor level, but the camera looks slightly down,
so verticals lean outward toward the top of the frame. Recolouring all three walls with per-wall colour
groups exposed more:

- **Geometry first works better than segmenting walls.** Each wall became a polygon from its real edges
  (corner, ceiling line, baseboard line, the casing's leaning edge), read off gridded renders; Cerebrate
  only supplied what stands in front of the walls (windows with trim, nightstand, lamp, stool).
- **Check coverage before colour.** Overlaying every wall mask on the photo shows gaps instantly. I missed
  the near right wall twice: once because `segment_by_text`'s right-wall instance covered only its top,
  then because the casing candidate in the keep-out spilled over that wall and erased it.
- Per-wall groups make schemes trivial: all Clary Sage, a Goldenrod accent on the back wall, Evergreen Fog
  sides with a Clary Sage back.

Remaining: a hairline of old wall beside the casing crown's left return; walls seen through the stool's
openings keep the old colour.
