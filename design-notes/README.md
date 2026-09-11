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

## Forward-looking research (beyond the current build-out)

These describe possible future direction — agent orchestration and deeper
media/ROM automation — written before basic storage, ingestion, and the media
pipeline exist. They are not a commitment to build any of this next, and they
do not override the current documents above when they conflict. Get the basic
media pipeline and ingestion actually working first; revisit these once that's
true.

- [Product thesis and architectural principles](Overmind — Product Thesis and Architectural Principles.md) —
  broader project vision; the current documents above are the maintained,
  load-bearing version of what it describes.
- [Agent orchestration & human review: open-source landscape](overmind_agent_orchestration_research.md) —
  research concluding Paperclip already implements most of the originally
  proposed custom review-inbox design; recommends piloting Paperclip on one
  small, generic, reversible task before any media-specific integration.
- [Agent orchestration and review inbox](Overmind — Agent Orchestration and Review Inbox.md) —
  the original custom-inbox proposal; superseded by the research above as a
  build commitment, kept as a requirements reference.
- [Agentic media & ROM automation design](Overmind — Agentic Media & ROM Automation Design.md) —
  a phased plan where Paperclip only enters after Sonarr/Bazarr/Transmission
  and a bounded agent API already exist; those phases are themselves blocked
  on the SSD today.
- [Substrate standards research](substrate_standards_research.md) — research
  on a portable, agent/tool-agnostic project-context convention.

## Discussion history

These snapshots explain the design's evolution; their old names, paths, and
proposals are not current deployment instructions:

- [Initial merger proposal](history/2026-09-09-unified-home-server-proposal.md)
- [Repository and storage discussion](history/2026-09-09-repository-and-storage-boundaries.md)
- [Consolidated discussion before scaffolding](history/2026-09-09-platform-design.md)

Record future decisions here with status, rationale, consequences, and verification
needed. Update the current documents when a decision supersedes them.
