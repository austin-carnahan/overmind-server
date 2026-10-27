# Room V1 capstone

Thirteen decorating experiments on the bedroom scene (E01–E13), run first by Claude Code and then,
for a representative subset, by Buckminster, with the same skills and starting conditions. The
experiments are defined in [experiments.yaml](experiments.yaml); the reasoning and per-experiment
detail are in [plan.md](plan.md). This folder is the authoritative record.

## Where things live

| What | Where |
| --- | --- |
| Definitions, plan, asset provenance, run records (`run.yaml`, `notes.md`) | here, in git |
| Reference scene `bedroom-v1.xcf` (never modified by a run) | `~/DesignStudio/workspaces/bedroom/` (hash in [assets/manifest.yaml](assets/manifest.yaml)) |
| Downloaded assets (originals, never edited) | `~/DesignStudio/workspaces/room-v1-capstone/assets/` |
| Run outputs (working XCF, before/clean/annotated renders) | `~/DesignStudio/workspaces/room-v1-capstone/runs/<run_id>/` |
| Shared skills | [`.claude/skills/gimp`](../../.claude/skills/gimp/SKILL.md), [`.claude/skills/interior-scene-editing`](../../.claude/skills/interior-scene-editing/SKILL.md) |
| Tool contracts (Cerebrate, `overmind-*`) | [`services/design-studio/buckminster/cerebrate-gimp.md`](../../services/design-studio/buckminster/cerebrate-gimp.md) |
| Earlier bedroom experiments (1–4) | [`models/field-notes.md`](../../models/field-notes.md) |

## A run

1. Copy the reference scene into the run's DesignStudio folder; never open the reference for editing.
2. Copy [`runs/_template/`](runs/_template/) to `runs/<YYYY-MM-DD>_<EXX>_<agent>_<slug>/`, fill the
   header (agent, model, skill revision, capabilities, inputs) and set `status: running`.
3. Work. Record every interface used, and for each step that needed something Buckminster doesn't
   have: the capability, why it was preferable, whether existing MCP operations or a small primitive
   could do it, and the tradeoffs. Keep **what was achieved** separate from **what it required**.
4. Save the XCF and renders, set the status (`pass` / `partial` / `fail` / `blocked`), write `notes.md`.
5. If the run taught a reusable technique or rule, update the skill in a focused commit and list it
   under `skill_updates`. Measurements, screenshots and trial history stay in the run, not the skill.

Buckminster's environment: the GIMP Agent MCP (38 tools), Cerebrate (9 tools), Overmind's `overmind-*`
GIMP procedures, workspace files and memory, `view_image`, `file_fetch`, and a non-sudo shell on
Overmind (not on the Mac that runs GIMP). Claude Code has the same MCP tools plus its development
environment (shell and Python on the Mac, including direct bridge access). Neither is restricted to
match the other; the records show what each needed.

## Comparison protocol

1. **Exploratory (Claude Code).** Runs may update the skills. Each update is its own commit, so every
   run's `skills.revision` identifies exactly what it saw.
2. **Freeze.** Tag the skills to compare: `git tag skills-baseline-1 <commit>`. Record the tag here.
3. **Baseline replay.** Both agents run the same subset (from `experiments.yaml`) from the same pinned
   scene and assets, with the tagged skills, `condition: baseline`. Don't fold new findings into the
   skills between the two agents' baseline runs.
4. **Compare.** Attribute differences carefully: missing skill knowledge vs tool access vs planning vs
   visual judgment vs execution. Use the `beyond_buckminster` entries.
5. **Revise.** Improvements come after the baseline, as a new tag; reruns with them are
   `condition: revised-skill`.

**Installing a pinned revision for an agent:** export the tagged skills into a read-only directory,
e.g. `git archive skills-baseline-1 .claude/skills | tar -x -C <dir>`, and point the agent at that
copy, not at a working tree that keeps changing. Claude Code reads `.claude/skills/` of the checkout it
runs in: for a baseline run, check out the tag (a worktree) and open that. For Buckminster, the skills
go into its OpenClaw workspace (its `skills/` directory; confirm OpenClaw's skill loading on that
install), with the tool-contract adapter linked as today by `install-buckminster-cerebrate-runbook`.

Frozen revisions: none yet.
