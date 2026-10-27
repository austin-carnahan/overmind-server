# P0 — HUD check (2026-10-26_P0_claude-code_hud-check)

## Attempt

A scratch copy of `bedroom-v1.xcf`; an "EXPERIMENT HUD (exclude from inference/export)" group at the top
with a dark 72%-opacity backing and two text layers (title, status), all through GIMP MCP tools. Then a
clean export with the group hidden, and three `overmind-publish` snapshots of the top-left region: HUD
visible, HUD hidden, and `source=Room`.

## Observed

The panel is legible in the annotated render. The clean export has none of it. The canvas snapshot with
the HUD visible contains it (253,569 px differ from the clean scene in that region); hidden or
`source=Room`, 0 px differ.

## What helped or failed

`gimp_layer(action="new")` lands at the top level; the backing and text layers need a `reorder` into the
group. A status update is one `gimp_text(layer_id=…, text=…)` call.

## Reusable rule or open question

Hide the HUD (or publish a specific group) before anything goes to Cerebrate and before clean exports.
A snapshot taken with the HUD visible would show the title to the models.
