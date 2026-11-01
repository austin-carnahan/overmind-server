# Overmind Agent Ecosystem — Technical Design & Expansion Roadmap

**Status:** PROPOSED (working design / implementation handoff). Baseline facts in §3 are verified as of 2026-11-01.  
**Version:** 1.0  
**Date:** 2026-11-01  
**Primary system:** Overmind (self-hosted agent environment)  
**Audience:** Kerrigan, future implementation agents, and human operator  
**Related:** [Design Studio environment report](agentic-design-studio-environment.md) · [Remote workers](remote-workers.md) · [Design Studio service](../services/design-studio/README.md) · [Agents and model routing](../runbooks/openclaw/agents-and-model-routing.md)

> **Purpose.** This document freezes the currently agreed direction for Overmind's agent ecosystem. It is a roadmap and an implementation handoff, **not** a claim that the proposed integrations are already deployed. The immediate work is Buckminster's external design research and 3D modeling capabilities, followed by the cross-domain Coach and shared knowledge/data/visualization foundation. Other agents extend the same infrastructure. Treat model/harness optimization as iterative maintenance, not a blocking prerequisite.

## 1. Executive summary

Overmind will be a **modular, persistent multi-agent environment** for personal assistance, behavior support, design, research, coding, and business operations. Agent identities and durable outputs survive replacements of models, harnesses, chat clients, and third-party services. Prefer mature CLIs, APIs, MCP adapters, and existing software over building a monolithic proprietary agent framework.

**Agreed implementation order:**

1. **Buckminster design expansion:** Pinterest access and reference discovery; evaluate Composio and Bright Data; test an editable 3D modeling workflow and complete a design handoff.
2. **Cross-domain Coach MVP:** persistent private coaching context; a lightweight goals/progress ledger; opt-in interactive accountability; pilot Logseq for knowledge; start a shared visualization layer.
3. **Personal ecosystem:** executive assistant (name shortlist: **Hermes, TARS, Finch**), Soma, and Saffron, reusing access channels and data services.
4. **Professional ecosystem:** dedicated coding, research, and business specialists coordinated with Buckminster and Kerrigan.
5. **Shared Reading, Discovery & Reflection:** scheduled, cost-bounded source ingestion and retrospective exploration as a cross-cutting capability, introduced when useful.

Harness evaluation, UX, voice dictation, authorization, and cost tuning occur **alongside** these phases, prompted by observed workflow limitations. There is **no Radar agent**; its former functions belong to existing roles or shared services.

## 2. Scope, objectives, and non-goals

### Objectives

- Deliver **useful end-to-end workflows**, not merely an expanded roster of agent names.
- Make access to external systems **reusable, permissioned, and auditable**.
- Keep **domain expertise** within relevant agents and **cross-domain execution support** within the Coach.
- Provide durable, human-readable knowledge and structured data that can be queried, visualized, and reused.
- Let agents create and maintain dashboards and reports through **version-controlled code**.
- Keep interactive tools and remote workers portable across model/harness upgrades.
- Provide clear human approval boundaries for purchases, sending messages, editing external accounts, deployments, and other consequential actions.

### Non-goals in the first implementation cycle

- Rebuilding OpenClaw or creating a new general-purpose harness.
- Developing a full custom PWA before simpler dashboard frameworks have been tested.
- Replacing Logseq with a bulk time-series database, or forcing all data into one schema.
- Building a dedicated monitoring/triage agent called Radar.
- Fully autonomous purchasing, finances, communications, or production changes.
- Turning the Coach into a diagnosis/treatment provider or an intrusive reminder system.
- Automatically changing an agent's permanent instructions based solely on articles it has read.

## 3. Current baseline and decision status

### Known or previously reported baseline

- **Overmind-01:** Raspberry Pi 4, Ubuntu Server 26.04, SSH and OpenClaw gateway; hosts orchestration and persistent services.
- **Kerrigan:** existing systems/operations agent, with tool access being broadened incrementally.
- **Cerebrate / Pixel 6:** remote inference and supporting infrastructure; vision model experiments have been validated. Use as a worker where appropriate rather than requiring large models on the Pi.
- **Buckminster:** the design agent, working through the Mac design worker (`macbook-m1`, a paired OpenClaw node).
  - **GIMP:** via GIMP Agent MCP (`gimp_gimp_*`).
  - **Sweet Home 3D:** since 2026-10-27, via the `sweethome3d-mcp-server` plug-in (`sweethome3d_*`). Both tool sets are scoped to Buckminster.
  - **Checkpoints:** remote Mac execution and durable checkpoint/resume were demonstrated end to end on 2026-10-23 (Spikes A–E), with `design-checkpoint` storing verified checkpoints in `/mnt/substrate/design-studio`. See the [environment report](agentic-design-studio-environment.md), the [remote-worker pattern](remote-workers.md), and the [service docs](../services/design-studio/README.md). The Room V1 capstone has run on this foundation since.
- **Substrate + Git:** intended durable source-of-truth pattern for repository files, project records, decisions, and artifacts.
- **Paperclip:** deployed as a container on Overmind. Its actual task and approval capabilities are unverified.
- **Composio and Bright Data:** accounts set up (2026-11-01). Composio is connected to **Pinterest, Gmail, and Google Calendar**, and has a Bright Data integration.
  - Reachability: AdGuard Home blocked `brightdata.com` and `luminati.io`; both are allow-listed as of 2026-11-01. Bright Data's other API/proxy domains are unchecked.
  - Neither is wired into an OpenClaw agent or tested in an agent workflow yet.

### Proposed, not yet proven as production integrations

Agent use of Composio, Bright Data, and Pinterest; Sweet Home 3D in a complete design workflow; Logseq DB/CLI/MCP, a goals ledger, Observable Framework, SQLPage, the Coach, the executive assistant, Saffron, and the professional coding/research/business specialists.

**Implementation rule:** At the start of each work package, inspect the actual Overmind host and repositories. Record installed versions, active services, credentials *locations* (not values), and tested tool endpoints. Do not infer deployment from this roadmap.

## 4. Target system architecture

| Layer | Responsibility | Expected technologies / contracts |
|---|---|---|
| **Interaction** | Human chat, mobile, voice/dictation, approvals, dashboards | Replaceable clients; later Overmind Views PWA |
| **Identity & authorization** | User identity, agent scopes, delegated actions, approval policy | Independent of chat transport; least privilege; secrets store |
| **Agent runtime** | Reasoning, skill use, tool calls, conversation sessions | OpenClaw default initially; Codex/Claude Code/Hermes Agent evaluated as needed |
| **Work orchestration** | Assignments, state, retries, human approvals, provenance | Paperclip or equivalent; Git-backed work artifacts |
| **Domain agents** | Design, behavior, fitness, cooking, coding, research, business, operations | Persistent identities where useful; ephemeral workers for bounded jobs |
| **Tool integration** | Deterministic operations in services and apps | Prefer API/CLI; expose MCP adapters when valuable; Composio/Bright Data candidates |
| **Knowledge** | Plans, notes, recipes, research, reflections, decisions | Substrate/Git, Logseq DB pilot, private agent memory |
| **Structured data** | Goals, activity events, measurements, derived metrics | SQLite first; DuckDB optional for heavier analytics |
| **Views** | Charts, dashboards, forms, summaries | Observable Framework preferred; SQLPage optional; PWA later |
| **Execution workers** | GUI, vision, automation and compute away from the Pi | Mac design worker, Pixel 6 inference, other scoped workers |

### Ownership and portability rules

1. **Agent identity is not a harness.** Kerrigan, Buckminster, and the Coach should retain role descriptions, permissions, context pointers, and work history even if their runtime changes.
2. **Source systems remain authoritative.** Garmin for its measurements, financial provider for account/transaction facts, Git for source code, Logseq for curated knowledge, and the goal ledger for goal events. Derived views link back to sources.
3. **Structured records are not free-form memory.** Use the database for events, status, targets, and histories; use Logseq/Substrate for interpretation, plans, and linked narrative context.
4. **Tools enforce permissions.** Do not depend on a mobile client or prompt alone to decide whether an action is allowed. Read, propose, approve, execute, and audit should be distinct operations where appropriate.
5. **Human-facing artifacts are durable.** Store editable documents, models, code, and visualization sources in predictable directories under version control when appropriate; attach provenance and checkpoints.
6. **Small pilots before platform commitments.** A successful, repeatable workflow is the adoption criterion.

## 5. Agent roster and responsibilities

| Agent | Primary owner of | Scope / status |
|---|---|---|
| **Kerrigan** | Infrastructure, deployments, health checks, operational access and alerts | Existing; expand carefully |
| **Buckminster** | Visual/spatial design, reference research, prototypes, editable design artifacts | Existing workstream; **next** |
| **Coach** | Cross-domain activation, flexible goals, accountability, reflection, executive-function support | **Next after Buckminster** |
| **Executive Assistant** | Email, calendar, personal administration, spending logistics, shopping, personal triage | Planned; name shortlist Hermes/TARS/Finch |
| **Soma** | Fitness, activity, nutrition/wellness plans and domain measurements | Previously defined; integration planned |
| **Saffron** | Recipes, food experimentation, inventory, meal and grocery planning | Planned |
| **Coding Specialist** | Software lifecycle ownership: architecture, coding delegation, tests, PRs, maintenance | Planned persistent lead; ephemeral coding/review executors |
| **Research Specialist** | Literature and technical investigations, source-grounded synthesis, experiments | Planned; some work can be ephemeral |
| **Business Specialist** | Market exploration, opportunity validation, unit economics, operations | Planned |

**Explicit removal:** Do not create **Radar**. Personal alerts and triage belong to the executive assistant; operational monitoring belongs to Kerrigan; goal check-ins belong to the Coach; source discovery belongs to the shared reading service and domain specialists.

## 6. Phase 1 — Buckminster: Pinterest, research channels, and 3D design

**Outcome:** A repeatable design workflow that discovers inspiration, tests spatial ideas in editable 3D, produces user-reviewable outputs, and saves source artifacts for subsequent work.

### Work packages

**B1 — Confirm the current design baseline.** Most of this is documented (§3). Confirm nothing has drifted:

- Buckminster's workspace and skills (including `.claude/skills/`);
- the Mac node, GIMP and Sweet Home 3D tools;
- the checkpoint store.

Record only changes and the remaining failure points.

**B2 — Integrate reference discovery.** Wire **Composio** into OpenClaw and test its existing Pinterest connection. Evaluate **Bright Data** (directly or through Composio's integration) for public-web research and extraction:

- Test both against real scenarios, and establish which provider handles which action.
- Use the authorized Pinterest connection for Pinterest, and Bright Data only for public-web sources where its use is permitted.
- Respect site access policies; do not bypass authentication, scraping restrictions, or copyright controls.
- First check that Overmind resolves and reaches every endpoint each provider uses. AdGuard's blocklist has already blocked Bright Data domains once.

**B3 — Create a reference workflow.** Given a user design brief, search selected sources, collect citation/URL metadata, keep image rights/attribution context, group references by themes, and persist a concise inspiration board or research dossier. Separate references from generated or user-owned artifacts.

**B4 — Test the 3D modeling path.** Sweet Home 3D and its MCP plug-in are already installed and scoped to Buckminster ([setup](../services/design-studio/README.md), [runbook](../services/design-studio/buckminster/sweethome3d.md)). Exercise them through Buckminster:

- open/create a room and change its dimensions;
- place and edit objects;
- save a native editable `.sh3d` project, then reopen it;
- export one inspectable preview.

Known limits to cover:

- agent edits are not on Sweet Home 3D's Undo;
- plug-in checkpoints live in memory and are lost when the app quits, so durable state must go through saved projects and `design-checkpoint`.

Compare against a practical alternative only if it can't be controlled reliably.

**B5 — Demonstrate a combined workflow.** Move from brief → cited references → design decisions → editable 3D scene → saved checkpoint → reviewed artifact. Where relevant, connect GIMP for visual iteration and test resume after the Mac worker disconnects.

### Phase 1 acceptance criteria

- Pinterest access path is authenticated, documented, permission-scoped, and tested; if blocked, record a reproducible limitation and supported fallback.
- Composio and Bright Data each have a clear **adopt / defer / reject** decision based on real tests (not feature lists).
- Buckminster can produce a small reference dossier with working provenance links and no unsupported access claims.
- Agent can make at least three specific changes to an editable 3D scene, export a preview, and reopen the native file successfully.
- At least one complete design task has traceable artifacts, manual review point, and checkpoint/recovery evidence.

## 7. Phase 2 — Coach, knowledge, goals, and visualization

**Outcome:** One persistent cross-domain Coach helps the operator act on self-endorsed goals without imposing rigid schedules. This phase also proves reusable structured data, knowledge management, and visualization infrastructure.

### 7.1 Behavioral Coach

The Coach owns the **relationship and behavioral support**, not the underlying fitness, finance, or software domain plans. It supports conversation, activation, focus/Pomodoro starts, voluntary accountability, practical emotional reflection, negotiation of partial progress, and recovery after disruption. It can use evidence-informed executive-function and behavioral techniques, but must not present itself as a licensed therapist or make clinical diagnoses.

**Intervention design:** Start user-initiated. Later add limited, opt-in proactive invitations via a tested client (Telegram and/or ntfy are candidates). Favor interactive choices such as **start / adjust / snooze / skip** over repeated one-way reminders. Ensure quiet hours, frequency caps, simple disable controls, and logged consent. Never fabricate an external human obligation or pressure the user to maintain streaks.

### 7.2 Lightweight Goal Ledger

Prefer a small **SQLite** store with a narrow HTTP/API surface. Make goal semantics flexible and keep calculations deterministic.

**Minimum entities:**

| Entity | Required attributes |
|---|---|
| `goal` | ID, domain, aspiration, owner, unit/measurement rule, active state |
| `commitment` | Goal ID, period, target, minimum viable action, stretch target (optional), consented follow-up rule |
| `progress_event` | Timestamp, source, measured action/value, note, provenance, correction history |
| `adjustment` | Prior commitment, agreed replacement, reason (optional), author, effective time |
| `intervention` | Trigger, channel, consent/policy outcome, prompt, user response, completion/skip status |

**Core operations:** list/read goals; propose and approve adjustments; record progress; query rolling trends; create/cancel a check-in; retrieve relevant context. Do not let the LLM silently change actual measurement values or erase the original commitment.

**Progress model:** Support binary, quantitative, milestone, and qualitative goals. Show target versus actual, meaningful partial credit, rolling windows, purposeful rest, and returns after interruption. Streaks are an optional motivator, not the sole measure of success.

### 7.3 Knowledge and memory

Pilot **Logseq DB + CLI/MCP** against a narrow set of use cases: Coach reflections, simple goal descriptions, Saffron recipes, research notes, and project decisions. Keep structured goal events in SQLite rather than bulk-writing them into Logseq. Evaluate backup/export, stable identifiers, automation safety, retrieval reliability, and human usability before committing to Logseq as the common knowledge layer.

The Coach's sensitive conversational context must have stricter access controls than shared goals. Other agents receive only explicit, scoped summaries/commitments; not full private reflections.

### 7.4 Shared analytics and views

- **Preferred:** **Observable Framework** for agent-authored interactive visualizations and reports, with code in Git.
- **Optional complement:** **SQLPage** for small database-backed forms, CRUD workflows, and simple tools.
- **Structured storage:** SQLite for the initial Goal Ledger and measurements; add **DuckDB** only when analytical size/query requirements justify it.
- **Long-term option:** **Overmind Views**, a unified PWA/nav shell for independently generated pages. **Do not start by building it.**

Demonstration dashboards: (1) Coach commitments/partial progress, (2) an illustrative or consented dataset comparing energy intake, estimated expenditure, and weight trends. Garmin/other provider connectors are independent integrations; do not assume they are accessible until tested. Derived measures must show units, methods, uncertainty where relevant, and source provenance.

### Phase 2 acceptance criteria

- One private Coach conversation continues correctly across sessions and retrieves only authorized context.
- At least three goals can be created, adjusted by consent, and visualized; meaningful partial progress and planned rest work correctly.
- One interactive accountability session completes start → voluntary check-back → logged outcome, including snooze/disable behavior.
- Logseq pilot can create, retrieve, edit, and export example records without losing source data; decision recorded.
- Observable renders a version-controlled dashboard from a repeatable structured dataset; assess SQLPage with one editable form only if needed.
- Notification frequency limits, privacy boundaries, and event audit trail are exercised in tests.

## 8. Phase 3 — Personal specialists on the shared foundation

**Executive Assistant:** Email and calendar workflows, personal administration, money/budget summaries, shopping coordination, and personally relevant alerts; use Composio/connectors where validated. Draft-and-approve before sending or purchasing. Name is **undecided**: Hermes, TARS, Finch. Note that **Hermes Agent** is separately a candidate harness technology.

**Soma:** Own exercise, activity, nutrition and wellness planning. Supply approved goals and progress summaries to the Coach. Integrate Garmin or other activity sources through verified mechanisms; keep raw health data scoped to necessary uses.

**Saffron:** Own cooking knowledge, recipe variants, food inventory, meals and groceries. Use Logseq/Substrate for recipes and notes, structured tables only where justified, and pass approved shopping needs to the executive assistant.

**Acceptance pattern:** For each specialist, prove one cross-agent workflow with clear data ownership, explicit authorization, an editable artifact or measurable output, and a human correction path. Avoid duplicating Coach/accountability behavior in every domain agent.

## 9. Phase 4 — Professional agent ecosystem

**Coding Specialist:** A persistent software-engineering lead that interprets requirements, delegates work, understands repositories, designs changes, reviews tests and PRs, and coordinates releases. Use **Codex, Claude Code, GitHub Copilot, or Cursor** as replaceable execution tools where they fit. Evaluate **P-Stack** for rigorous review/verification and **Ponytail** for simplicity/anti-overengineering; keep both as optional reusable skills, not mandatory frameworks.

**Research Specialist:** Source-grounded literature/research review, deep technical investigation, reproducible experiments, and technical briefs. Can run temporary specialized researchers when cheaper or more focused.

**Business Specialist:** Opportunity research, validation hypotheses, customer/market evidence, unit economics, commercialization, and business operations proposals. Actions with financial, contractual, or public commitments require human approval.

**Shared workflow target:** Opportunity/brief → research → Buckminster design → coding implementation → verification/PR → Kerrigan deployment → feedback/iteration. The sequence is iterative, not an inflexible waterfall. Paperclip (or verified equivalent) manages task status and approvals; Git/Substrate retains durable outputs.

## 10. Shared capability — Reading, Discovery & Reflection

Build as a **shared ingestion/synthesis capability**, not a dedicated agent. Each domain agent may have its own source curriculum: explicit subscriptions, priority tiers, topics, schedule, and exploration budget.

- **Buckminster:** Architectural Digest / Open Door, contemporary design media, historical movements, classic practitioners and spatial-design references.
- **Coding Specialist:** Official release notes and security notices (freshness-sensitive), engineering blogs, seminal papers, established architecture patterns.
- **Saffron:** Culinary publications, traditions, technique histories and food science.
- **Research / Business:** Academic sources, canonical work, historical case studies, market developments, and failures worth learning from.

**Recency is not the objective by default.** Rank for relevance, authority, conceptual usefulness, historical influence, project fit, and freshness only when it matters (especially security/release information). Include intentional retrospective discovery.

A shared collector should fetch/deduplicate and preserve source references. Domain agents then read, reflect, propose experiments or tasks, and selectively promote supported findings to Logseq/Substrate. Do not overwrite durable instructions based on a single article; distinguish observations, hypotheses and verified facts. Keep alerts quiet by default except genuinely urgent, authorized operational notices.

**Initial pilot:** Weekly Buckminster design journal plus weekly coding engineering journal, each with source links, three concise observations, and at most one actionable proposal. Evaluate usefulness before expanding.

## 11. Cross-cutting engineering requirements

### Security, permissions, and privacy

- Scope credentials per integration/agent; keep secrets out of prompts, Git, logs, and exported artifacts.
- **Scope every new tool surface to its owning agent from day one.** OpenClaw exposes MCP and node-published tools to every agent by default. A Composio MCP server, for example, would give every agent Gmail and Calendar. Allow the tools on the owner and deny them on the others, as done for `gimp_gimp_*` and `sweethome3d_*` ([pattern](remote-workers.md#3-publishing-tools-to-exactly-one-agent)).
- Distinguish discovery/read, draft/propose, edit, and consequential execute rights.
- Authenticate users at the service layer regardless of which chat client initiates a command.
- Use explicit approvals for messages sent, purchases, changes to external accounts, production deployments and irreversible operations.
- Keep Coach reflections and health/financial details private by default; share only narrowly defined, consented summaries.
- Log tool action metadata and approvals without storing unnecessary sensitive content.

### Reliability and operations

- Back up SQLite and Logseq data; document restoration and migration paths.
- Make integrations retryable/idempotent when appropriate and record external API failures transparently.
- Define task limits for model spend, crawler volume, worker CPU/GPU time and notifications.
- Require source attribution, timestamp and transformation method for derived analytics.
- Prefer standard containers/services where feasible on the Pi; validate CPU/RAM and ARM compatibility before deployment.

### Performance and harness evolution

Do **not** make a large platform benchmark a mandatory first phase. Instead collect observed failure cases and compare identical tasks with controlled models/settings when appropriate. Resolve degraded tool use, context handling, mobile permission anomalies, speech-to-text UX and routing incrementally. Maintain a replaceable agent-runtime boundary. Always test against the actual installed API/harness versions rather than presumed feature lists.

When evaluating another harness (Codex, Claude Code, Hermes Agent), check whether it delegates outside OpenClaw. The Codex harness's native `spawn_agent` bypassed OpenClaw's sandbox and audit trail entirely ([history](../runbooks/openclaw/sandboxing-and-trust.md#iteration-2--agent-identity-based-trust-with-separate-worker-identities)).

## 12. Implementation plan and decision gates

| Order | Deliverable | Depends on | Decision gate |
|---|---|---|---|
| **Now** | Buckminster baseline and external-service integration tests | Existing GIMP/Sweet Home 3D/Mac/Cerebrate work | Verify Pinterest access and Composio/Bright Data value |
| **Next** | Sweet Home 3D pilot + end-to-end design artifact | Design integration | Keep or replace the 3D tool based on reproducibility |
| **Then** | Coach identity + privacy and goals ledger | Existing agent runtime; SQLite | Three real goals, flexible adjustment, persistence |
| **Then** | Logseq and Observable pilots | Goal data / knowledge samples | Adopt only after edit/export/rebuild tests |
| **Then** | Interactive Coach check-ins | Approved channel and policy | Helpful, low-frequency, dismissible intervention |
| **After** | Executive assistant, Soma, Saffron integrations | Shared connectors + data | Demonstrate cross-agent handoff |
| **In parallel / later** | Coding, research, business roles | Git/Paperclip/tool channels | Repeatable reviewed work product |
| **Incremental** | Harness/UX improvements and reading service | Concrete use cases | Demonstrable quality or workflow gains |

**No calendar deadlines are imposed by this design.** Sequence reflects dependencies and current priorities, not promises of delivery dates.

## 13. Immediate agent handoff — first work package

### Assignment: Buckminster integration and 3D capability spike

**Objective:** Deliver one usable Pinterest/reference-research path and one functioning editable 3D modeling path, then demonstrate a combined design workflow.

**Instructions to implementing agent:**

1. Inspect the actual Overmind installation, repo, service state, available MCPs, and existing Buckminster/GIMP work. Produce a short inventory and note unknowns.
2. Research/verify supported Pinterest connectivity via Composio and relevant Bright Data endpoints. Confirm authentication and allowed operations; do not assume product support from names alone.
3. Implement the **smallest reversible integration** with least-privilege credentials and a documented test fixture. Preserve raw links, timestamps and provenance for references.
4. Exercise the installed Sweet Home 3D tools through Buckminster: produce an editable native project and an exported image/preview, and test save/reopen.
5. Exercise a practical brief-to-output workflow and store editable files, references, generated assets, steps, and reviewer instructions in the project artifact directory.
6. Document limitations, security considerations, resource consumption and clear next actions. Request approval before any externally consequential operation or irreversible change.

**Required deliverables** (notes in `design-notes/`; design artifacts under `/mnt/substrate/design-studio/projects/<project-id>/`, committed through `design-checkpoint`):

- `integration-inventory.md` — current tools/services and verified versions, without secrets.
- `pinterest-research-spike.md` — test cases, results, provider decision, provenance and constraints.
- `3d-modeling-spike.md` — supported operations, test commands/tools, errors, native-format save/reopen results.
- `design-pilot/` — editable 3D project, preview, reference manifest, and concise design brief.
- `implementation-notes.md` — reproducible setup, rollback, follow-up backlog and acceptance assessment.

**Completion standard:** Report each acceptance criterion as **pass / partial / blocked**, with evidence and reproduction steps. Do not substitute a mockup for a native editable model. Do not claim a connector or integration is available without executing a representative test.

## 14. Decisions, open questions, and future extensions

### Decisions captured in this version

- **No Radar**; roles redistributed to Kerrigan, executive assistant, Coach, and shared reading service.
- **Buckminster first, Coach second**; personal/professional specialists build on shared access and data foundations.
- **Harness/UX benchmarking is incremental**, not a blocker.
- **Logseq DB is a pilot**, not yet the guaranteed universal database.
- **SQLite is the initial structured store**; DuckDB is optional for analytics.
- **Observable Framework is the preferred visualization trial**; SQLPage is a potential forms/data-entry complement.
- **Overmind Views PWA is a future possibility**, conditional on proven limitations of simpler options.
- **One cross-domain Coach**, not one coach per domain; domain agents own substantive plans.
- **Reading includes classic and historical work**, not just current publications.

### Open decisions (resolve only when their phase begins)

- Final executive assistant name: **Hermes / TARS / Finch**.
- Exact Pinterest integration method and Composio/Bright Data division of responsibility.
- 3D modeling application's long-term selection and supported remote-control surface.
- Logseq DB operational fit, backup/export mechanism, and integration contracts.
- Whether SQLPage is needed alongside Observable for the first Coach dashboard.
- Exact mobile interactive check-in transport (Telegram, ntfy, another client) and per-channel permissions.
- Long-term agent/runtime assignments and when to deploy Paperclip-driven professional workflows.

---

**Implementation posture:** Ship the smallest useful vertical slice, measure it against a real workflow, record evidence and decisions, then expose the capability for reuse. The roadmap is a living design, but this version is an agreed starting baseline for the next implementing agent.
