> Historical discussion snapshot. See the [current design index](../README.md) for the implemented repository structure and current decisions.

# Unified home server: initial proposal

Date: 2026-09-09
Status: Discussion draft; proposed paths and tools are not deployment decisions.

See the [consolidated platform design](2026-09-09-platform-design.md) for the
current whole-system proposal, including naming and dataset ownership.

The directory and project-ownership proposals below are superseded by the
evolving [repository and storage boundaries](2026-09-09-repository-and-storage-boundaries.md)
note, which consolidates projects and workspaces and replaces staging.

The aim is a personal computing environment whose storage and execution live on
the home server, accessible through laptop IDEs, research tools, agents, TVs, and
travel devices. Begin with one host and a few useful workflows. Preserve the
ability to move a workload to another machine without reorganizing its content.

## What exists

- **Bag of Holding** is an alpha media/gaming architecture with service notes,
  device profiles, runbooks, shell scaffolding, and a ShellCheck workflow. Its
  strongest contracts are immutable ROM masters, validated library promotion,
  private remote access, separate outbound torrent privacy, and replaceable
  clients. The backlog records a first Mega Drive cleanup workflow; most service
  deployment and automation remains planned.
- **Substrate** separates a shared knowledge vault and paper corpus from
  project-specific references, notes, authoring material, and deliverables.
  Phytophany Desktop provides a worked example: linked reference repositories,
  a project manifest, agent roles, research notes, and approved design decisions.
  Code lives in a separate Git workflow. Syncthing markers suggest intended
  client synchronization; they do not establish a current working deployment.
- The supplied Substrate paper corpus and evergreen vault contain no substantive
  files; the workspace template's three top-level files are empty. Paperclip is
  referenced in project documents, but no deployment configuration or runtime
  database is present in this copy. Old absolute paths and identifiers are
  historical context, not verified settings for the new host.
- Neither supplied project directory has a Git repository at its root. This
  review examined local documents and scripts, not the live server or its disks.

The shared idea is already strong: preserve valuable sources, produce useful
outputs, and keep clients and applications replaceable.

## Principles to carry forward

1. Reuse maintained applications and their native interfaces. Write small glue
   only for a demonstrated gap; experiments for fun should have explicit scope.
2. Keep one clear home and owner for each kind of content. Prefer links and
   manifests to duplicate canonical copies.
3. Separate content, application state, and disposable processing outputs.
   **Generated does not mean disposable:** saves, annotations, job history,
   manually edited metadata, and unique agent outputs can be irreplaceable.
4. Keep workloads independent through explicit paths, permissions, and service
   endpoints. Each application owns its database; avoid direct database coupling.
5. Document a manual path before automating it. Every deployed service needs a
   version, state locations, health check, backup/restore procedure, and rollback.
6. Prefer a supported single-host setup initially. Add machines when a measured
   storage, compute, availability, or isolation requirement justifies them.

## Repository and live storage are different things

Proposed infrastructure repository:

```text
home-server/                 # small, versioned infrastructure repository
  design-notes/              # proposals and accepted decisions
  services/                  # per-application deployment config and examples
  hosts/                     # hardware inventory and role/path assignments
  agents/                    # shared authored definitions, prompts, workflows
  scripts/                   # small operational helpers
  runbooks/                  # setup, verification, recovery, client setup
```

Application source repositories remain independent. Secrets, live databases,
media, model weights, and the research corpus stay outside this repository.
Project-specific agent instructions belong with their project; shared defaults
belong here. Avoid maintaining two competing copies of definitions in Git and
Paperclip: decide which settings are versioned and which are application-owned.

Illustrative live storage, following Bag of Holding's stable `/mnt/` preference:

```text
/mnt/home-server/           # logical view; physical mounts still to be designed
  media/                   # libraries, preserved ROM masters, saves
  substrate/               # papers, evergreen vault, non-code project hubs
  workspaces/              # independent Git checkouts and agent worktrees
  models/                  # shared model weights; custom weights are valuable
  state/<service>/         # durable databases and other application state
  cache/<service>/         # demonstrably rebuildable indexes and caches
  staging/<domain>/        # imports, quarantine, scratch processing
```

These names describe ownership, not a requirement for separate disks or
partitions. Torrent staging and media destinations must share a filesystem for
hardlinks; container mount arrangements must preserve that relationship. Keep
databases on suitable local storage initially. Missing required storage should
prevent dependent services from starting and filling the OS disk instead.

Backups need an independent destination, with an off-host copy for valuable data.
A `backups/` directory on the same disk is only a convenience or intermediate
export location. Keep secrets recoverable through a separate protected procedure.

## Major design areas

| Area | Proposed direction | Boundary to preserve |
| --- | --- | --- |
| Access and networking | Retain private remote access through Tailscale; SSH for remote work, application clients for media/research. Keep Pi Zero DNS independent if retained. | Outbound torrent VPN and remote access remain separate. Application and filesystem permissions still matter inside the private network. |
| Deployment | Small Docker Compose stacks for suitable server apps; native/systemd services for host integration or hardware-facing tools where simpler. Pin versions and upgrade deliberately. | No application should require the entire platform to be restarted or upgraded with it. Validate ARM support and actual resource needs before selecting a Pi deployment. |
| Media and games | Preserve canonical media, ROM masters, curated outputs, and independent saves. Reuse the existing Kodi/Jellyfin, library-manager, and ROM-tool direction incrementally. | Viewers see promoted libraries. Begin with a manual validation/import path; resolve automated import gating before enabling unattended imports. |
| Research | Retain papers, portable notes, project hubs, and source references. Choose ownership of citation metadata and attachments before importing a large corpus. | Search/indexing is a consumer of canonical material. Preserve annotations and hand-edited metadata even when stored in an application's database. |
| Remote development | Laptop IDE connects to server workspaces; each agent job gets its own worktree or checkout. Link non-code project hubs to code using lightweight manifests. | Do not place every codebase inside the infrastructure repository. Committed Git history can live upstream; uncommitted server work still needs backup. |
| Agent orchestration | Use Paperclip for coordination, with a small initial workflow and scoped credentials. Put retained outputs in the relevant project; protect Paperclip state separately. | Files and Git remain usable without Paperclip. Worktrees prevent editing collisions but do not provide security isolation; use restricted execution environments for agent tools. |
| Shared compute | Add inference as a replaceable service endpoint, backed by shared model storage where appropriate. Later assign heavy inference, transcoding, and emulation to a capable node. | Clients depend on configured interfaces, not a particular machine name or an orchestrator's private directories. |
| Operations | Basic disk/service/backup health checks, bounded logs, deliberate upgrades, and tested recovery. Prioritize notes, papers, project work, saves, credentials, and valuable service state. | Restore must work without agents; media volume and replaceability should determine its separate backup policy. |

Compose provides an existing model for services, networks, configuration, and
volumes; the per-stack approach above is our proposed use of it, not an upstream
requirement. See [Docker's application model](https://docs.docker.com/compose/intro/compose-application-model/).
Paperclip describes itself as an agent orchestration application with task,
coordination, and cost-management capabilities; exact deployment and runner
choices still require evaluation. See [the upstream repository](https://github.com/paperclipai/paperclip).

Selective offline clients are part of this design. Use Git for code exchange,
explicit synchronization for selected notes/documents, and curated copies for
travel media. Define save and note conflict behavior before bidirectional sync.
Do not synchronize live application databases as ordinary files. Synchronization
also does not replace backup: [Syncthing's FAQ](https://docs.syncthing.net/users/faq.html)
explicitly distinguishes them.

## Stages and evidence of completion

1. **Foundation plus two useful workflows.** Inventory `overmind-01`, actual
   storage, current services, and valuable data. Agree on paths, ownership,
   private access, and backup destination. Demonstrate laptop remote editing of
   one project, playback of one canonical media/ROM set, and restoration of a
   project file, a save, and representative service state. This proves the merged
   architecture serves work and leisure from the beginning.
2. **Repeatable daily use.** Make the validated deployments reproducible; add
   research capture and selected client sync, media/ROM import procedures, and
   minimal health reporting. Demonstrate a repeatable import and recovery for
   each enabled domain before broadening automation.
3. **One bounded agent workflow.** Run one Paperclip project against a dedicated
   checkout, with scoped access, cost/concurrency limits, retained outputs, and
   human review. Verify ordinary development still works when orchestration is
   stopped. Restore its valuable state before expanding the agent team.
4. **Expand on demand.** Add richer search, local inference, game streaming,
   larger storage, or a compute node when real usage motivates it. Demonstrate
   migration of one service while preserving content and client access contracts.

## Follow-up decisions

Recommended order for individual design discussions:

1. Current hardware/storage inventory, ownership, canonical paths, and recovery.
2. Deployment convention and host roles, including whether the Pi remains both
   server and local gaming frontend.
3. Client behavior: remote work versus offline replicas; note and save conflicts.
4. Research capture, citation/attachment ownership, and project-to-repo links.
5. Paperclip deployment, runner isolation, credentials, and output retention.
6. Media import gating, hardlinks, ROM curation, and travel selection.

Implementation observations to carry forward: Bag of Holding's `.gitignore`
currently ignores all `*.md` files, including documentation; its setup script
recursively applies shared media permissions; backup and health scripts are
scaffolds, not reliable evidence of successful recovery or overall health. These
need correction before reuse. The referenced ingestion worker does not exist.
No existing files, services, permissions, or storage paths were changed by this
proposal.
