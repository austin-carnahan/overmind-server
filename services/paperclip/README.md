# Paperclip

Status: planned; no deployment, database, or agent organization is configured.

Coordinate one bounded project workflow first. The old Substrate work contains
examples of project briefs, decisions, and agent roles; its identifiers and
absolute paths are historical, not configuration for this instance.

Content: scoped projects under `/mnt/substrate/projects` when attached. Working notes,
code changes, and retained outputs belong to those projects. Shared authored
behavior belongs in [agents](../../agents/README.md).

When configuring the first runner, explicitly connect it to the proposed
Substrate instruction/index paths in [shared agent notes v1](../../design-notes/agent-notes-v1.md).
The live knowledge collection is Substrate content, not Paperclip runtime state.

Private task history, approvals, execution state, and database files belong at
supported service paths outside Substrate, backed by SSD if useful. Back them up
consistently. Multiple instances must use the owning service's interface rather
than opening its live database concurrently.

Before deployment: select/verify upstream installation and runner methods on this
Pi; document native state paths, credentials, execution isolation, worktrees,
limits, review, health checks, state restore, and rollback. Demonstrate ordinary
project work and host administration without Paperclip running.
