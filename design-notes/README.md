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
- [ROM & emulator design brief](overmind_rom_emulator_design_brief.md) —
  adopted architecture for the ROM pipeline and Fire TV client (ROMarr, Igir,
  SMB, R-Shop, RetroArch, Syncthing-Fork); tool names verified real before
  adoption. DEFERRED overall (nothing built yet) — see
  [runbooks/clients/fire-tv.md](../runbooks/clients/fire-tv.md) for the
  summary and current status.
- [Home DNS + reverse-proxy plan](2026-09-15-home-dns-reverse-proxy-plan.md) —
  step-by-step plan for readable `home.arpa` names on both LAN and Tailscale,
  covering AdGuard rewrites on Cerebrate and host-local Caddy on Cerebrate and
  Overmind. PROPOSED (plan only, nothing executed).
- [Pixel 6 inference node](2026-09-16-pixel6-inference-node.md) — staged
  plan converting a factory-reset Pixel 6 into an always-on inference node
  (second "cerebrate" fleet member); Stage 1 (ADB baseline +
  appliance-readiness) done, Stages 2-4 pending. See
  [hosts/cerebrate-pixel6](../hosts/cerebrate-pixel6/README.md).
- [Cerebrate Pixel 6 — Multi-Runtime Execution Plane](Cerebrate%20Pixel%206%20%E2%80%94%20Multi-Runtime%20Execution%20Plane.md) —
  next-phase plan evolving `cerebrate-infer` from a single-purpose
  classifier into a general Android execution plane (bounded Graph
  Execution via NNAPI/TFLite, stateful Session Execution via LiteRT-LM).
  Feasibility spike done: native runtime, model, and backend gates all
  passed. Five-phase implementation not yet started.
- [Romset curation pipeline](romset-curation-pipeline.md) — archive tier →
  library tier curation design: ScreenScraper hash identification across the
  full archive, ranked candidates enriched with a second IGDB rating, and a
  Bayesian combined score selecting the top ~100 per platform. PROPOSED
  (design agreed, nothing implemented). Answers the open "Curation
  strategies" question in
  [runbooks/romsets/igir.md](../runbooks/romsets/igir.md#curation-strategies-archive--library).
- [Seerr & Maintainerr setup brief](overmind_seerr_maintainerr_setup_brief.md) —
  adopted architecture for the request/discovery and retention/cleanup
  layers on top of Jellyfin/Radarr/Sonarr; both tools verified real before
  adoption. PROPOSED (not yet deployed) — see
  [services/seerr](../services/seerr/README.md) and
  [services/maintainerr](../services/maintainerr/README.md).

The [host inventory](../hosts/overmind-01/README.md)
(also: [cerebrate-pi0](../hosts/cerebrate-pi0/README.md),
[cerebrate-pixel6](../hosts/cerebrate-pixel6/README.md)) separates reported hardware
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
- [Overmind operating model](overmind_operating_model_design_plan.md) — a
  full future operating model (project lifecycle stages, indexing, code
  intelligence, a "Kerrigan" resident-operator role, a chief-of-staff routing
  agent, human-facing board views). Most of it is deferred, same as the rest
  of this section — but its Paperclip execution-seam principle (Workstream E)
  is adopted now, see [services/paperclip/README.md](../services/paperclip/README.md#work-item-convention).
  Its intake-pattern principle (Workstream B) validates the existing
  [ingestion](../services/ingestion/README.md) design rather than changing
  it; ignore this doc's `/incoming/...` path examples, which don't match and
  aren't a rename to make.

## Discussion history

These snapshots explain the design's evolution; their old names, paths, and
proposals are not current deployment instructions:

- [Initial merger proposal](history/2026-09-09-unified-home-server-proposal.md)
- [Repository and storage discussion](history/2026-09-09-repository-and-storage-boundaries.md)
- [Consolidated discussion before scaffolding](history/2026-09-09-platform-design.md)

Record future decisions here with status, rationale, consequences, and verification
needed. Update the current documents when a decision supersedes them.
