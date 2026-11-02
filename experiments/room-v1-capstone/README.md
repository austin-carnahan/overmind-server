# Room V1 capstone

Thirteen decorating experiments on the bedroom scene (E01–E13), run by Claude Code to develop the
shared GIMP skills. The experiments are defined in [experiments.yaml](experiments.yaml); the reasoning and per-experiment
detail are in [plan.md](plan.md). This folder is the authoritative record.

**Status (2026-10-27):** all 13 experiments run by Claude Code; summary in [DIGEST.md](DIGEST.md).
A planned baseline replay by Buckminster, comparing the two agents on frozen skills, was dropped on
2026-11-02 for simplicity: the skills stay live, and Buckminster loads them directly from this
repository.

## Where things live

| What | Where |
| --- | --- |
| Definitions, plan, asset provenance, run records (`run.yaml`, `notes.md`) | here, in git |
| Reference scene `bedroom-v1.xcf` (never modified by a run) | `~/DesignStudio/workspaces/bedroom/` (hash in [assets/manifest.yaml](assets/manifest.yaml)) |
| Downloaded assets (originals, never edited) | `~/DesignStudio/workspaces/room-v1-capstone/assets/` |
| Run outputs (working XCF, before/clean/annotated renders) | `~/DesignStudio/workspaces/room-v1-capstone/runs/<run_id>/` |
| Shared skills | [`.claude/skills/gimp`](../../.claude/skills/gimp/SKILL.md), [`.claude/skills/interior-scene-editing`](../../.claude/skills/interior-scene-editing/SKILL.md) |
| Tool contracts (Cerebrate, `overmind-*`) | [`services/design-studio/buckminster/skills/cerebrate-gimp/SKILL.md`](../../services/design-studio/buckminster/skills/cerebrate-gimp/SKILL.md) |
| Earlier bedroom experiments (1–4) | [`models/field-notes.md`](../../models/field-notes.md) |

## A run

1. Copy the reference scene into the run's DesignStudio folder; never open the reference for editing.
2. Copy [`runs/_template/`](runs/_template/) to `runs/<YYYY-MM-DD>_<EXX>_<agent>_<slug>/`, fill the
   header (agent, model, skill revision, capabilities, inputs) and set `status: running`.
3. Work. Record every interface used, and for each step that needed something Buckminster doesn't
   have: the capability, why it was preferable, whether existing MCP operations or a small primitive
   could do it, and the tradeoffs. Keep **what was achieved** separate from **what it required**.
4. Save the XCF and renders, set the status (`pass` / `partial` / `fail` / `blocked`), write `notes.md`.
   Up to five attempts per experiment, numbered in `run.yaml`; check coverage (overlay masks on the photo)
   before judging results.
5. **Stop:** show the results with your own evaluation and a recommendation, open the run's XCF in GIMP,
   and wait for confirmation before the next experiment.
6. If the run taught a reusable technique or rule, update the skill in a focused commit and list it
   under `skill_updates`. Measurements, screenshots and trial history stay in the run, not the skill.

Buckminster's environment: the GIMP Agent MCP (38 tools), Cerebrate (9 tools), Overmind's `overmind-*`
GIMP procedures, workspace files and memory, `view_image`, `file_fetch`, and a non-sudo shell on
Overmind (not on the Mac that runs GIMP). Claude Code has the same MCP tools plus its development
environment (shell and Python on the Mac, including direct bridge access). Neither is restricted to
match the other; the records show what each needed.

## Revisit later

Experiments closed short of good enough, kept for a later enhancement pass:

| Run | Status | What would improve it |
| --- | --- | --- |
| [E03 material replacement](runs/2026-10-27_E03_claude-code_pattern/run.yaml) | partial (accepted 2026-10-27) | The print doesn't follow the folds: a displace-by-map operation (shading as the map) — `gegl:displace` needs an aux input `gimp_apply_filter` can't pass. Also the faint face line and the rim at the blanket edge. |
| [E05 simulated rotation](runs/2026-10-27_E05_claude-code_rotation/run.yaml) | pass for solid furniture (accepted 2026-10-27) | The bed's near corner where the hanging blanket crosses the box edge; pillows for the −90° variant; a quad-to-quad warp or "rotate box on floor" primitive so an MCP-only agent can do C3D. |
| [E06 perspective warping](runs/2026-10-27_E06_claude-code_perspective/run.yaml) | pass (accepted 2026-10-27) | Re-place the curtains with the window's measured W/H (1.57, found in E08) instead of the guessed 1.3. |
| [E13 camera shift, v3](runs/2026-10-27_E13v3_claude-code_corrected-camera/run.yaml) | v2 partial; v3 the final pass (2026-10-27) | v3 fixed v2's list (camera re-derived, view inside the room, door at the corner, fan as a sprite). Left: the bed's edge-on side and slab-like foot, the stretched doorway interior, flat right-wall paint. |
