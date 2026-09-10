# Overmind

A reproducible personal computing environment for remote development, research,
agents, media, and games. **Overmind** names the repository, its host pattern
(`overmind-01`, `overmind-02`), and the acting intelligence. **Substrate** is the
optional collaborative work surface. **Library** is the passive archive, and
**Inbox** is the universal loading dock drained by Overmind.

## Current status

**Status:** PARTIAL — see [status legend](design-notes/README.md#status-legend).
This is a first-pass repository scaffold, not a working installer. The current
host is a Raspberry Pi 4 with a fresh Ubuntu Server 26 LTS install, a 128 GB
microSD, and a 2 TB SSD, as reported by its owner. Hardware details, mount layout,
and deployed services have not been verified from this repository.

Start with [the design index](design-notes/README.md),
[overmind-01](hosts/overmind-01/README.md), and the [backlog](TODO.md).

```text
overmind/
  AGENTS.md                 # contributor and coding-agent instructions
  design-notes/             # decisions, proposals, historical discussion
  hosts/overmind-01/        # host inventory and example path configuration
  services/                 # service plans, configuration examples, helpers
  agents/                   # shared agent behavior and ownership conventions
  scripts/                  # repository checks and operational entry points
  runbooks/                 # rebuild, recovery, imports, clients, romset workflows
```

## Filesystem contract

| Location | Purpose |
| --- | --- |
| `/opt/overmind` | Proposed deployed infrastructure checkout |
| `/etc/...` | Installed host/service configuration at native paths |
| `/mnt/substrate` | Work surface: projects, notes (including agent knowledge), papers, datasets, models |
| `/mnt/library` | Passive archive: movies, TV, ROMs, other media |
| `/var/spool/overmind` | Inbox with `documents/`, `media/`, and `torrents/` intake |
| Each service's own defaults | Private state/cache; exact paths documented per service and optionally SSD-backed |

These are logical paths, not a partition plan. Substrate does not encompass the
whole SSD, and neither does Library. Projects own all their working material, including rough notes;
other source repositories remain independent. Private service internals stay
outside Substrate. See [storage and ownership](design-notes/storage-layout.md).

## Working here

```sh
./scripts/check-repo
./scripts/bootstrap --plan
```

The repository check validates local links, JSON examples, shell syntax, and
ShellCheck when installed. CI requires ShellCheck. The bootstrap plan only prints
remaining setup work. Backup and restore entry points are explicit, non-mutating
placeholders pending a tested recovery design.

On a configured Linux host, `scripts/health-check` checks explicitly named systemd
units and optional mounts; see `scripts/health-check --help`. Use repeated
`--mount` options for the mounts required by the selected services. It is not a complete health assessment
and does not assume every planned application is installed.

## Principles

- Reuse maintained tools; automate small, understood procedures.
- Keep ownership, permissions, dependencies, and recovery explicit.
- Treat incoming content as untrusted and preserve canonical sources.
- Keep remote access private; torrent egress privacy is a separate concern.
- Keep secrets and payloads outside this Git repository.
- Document decisions during development and grow from tested workflows.

Reproduction combines **this repository + protected secrets + content/state
backups**. Begin with private access, storage/recovery, one remote project, and
one media workflow; then expand daily use, agent orchestration, and compute.

This project succeeds the Bag of Holding scaffold and the earlier Substrate
research design. See [first-pass migration](design-notes/2026-09-09-repository-first-pass.md).
