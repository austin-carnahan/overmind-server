# Overmind — Product Thesis and Architectural Principles

## Status

Foundational product and architecture design note.

## Purpose

Overmind is evolving beyond the idea of a home server, media server, or local-AI machine.

Its purpose is to become a **self-hosted, open, composable personal compute environment for persistent projects and agentic work**.

Overmind should integrate rapidly evolving open-source tools, models, standards, indexing systems, orchestration frameworks, and automation services into a coherent environment that can be accessed from many client devices and work contexts.

The core product value is not inventing every layer.

The value is **composition**.

---

# 1. Product Thesis

Overmind should make frontier open-source agent infrastructure feel like a coherent personal computing environment rather than a collection of unrelated developer tools.

The defining idea is:

> **Persistent context and capabilities live on the server. Humans, agents, IDEs, applications, and client devices operate against that shared environment.**

Conceptually:

```text
                         CLIENTS
            ┌──────────────┼──────────────┐
            │              │              │
            ▼              ▼              ▼
          IDE            Browser        Mobile
            │              │              │
            └──────────────┼──────────────┘
                           │
                           ▼
                       OVERMIND
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
        ▼                  ▼                  ▼
    Substrate          Paperclip          Services
 project context      orchestration       automation
        │                  │                  │
        ├──────────┐       │       ┌──────────┤
        ▼          ▼       ▼       ▼          ▼
     indexes      Git    agents   models     media
```

The server is the persistent center.

Client devices are temporary work surfaces over it.

---

# 2. Composition Is the Product

Overmind should strongly prefer composing mature, open systems over recreating them.

Examples include:

- Paperclip for agent orchestration;
- Open Knowledge Format-style conventions for portable knowledge;
- RO-Crate-style metadata where typed resource relationships are valuable;
- Git for source history;
- Markdown and ordinary files for canonical project knowledge;
- MCP-style interfaces for agent/tool access;
- pgvector, Qdrant, or similar systems for derived semantic retrieval;
- Tree-sitter/Aider-style techniques for efficient code indexing;
- local and hosted LLM runtimes;
- Sonarr, Bazarr, Transmission, RomM, Igir, and similar deterministic application tools;
- existing authentication, networking, backup, and container infrastructure.

The question for every proposed Overmind component should be:

> **Does this capability already exist somewhere we can adopt, configure, wrap, or integrate?**

Custom software should be reserved for genuine gaps.

---

# 3. Open Source by Default

Overmind should bias toward:

- open-source implementations;
- open protocols;
- portable data formats;
- self-hostable infrastructure;
- independently replaceable components;
- ordinary files and databases that remain understandable outside the application that created them.

Closed services may still participate when they provide meaningful capability, but they should not become unnecessary architectural dependencies.

A hosted frontier model may perform a difficult task.

It should not become the only system capable of understanding an Overmind project.

---

# 4. Server-First, Client-Agnostic

Persistent state should live on Overmind rather than on individual user devices wherever practical.

Examples include:

```text
projects
repositories
papers
notes
agent work
task state
indexes
models
automations
media libraries
service configuration
```

A laptop, phone, IDE, browser, or future client should connect to that environment rather than become a separate information silo.

This enables continuity:

```text
Morning:
VS Code on laptop

Afternoon:
Paperclip agents

Evening:
browser review inbox

Travel:
different laptop

All operate against the same project world.
```

The goal is to eliminate the concept of:

> “the copy of the project that lives on this particular device.”

---

# 5. Substrate as the Shared Project Context Standard

Substrate should define how projects are organized and understood rather than necessarily becoming a bespoke software application.

A Substrate project should remain useful with no AI system running.

It should consist primarily of portable, human-readable resources:

```text
project/
├── project metadata
├── repositories
├── notes
├── decisions
├── references
├── papers
├── datasets
├── artifacts
└── agent/context conventions
```

Shared resources such as papers may exist canonically outside a single project while being referenced from multiple projects.

The important relationship is semantic:

```text
Paper A
├── relevant to Gather
├── relevant to thesis
└── relevant to future project
```

not necessarily physical duplication.

Substrate should favor emerging open conventions such as Open Knowledge Format and reuse existing metadata standards wherever practical.

---

# 6. Canonical Data vs. Derived Intelligence

One of Overmind's strongest architectural boundaries should be the distinction between canonical project state and derived machine state.

## Canonical

Examples:

```text
source code
papers
notes
decisions
datasets
project metadata
references
artifacts
human-authored documents
```

These should be portable, inspectable, and backed up carefully.

## Derived

Examples:

```text
embeddings
vector indexes
search indexes
code graphs
generated summaries
model caches
temporary agent worktrees
transcodes
runtime caches
```

These should be reproducible.

A database failure should never destroy the only meaningful copy of a project's knowledge.

---

# 7. Indexing as Core Infrastructure

Indexing is part of the Substrate MVP because agents should not repeatedly ingest entire project trees.

Overmind should support multiple complementary retrieval mechanisms:

```text
metadata filtering
+
full-text / lexical search
+
semantic/vector retrieval
+
structural code indexing
```

Retrieval should be:

- project-scoped by default;
- provenance-preserving;
- incrementally updated;
- token-budgeted;
- agent-neutral.

The index should answer:

> “Where should I look?”

The canonical file answers:

> “What is actually true right now?”

Agents should always return to canonical sources before consequential edits or conclusions.

---

# 8. Agent Orchestration

Paperclip is currently the preferred orchestration/control-plane layer.

Its role is to coordinate work rather than define the entire Overmind environment.

Paperclip should manage:

```text
tasks
delegation
agent identities
review stages
decisions
approvals
attention/inbox state
work products
schedules
audit history
```

Agents should remain heterogeneous and replaceable.

Possible workers include:

```text
local LLM agents
Codex
Claude Code
IDE agents
research agents
Mastra workflows
LangGraph workflows
HTTP services
future agent runtimes
```

Paperclip is pinned, but it should not become inseparable from Substrate.

---

# 9. Human Attention as a Scarce Resource

Overmind should optimize for:

> **delegate aggressively, interrupt selectively.**

Routine agent work should proceed independently.

Human attention should be requested primarily for:

- consequential decisions;
- ambiguity;
- destructive actions;
- architecture changes;
- external costs;
- security-sensitive actions;
- unresolved reviewer disagreement;
- final review where warranted.

Paperclip's Attention and Decisions surfaces are currently the preferred implementation of this human-review layer.

The primary question presented to the user should be:

> **What needs me?**

not:

> “What are all my agents currently doing?”

---

# 10. Agents Should Supervise Tools, Not Replace Them

Overmind should avoid using LLMs for deterministic problems already solved by reliable software.

Examples:

```text
Sonarr
→ tracks series and release state

Bazarr
→ subtitle automation

Transmission
→ transfers

RomM
→ game library

Igir
→ ROM identification and normalization

Git
→ source control

CI/tests
→ objective verification
```

Agents should provide:

- intent;
- coordination;
- interpretation;
- exception handling;
- review;
- escalation.

This distinction reduces cost, hallucination risk, and unnecessary complexity.

---

# 11. Deterministic Verification

An agent saying something succeeded should never substitute for objective system state.

Examples:

```text
Did tests pass?
→ test runner

Did PR merge?
→ Git/GitHub state

Did deployment become healthy?
→ health checks

Did backup complete?
→ backup system

Did media validate?
→ ffprobe / validation pipeline
```

Paperclip and agents may interpret these results.

They should not invent them.

---

# 12. Model Independence

Overmind should treat models as interchangeable compute resources.

A model pool might include:

```text
small local model
→ routine organization / classification

local coding model
→ repo work / automation

large local model
→ more demanding reasoning

hosted frontier model
→ difficult or consequential tasks
```

The orchestration layer should choose models based on:

- capability;
- cost;
- privacy;
- latency;
- context size;
- workload type.

No project representation should depend on one model vendor.

---

# 13. Hardware as a Local Personal Compute Platform

Overmind should run on a server capable of becoming part of daily professional work, not merely entertainment infrastructure.

The target server should support:

```text
media services
Substrate
Paperclip
databases
indexing
local inference
agent workspaces
development tools
automation
backups
```

The preferred architecture is one primary always-on server with expandable compute and storage.

A dedicated lightweight DNS appliance may remain separate because DNS is an appropriate infrastructure boundary.

Additional machines should only be introduced when they provide a clear capability, reliability, or recovery benefit.

---

# 14. Composability and Replaceability

Every major subsystem should have an architectural seam.

Conceptually:

```text
Substrate
   ↓
context/search interface

Paperclip
   ↓
agent invocation interface

Models
   ↓
inference/API interface

Applications
   ↓
service APIs

Clients
   ↓
web / IDE / MCP / SSH
```

If one implementation disappears or is superseded, the layer should remain conceptually intact.

Examples:

```text
Qdrant → pgvector
Paperclip → future orchestrator
VS Code → future IDE
llama.cpp → future inference runtime
Telegram → another notification surface
```

Replacing a component should not require rebuilding the user's information architecture.

---

# 15. Graceful Degradation

Overmind should remain useful when sophisticated components are unavailable.

If local inference fails:

> files and projects still exist.

If Paperclip is down:

> Substrate remains usable.

If vector search is unavailable:

> full-text search and filesystem navigation remain.

If a client disappears:

> server state remains.

If Overmind itself must be reconstructed:

> configuration and canonical project data should permit rebuilding it.

This principle is central to long-term durability.

---

# 16. Complexity Must Earn Its Place

Overmind must actively resist infrastructure gravity.

Avoid:

- distributed systems without a demonstrated need;
- multiple servers merely because hardware is available;
- custom software where mature open-source software exists;
- hidden state that cannot be reconstructed;
- overlapping systems of record;
- unnecessary SaaS dependencies;
- agent loops for jobs deterministic software performs better.

A useful rule is:

> **Every additional subsystem must either unlock a meaningful capability, remove significant recurring labor, or improve reliability enough to justify its maintenance cost.**

---

# 17. Initial Developer Experience

The first Overmind user experience can assume a technically capable operator.

Possible surfaces include:

```text
VS Code Remote SSH
Git
Markdown
Paperclip
Docker
MCP
browser dashboards
configuration files
CLI tools
```

This allows Overmind to become useful before a polished consumer interface exists.

---

# 18. Long-Term User Experience

The underlying architecture should eventually support a much simpler surface.

A future nontechnical Overmind interface might expose:

```text
Projects
Ask Overmind
Inbox
Files
Research
Automations
Media
Settings
```

The complexity of:

```text
models
agents
vector stores
containers
MCP
Git
task state
service APIs
```

can remain underneath.

The long-term product opportunity is:

> **make advanced open agent infrastructure feel like a coherent personal computer rather than a homelab.**

---

# 19. Relationship Between Overmind and Substrate

The distinction should remain clear.

## Substrate

Defines the portable project context.

```text
files
knowledge
relationships
project organization
metadata
context conventions
```

## Overmind

Hosts, operates, indexes, automates, and reasons over that context.

```text
server infrastructure
agents
models
automation
services
retrieval
workflow
human review
```

This produces a clean separation:

> **Substrate describes the world. Overmind operates on it.**

---

# 20. What Is Actually Novel

Overmind should not claim novelty in its individual components.

The interesting contribution is their composition.

Existing systems increasingly solve:

```text
agent orchestration
semantic retrieval
local inference
code agents
knowledge representation
automation
workflow review
media management
```

But these systems generally arrive as independent products and frameworks.

The user's burden is still often:

> install everything, configure everything, wire everything together, learn every abstraction, and become the administrator of the entire stack.

Overmind aims to turn those pieces into one coherent personal environment.

That means its meaningful intellectual work lies in:

- selecting strong components;
- defining clean boundaries;
- creating conventions between them;
- establishing interoperability;
- packaging useful defaults;
- preserving portability;
- reducing operational complexity;
- designing coherent human workflows.

---

# 21. Open Ecosystem Strategy

Overmind should assume that this ecosystem will change rapidly.

Many of the technologies now becoming relevant are extremely new:

- modern agent orchestration control planes;
- durable human-review workflows;
- open agent tool protocols;
- portable knowledge formats;
- local agentic coding models;
- inexpensive high-memory local inference;
- semantic and structural project indexing.

Overmind should therefore avoid locking itself to assumptions that may be obsolete within a year.

The correct response to a rapidly evolving ecosystem is **strong boundaries and loose coupling**.

---

# 22. Evaluation Rule for New Capabilities

Before adding a capability, ask:

1. What user problem does this solve?
2. Does an open implementation already exist?
3. Can we integrate it rather than recreate it?
4. Where should its canonical state live?
5. Is that state portable?
6. Can the component be replaced?
7. Does an LLM actually need to be involved?
8. Can deterministic software handle the routine path?
9. Does the feature reduce or increase long-term maintenance?
10. Would Overmind still make sense without this component?

If those questions do not have good answers, the feature probably does not belong in the core architecture.

---

# 23. Current Reference Composition

The emerging reference architecture is approximately:

```text
                       CLIENT DEVICES
              IDE / browser / mobile / CLI
                           │
                           ▼
                       OVERMIND
                           │
      ┌────────────────────┼─────────────────────┐
      │                    │                     │
      ▼                    ▼                     ▼
  Substrate             Paperclip             Services
 project context       agent control       media / automation
      │                    │                     │
      ▼                    ▼                     ▼
 indexing/retrieval    agent runtimes       deterministic tools
      │                    │                     │
      └───────────────┬────┴───────────────┬─────┘
                      │                    │
                      ▼                    ▼
                 local models        hosted models
```

Supporting infrastructure includes:

```text
Git
PostgreSQL
Docker
remote access
backups
networking
local storage
```

The exact implementations remain intentionally replaceable.

---

# 24. Success Criterion

Overmind succeeds when a user can think in terms of projects and desired outcomes rather than infrastructure.

A successful interaction looks like:

> “Look into whether this architecture makes sense.”

> “Implement the approved design.”

> “Find the papers relevant to this question.”

> “What work needs my attention?”

> “Make sure the new episode is available.”

> “Put this game on my travel device.”

Underneath those requests, dozens of specialized tools may participate.

The user should not need to manually orchestrate them.

---

# 25. Concise Thesis

> **Overmind is a self-hosted, open, composable personal compute environment for persistent projects and agentic work. It integrates best-of-breed open-source tools and emerging standards into a coherent system that can be accessed from many clients and extended without locking the user into a particular model, agent framework, knowledge store, or application.**

Its central architectural commitments are:

> **server-first**

> **client-agnostic**

> **open by default**

> **portable canonical state**

> **derived intelligence**

> **replaceable components**

> **agents for judgment, deterministic tools for execution**

> **composition over reinvention**

The intended outcome is not another AI application.

It is an environment in which open agentic tools begin to behave like parts of one personal computer.