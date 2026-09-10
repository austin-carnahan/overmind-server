# Design notes

These documents describe the current Overmind design. Target paths are agreed
as the design direction; physical mounts and deployments have not been executed.

## Status legend

Every design/runbook/service doc opens with one badge instead of restating the
same caveats:

- **PROPOSED** — design agreed; nothing implemented or verified on a live host.
- **PARTIAL** — some facts/pieces are verified; the rest is still PROPOSED.
- **DEFERRED** — intentionally not pursued yet; revisit only when justified.
- **HISTORICAL** — a record of past discussion; superseded by current docs.

A badge may add one short clause for a detail specific to that doc, but should
not restate what the label already means.

- [Architecture and stages](architecture.md)
- [Storage, ownership, and physical placement](storage-layout.md)
- [Surface and intake refinement](2026-09-09-surface-layout-refinement.md)
- [Shared agent notes — minimal v1](agent-notes-v1.md)
- [Networking](networking.md)
- [Security boundaries](security-model.md)
- [Future compute roles](future-compute.md)
- [Repository first-pass changes](2026-09-09-repository-first-pass.md)

The [host inventory](../hosts/overmind-01/README.md) separates reported hardware
from unverified details. Service plans live under [services](../services/README.md).
Operational procedures live under [runbooks](../runbooks/README.md).

## Discussion history

These snapshots explain the design's evolution; their old names, paths, and
proposals are not current deployment instructions:

- [Initial merger proposal](history/2026-09-09-unified-home-server-proposal.md)
- [Repository and storage discussion](history/2026-09-09-repository-and-storage-boundaries.md)
- [Consolidated discussion before scaffolding](history/2026-09-09-platform-design.md)

Record future decisions here with status, rationale, consequences, and verification
needed. Update the current documents when a decision supersedes them.
