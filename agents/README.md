# Shared agent behavior

Status: ownership convention and v1 design; no orchestrator configuration or
live shared-notes integration is deployed.

This directory is for versioned bootstrap instructions or shared workflow
definitions that Overmind deploys. Add them when a concrete workflow exists;
do not scaffold a large agent organization. Project-specific instructions,
working notes, and retained outputs belong with the project.

Reusable observations, patterns, and user-confirmed preferences are collaborative
knowledge. The [minimal shared-notes design](../design-notes/agent-notes-v1.md)
places those under `/mnt/substrate/notes/agents`, with candidates in
`/var/spool/overmind/documents/agent-notes`. This directory does not contain
the live knowledge collection.
The proposed `/mnt/substrate/AGENTS.md` provides short surface guidance and points
to the index; each runner must be explicitly connected to that entry point.

## OpenClaw agent skills

**Rule (2026-11-02): every skill an agent uses is in git, or can be rebuilt
from git.** Agents get procedures and tool knowledge as skills, never as
workspace runbooks. (The repository's top-level `runbooks/` is documentation
for the human operator.)

| Kind | Lives in | Reaches the agent |
| --- | --- | --- |
| Ours, for every agent | [`skills/`](skills/) | `skills.load.extraDirs: ["/opt/overmind/agents/skills"]` |
| Ours, for one agent | `<agent>/skills/<name>/` | symlinked into `<workspace>/skills/` |
| Third-party | `<agent>/skills-lock.json` | restored into `<workspace>/.agents/skills/` from upstream |
| Written by the agent | its Skill Workshop (`~/.openclaw/agents/<id>/agent/workshop-skills/`) | directly; not in git |

[`install-agent-skills <agent>`](install-agent-skills) does the linking and
restoring for one agent (it runs as `openclaw`; idempotent). A `git pull` of
`/opt/overmind` then updates our skills with no re-install. OpenClaw follows
the symlinks because `/opt/overmind/agents` is in
`skills.load.allowSymlinkTargets`.

**Current skills:**

- [`skills/skill-discovery`](skills/skill-discovery/SKILL.md), every agent:
  find and evaluate skills on skills.sh; install only with the user's
  approval, into the requesting agent's workspace. See
  [Skills catalog](../runbooks/openclaw/agents-and-model-routing.md#skills-catalog-skillssh).
- [`buckminster/skills/`](buckminster/skills/): `gimp` and
  `interior-scene-editing` (developed in the
  [Room V1 capstone](../experiments/room-v1-capstone/README.md); in
  `.claude/skills/` until 2026-11-02), `gimp-worker`, `cerebrate-gimp`,
  `sweethome3d`, `design-python`, `reference-research`. Third-party:
  `interior-design-expert` ([lock](buckminster/skills-lock.json)), and
  `composio-cli`, which the Composio CLI generates rather than skills.sh
  (regenerate it with `composio setup skill codex` into a scratch `HOME`, and
  copy `.agents/skills/composio-cli` into the workspace's `.agents/skills/`).
- [`soma/skills/`](soma/skills/): `garmin-workouts`.

**Writing and changing them:**

- Names must be unique: a same-named skill in a higher-precedence place
  silently wins (`agents/skills/` is OpenClaw's lowest precedence).
- Quote `description:` in the frontmatter when it contains `: `; OpenClaw is
  lenient, strict YAML parsers aren't.
- Update from evidence (a run in `experiments/`, `models/field-notes.md`, an
  agent's report), in focused commits. Mark techniques **[demonstrated]** or
  **[experimental]** where the skill uses those labels; measurements and trial
  history stay in the run record.
- Agents read these skills but don't edit them. A lesson an agent learns goes
  to the user or its Skill Workshop, and the operator folds it in here.
- **Skill Workshop skills are an inbox.** When one proves useful, review it
  and move it into `<agent>/skills/` (current candidates: Soma's four Garmin
  skills, Kerrigan's three).
- `buckminster/skills/gimp` is adapted from an upstream project: record
  upstream changes you adopt in its `UPSTREAM.md`, and keep its LICENSE and
  NOTICE.
- After approving a third-party install, copy the agent's updated
  `<workspace>/skills-lock.json` into `<agent>/skills-lock.json` and commit it.
  Restores fetch upstream's current version, so re-read a skill after
  restoring if its upstream may have changed.

The repository's [AGENTS.md](../AGENTS.md) governs infrastructure work.
[services/paperclip](../services/paperclip/README.md) describes the orchestrator's
proposed deployment. Its private database/history remains outside Substrate.

The first workflow needs a scoped project/checkout, execution isolation,
credentials, cost/concurrency limits, review, and output retention. Worktrees
separate edits but do not enforce permissions. Avoid duplicating live UI-owned
configuration in hand-maintained files; use supported exports where appropriate.
