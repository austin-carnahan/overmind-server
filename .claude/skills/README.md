# Shared agent skills

| Skill | For |
| --- | --- |
| [gimp](gimp/SKILL.md) | General GIMP technique through the GIMP Agent MCP tools; any GIMP project |
| [interior-scene-editing](interior-scene-editing/SKILL.md) | Room photos as layered scenes: objects, protection, surface reconstruction, placement, shadows |

Both are plain `SKILL.md` folders (frontmatter `name` + `description`, linked references loaded on
demand), meant for any agent with the GIMP and Cerebrate MCP tools: Claude Code reads them from this
directory; Buckminster gets the same content in its OpenClaw workspace
([comparison protocol](../../experiments/room-v1-capstone/README.md#comparison-protocol)). Call
contracts for Cerebrate and Overmind's GIMP procedures stay in
[`services/design-studio/buckminster/cerebrate-gimp.md`](../../services/design-studio/buckminster/cerebrate-gimp.md),
not in the skills.

## Maintaining them

- General GIMP knowledge goes in `gimp`; anything specific to rooms and furniture in
  `interior-scene-editing`.
- Update from evidence: a run in `experiments/` (or `models/field-notes.md`) that showed the technique.
  Label it **[demonstrated]** or **[experimental]**, keep its limits, and link nothing longer than a rule;
  measurements and trial history stay in the run record.
- Focused commits, one change each, so a run's `skills.revision` says exactly what it saw. Don't
  rewrite a skill wholesale after an experiment.
- Steps that need more than the shared MCP tools (scripts, direct bridge access, image arrays) are
  marked **[gap]** or described as environment-dependent alternatives, never as universal steps.
- Before a comparison, freeze a revision with a git tag and install that exact content for each agent.
- `gimp` is adapted from an upstream project: record upstream changes you adopt in
  [gimp/UPSTREAM.md](gimp/UPSTREAM.md), and keep its LICENSE and NOTICE.

## Claude Code notes

- Project skills load from `.claude/skills/` of the folder Claude Code is opened on (here: the
  overmind-server checkout). Ask for one by name (`/gimp`, `/interior-scene-editing`) or let the
  description match.
- The MCP servers are registered per user, not in this repository (local scope in `~/.claude.json`):
  `gimp` runs `uvx --from gimp-agent-mcp==0.5.0 gimp-agent-mcp serve` with `GIMP_AGENT_ALLOW_PYTHON=0`
  (the same server and settings as Buckminster's), and `cerebrate` is
  `http://127.0.0.1:18002/mcp` through an SSH tunnel to Overmind's loopback-only endpoint
  (`ssh -N -L 127.0.0.1:18002:127.0.0.1:8002 overmind-01`).
