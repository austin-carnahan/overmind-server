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

## Shared OpenClaw skills

[`skills/`](skills/) holds Overmind-owned skills that every OpenClaw agent
loads: the Gateway's `skills.load.extraDirs` points at
`/opt/overmind/agents/skills`. They change only when this repository is
committed and pulled on the server. Since 2026-11-01:

- [`skill-discovery`](skills/skill-discovery/SKILL.md): find and evaluate
  skills on skills.sh; install only with the user's approval, into the
  requesting agent's workspace. See
  [Skills catalog](../runbooks/openclaw/agents-and-model-routing.md#skills-catalog-skillssh).

Extra directories have the lowest precedence in OpenClaw, so a same-named
skill anywhere else overrides one here. Give these skills unique names.

The repository's [AGENTS.md](../AGENTS.md) governs infrastructure work.
[services/paperclip](../services/paperclip/README.md) describes the orchestrator's
proposed deployment. Its private database/history remains outside Substrate.

The first workflow needs a scoped project/checkout, execution isolation,
credentials, cost/concurrency limits, review, and output retention. Worktrees
separate edits but do not enforce permissions. Avoid duplicating live UI-owned
configuration in hand-maintained files; use supported exports where appropriate.
