# Overmind Operating Model
## Intake, Project Lifecycle, Context Retrieval, Paperclip, and Kerrigan

**Status:** Consolidated design plan  
**Date:** 2026-09-11

> **This document supersedes all previous Kerrigan design documents.**
>
> It replaces the earlier designs that framed Kerrigan primarily as a server administrator or resident operator in isolation. Kerrigan is now specified as one component of a broader Overmind operating model spanning project intake, canonical project state, context retrieval, Paperclip execution, and operational management.

---

# 1. Purpose

Overmind needs to become easier to build with, not harder.

Today, many useful ideas begin in conversation, become Markdown design documents, are manually handed to another agent, edited into a local repository, pushed and pulled to the server, deployed, debugged, and then reconciled manually.

That process works, but it contains too much human glue.

At the same time, Overmind is accumulating:

- design notes;
- future ideas;
- papers and links;
- infrastructure decisions;
- code repositories;
- media ingestion workflows;
- operational alerts;
- agent tasks;
- implementation plans;
- runbooks.

The goal of this design is to create a lightweight operating model that makes those things easier for both humans and agents to understand and act on without introducing a large new software stack.

The design follows several core rules:

> **Conventions over software.**

> **Canonical files and repositories over duplicate databases.**

> **Derived indexes over duplicated truth.**

> **Native inputs first; normalize only where needed.**

> **Specialized agents own work; one universal agent does not.**

> **Paperclip owns active execution, not long-term project knowledge.**

> **Kerrigan can operate broadly, but only within task-scoped authority.**

---

# 2. High-Level Architecture

```text
                  CANONICAL PROJECT STATE

        Git repos / Markdown / OKF / configs / data
                           │
            ┌──────────────┼──────────────┐
            │              │              │
            ▼              ▼              ▼
      project lifecycle   indexes     relationships
        + metadata       + search      + provenance
            │              │              │
            └──────────────┼──────────────┘
                           ▼
                    stable interfaces
                           │
         ┌─────────────────┼──────────────────┐
         ▼                 ▼                  ▼
   human clients       Paperclip            agents
  boards / notes       execution       retrieval / reasoning
                                              │
                                              ▼
                                           Kerrigan
                                 operate / deploy / repair
```

This architecture deliberately separates canonical state, project attention/state, derived retrieval systems, agent execution, and human interfaces.

Any layer above canonical state should be replaceable.

---

# 3. Canonical Project State

Each project should retain ordinary, inspectable canonical state.

Examples:

```text
code
→ Git repository

design notes
→ Markdown / OKF-style documents

project state
→ Markdown metadata / frontmatter conventions

infrastructure
→ infrastructure repository / Compose / config

media workflows
→ media pipeline config and scripts

research
→ papers, references, metadata, notes

runbooks
→ Markdown / operational documentation
```

Substrate is not itself a note-taking application, task manager, vector database, or agent orchestrator.

It is the portable project model and conventions that let these different systems agree on what belongs to a project and how it relates.

---

# 4. Workstream A — Project Intake and Lifecycle

## Goal

Stop treating the project `docs/` directory as an undifferentiated dumping ground.

Ideas, links, papers, speculative designs, near-term work, and mature implementation designs should have different lifecycle states.

The initial project lifecycle should remain intentionally small:

```text
inbox
  ↓
backlog
  ↓
on-deck
  ↓
explore
  ↓
refine
  ↓
ready
  ↓
Paperclip execution
```

`archive` may be used for material retained for history but no longer active.

## Implementation Plan

### Step 1 — Define the minimal work-item convention

Define a small Markdown/frontmatter schema for project items.

```yaml
---
id: overmind-0042
type: design
stage: explore
priority: normal
project: overmind
related:
  - overmind-context-index
---
```

Avoid adding fields until real use demonstrates a need.

### Step 2 — Apply it to the Overmind project first

Use the Overmind server repository as the first dogfood project.

Create clear homes for ideas, designs, references, decisions, and work items.

Existing documents do not need to be perfectly migrated immediately. New work should follow the convention first.

### Step 3 — Add triage habits, not a triage service

New material can arrive naturally as a Markdown note, design document, paper, URL, or project thought.

The item begins as `inbox`. Triage decides whether it becomes `reference`, `backlog`, `on-deck`, `explore`, `refine`, or `archive`.

No new daemon or queue is required.

### Step 4 — Use existing clients as views

Evaluate existing clients that can consume Markdown/frontmatter as project cards.

Priority candidates:

- Obsidian Bases;
- SilverBullet;
- OpenKnowledge.

The client is a view, not the source of truth.

### Step 5 — Promote only mature work into execution

Only sufficiently understood work reaches:

```text
stage: ready
```

At that point it can be handed to Paperclip.

---

# 5. Workstream B — Intake as a Shared Pattern

## Goal

Recognize that project ideas, media uploads, ROM ingestion, and operational alerts all share a common logical pattern without forcing them into one universal physical inbox.

The common lifecycle is:

```text
arrive
  ↓
classify
  ↓
route
  ↓
process
  ↓
verify
  ↓
escalate if needed
```

There should be **one intake concept, not one mandatory intake format**.

## Implementation Plan

### Step 1 — Keep native entry points

Use the natural interface for each domain.

```text
media
→ /incoming/media

ROMs
→ /incoming/roms

project ideas
→ project Markdown / chat / notes

alerts
→ monitoring / service-native events
```

Do not require the sender to construct a separate universal envelope.

### Step 2 — Route by existing context first

Prefer inference from path, project location, frontmatter, service metadata, alert metadata, and conversational context.

Only add explicit metadata when ambiguity actually appears.

### Step 3 — Introduce a lightweight router only where useful

Simple deterministic routing should handle obvious cases:

```text
media arrival
→ media ingestion workflow

operational alert
→ Kerrigan

project idea
→ project intake

ambiguous input
→ chief-of-staff / triage agent
```

The router should route, not become another workflow engine.

### Step 4 — Let specialist systems own the payload

Do not copy large or specialized payloads into an abstract inbox.

```text
movie stays in media storage
logs stay in observability system
paper stays in research library
code stays in Git
```

Only references and work state need to flow between systems.

### Step 5 — Turn recurring judgment into deterministic workflows

When a repeated intake pattern becomes well understood:

```text
agent handles novelty
→ successful pattern
→ script / rule / runbook
→ agent handles exceptions only
```

This should be a system-wide Overmind principle.

---

# 6. Workstream C — Project and Knowledge Indexing

## Goal

Make project knowledge cheap for agents to explore without dumping entire repositories or document collections into model context.

Derived indexes are disposable and rebuildable. Canonical files remain authoritative.

## Implementation Plan

### Step 1 — Start with explicit metadata and lexical search

Before embeddings, make project structure easy to query.

Use filenames, directories, frontmatter, IDs, relationships, and ripgrep/full-text search.

### Step 2 — Add semantic retrieval

Build a project-scoped semantic index over design documents, decisions, notes, research summaries, and runbooks.

Semantic retrieval should supplement, not replace, exact search.

### Step 3 — Preserve project and provenance boundaries

Search results should retain project, source path, document type, stage, timestamp/revision where useful, and relationships.

### Step 4 — Build bounded context packages

The retrieval layer should answer requests such as:

```text
What do I need to know to redesign Gather model storage?
```

with a bounded package containing current architecture, relevant decisions, on-deck or active designs, relevant research, and related work items.

### Step 5 — Measure context cost

Track rough retrieved tokens, files read, repeated retrieval, and context hit rate.

The goal is not merely better search. It is lower model cost and less redundant rediscovery.

---

# 7. Workstream D — Code Intelligence

## Goal

Treat code as a specialized canonical resource.

Do not force source code into the same representation as Markdown project knowledge.

The Git repository remains canonical. A derived code-intelligence layer provides efficient navigation.

## Implementation Plan

### Step 1 — Establish cheap exact search

Use tools such as ripgrep, Git, and language-native search for names, errors, symbols, APIs, and strings.

### Step 2 — Add a structural code map

Use Tree-sitter or an Aider-style repository map to extract symbols, definitions, references, imports, and dependencies.

Produce a compact architecture map that fits inside a bounded token budget.

### Step 3 — Add semantic code retrieval only where useful

Use semantic retrieval for questions such as:

> Where does this repository handle model lifecycle?

Do not rely on embeddings for exact symbol navigation.

### Step 4 — Expose one context interface to agents

Agents should ask for repo map, symbol definition, references, related files, semantic matches, and recent changes without needing to know which backend provides them.

### Step 5 — Keep the backend replaceable

Start with:

```text
ripgrep
+
Tree-sitter / Aider-style repo map
+
semantic index
```

Only evaluate heavier systems such as Sourcegraph when scale justifies them.

---

# 8. Workstream E — Paperclip Execution Seam

## Goal

Keep planning/project state separate from active execution.

Substrate/project files own work before it becomes executable. Paperclip owns active agent work.

## Implementation Plan

### Step 1 — Define the handoff point

The primary transition is:

```text
stage: ready
      ↓
Paperclip work item
```

Before that boundary, project state is canonical in files. After that boundary, Paperclip owns active execution state.

### Step 2 — Link rather than duplicate

A project item may record:

```yaml
paperclip:
  issue: pc-01847
```

Do not continually mirror Paperclip blockers, review state, assignments, and agent state into Markdown.

### Step 3 — Use Paperclip's native execution surfaces

Prefer Paperclip for assignment, agent runs, reviews, blockers, approvals, decisions, and execution history.

### Step 4 — Return durable outputs to canonical state

When work finishes:

```text
code
→ committed to repo

design decision
→ canonical project docs

runbook
→ operational docs

configuration
→ canonical config
```

Paperclip retains execution history, but not the sole copy of durable project knowledge.

### Step 5 — Keep the adapter replaceable

If Paperclip is replaced later, project lifecycle, canonical docs, indexes, code, and relationships should remain intact.

Only the execution adapter changes.

---

# 9. Workstream F — Kerrigan, Overmind Resident Operator

## Goal

Kerrigan is Overmind's resident operator.

Her jurisdiction may include infrastructure, server configuration, Substrate, media pipelines, runners, automation, storage, backups, and supporting services.

Broad jurisdiction does **not** imply blanket standing privilege.

Kerrigan acts under task-scoped authority.

## Implementation Plan

### Step 1 — Give Kerrigan direct access to canonical workspaces

Kerrigan should be able to work directly in relevant repositories and configuration spaces, including:

```text
overmind-infra
media configuration
Substrate config
runner configuration
operational docs
```

This removes the current manual handoff loop.

### Step 2 — Keep privileged mutation governed

Kerrigan should not receive unrestricted passwordless root access.

Privileged operations should use bounded mechanisms such as restricted sudo commands, service-native APIs, Docker operations, reviewed scripts, Ansible playbooks, or MCP/governed operational tools.

### Step 3 — Authorize objectives, not individual commands

A task should grant a temporary execution envelope.

```yaml
objective:
  deploy-paperclip

resources:
  - paperclip
  - postgres
  - paperclip-storage

allowed:
  - observe
  - routine
  - configuration

blocked:
  - ssh
  - firewall
  - unrelated-storage
  - destructive-database-actions
```

Kerrigan should not ask permission for every directory creation or restart inside that approved scope.

### Step 4 — Verify deterministically

Kerrigan should never infer success from command completion alone.

Examples:

```text
service deployment
→ health endpoint passes

media pipeline
→ test artifact reaches final destination

Substrate index
→ rebuild succeeds + representative query works

backup
→ restore verification passes
```

### Step 5 — Reconcile all durable changes

If Kerrigan fixes something live first:

```text
live fix
→ verify
→ reproduce in canonical repo/config
→ validate
→ commit
```

Completed work should not leave unexplained configuration drift.

---

# 10. Workstream G — Overmind Ops Contract

## Goal

Avoid hard-coding Kerrigan's knowledge of every service and resource.

Managed resources should describe themselves through convention and minimal metadata.

## Implementation Plan

### Step 1 — Start with service opt-in conventions

For Docker services:

```yaml
labels:
  overmind.managed: "true"
  overmind.project: "overmind"
```

Reuse existing health checks and logs where available.

### Step 2 — Define common action classes

Use a small stable set:

```text
observe
routine
configuration
destructive
critical
```

Global policy governs those classes.

### Step 3 — Infer common capabilities

For managed services, infer status, logs, health, and restart where possible.

Do not require explicit configuration for obvious runtime capabilities.

### Step 4 — Add custom capabilities only for domain-specific operations

Examples:

```text
retry ingestion
rebuild index
verify backup
rescan library
```

### Step 5 — Expand beyond services only when needed

Future managed resources may include repositories, indexes, filesystems, pipelines, runners, devices, and backup targets.

Do not model all of them on day one.

---

# 11. Workstream H — Human-Facing Project Views

## Goal

Provide a visual project-management layer without making the UI canonical.

The ideal human view is card/board-oriented.

## Implementation Plan

### Step 1 — Test Obsidian compatibility

Use Markdown/frontmatter files in a way that Obsidian Bases can render.

Target views:

```text
Inbox
Backlog
On Deck
Explore
Refine
Ready
```

### Step 2 — Test at least one open/server-first client

Evaluate SilverBullet or OpenKnowledge against the same canonical files.

The goal is to verify client portability.

### Step 3 — Keep board state in files

Dragging a card should conceptually update:

```yaml
stage: refine
```

not move the authoritative state into a proprietary board database.

### Step 4 — Link active cards to Paperclip

When an item is active, the board can display Paperclip-derived state through an adapter.

The board should not become another execution engine.

### Step 5 — Build custom UI only if real limitations emerge

Do not write an Overmind board client until existing tools prove insufficient.

---

# 12. Workstream I — Chief of Staff / Routing Agent

## Goal

Use a general triage agent only for ambiguous routing and coordination.

Do not make it responsible for all execution.

## Implementation Plan

### Step 1 — Route obvious cases deterministically

Examples:

```text
server alert
→ Kerrigan

media arrival
→ media workflow

project idea tagged Gather
→ Gather project intake
```

### Step 2 — Send ambiguity to the triage agent

Examples include:

```text
"Check out this paper."
"Maybe we should use this tool."
"Interesting idea for one of our projects."
```

The agent determines likely project/domain and next state.

### Step 3 — Delegate to specialists

Possible delegates include Kerrigan, designer, researcher, software-development agent, and media workflow.

### Step 4 — Keep human attention exceptional

The chief-of-staff agent should ask the human only where classification is materially uncertain, multiple project destinations are plausible, or a consequential decision is needed.

### Step 5 — Learn repeated routing patterns

Frequent successful routes should become conventions or rules rather than repeated model decisions.

---

# 13. Dogfood Plan — Overmind as the First Project

The Overmind server itself should be the first project using this architecture.

This is important because improvements compound.

```text
better project structure
      ↓
agents understand Overmind better
      ↓
Kerrigan implements changes faster
      ↓
less manual glue
      ↓
more Overmind capabilities
      ↓
repeat
```

## First Practical Sequence

### 1. Organize current Overmind design state

Create or normalize homes for:

```text
designs
work items
decisions
references
runbooks
```

Apply the minimal stage/type metadata to new documents.

### 2. Establish the first project board

Use an existing Markdown/frontmatter-capable client.

Do not build new software.

### 3. Add lightweight code/project retrieval

Start with:

```text
ripgrep
metadata
repo map
project search
```

Then measure what agents still struggle to find.

### 4. Wire `ready` work into Paperclip

Use Paperclip for execution rather than creating another work engine.

### 5. Deploy Kerrigan as the resident operator

Give Kerrigan direct workspace access plus governed operational capabilities.

Use her to implement subsequent Overmind design work.

---

# 14. What Not to Build Yet

Do not introduce:

- Kafka;
- Redis queues solely for intake;
- a universal inbox database;
- a new project-management backend;
- a custom note-taking system;
- a custom board application;
- a custom vector database unless needed;
- a giant observability stack before basic needs justify it;
- a bespoke code intelligence platform;
- a universal Kerrigan service registry.

Prefer:

```text
filesystem conventions
Markdown / OKF
Git
existing service metadata
existing clients
small adapters
derived indexes
Paperclip
bounded operational tools
```

---

# 15. Success Criteria

This architecture succeeds if the normal Overmind development loop becomes:

```text
idea appears
   ↓
captured in project
   ↓
triaged / explored / refined
   ↓
ready
   ↓
Paperclip assigns work
   ↓
agent receives bounded project/code context
   ↓
Kerrigan applies operational changes when required
   ↓
deterministic verification
   ↓
durable outputs return to canonical state
```

with progressively less manual handoff.

The human should increasingly spend time on intent, architecture, priorities, and consequential decisions.

Agents and deterministic systems should increasingly handle retrieval, organization, implementation, deployment, verification, routing, and routine operations.

---

# 16. Concise Architectural Summary

> **Overmind stores project truth in ordinary files, repositories, and native domain systems. Lightweight conventions describe project lifecycle and relationships. Derived indexes make that state cheap for agents to explore. Existing clients provide interchangeable human views. Paperclip owns active execution. Kerrigan operates Overmind under task-scoped authority. Repeated workflows become deterministic over time. No application above the canonical project state should be indispensable.**
