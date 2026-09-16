# Substrate — Early Design Notes

## Overview

Substrate is a project-context layer for human and agent collaboration.

Its goal is not to invent a new knowledge-management format, project-management system, documentation framework, or agent protocol. Instead, Substrate composes existing open conventions and tools into a coherent, repository-native system for maintaining durable project context.

The core problem is simple:

> Humans and agents accumulate significant working knowledge while developing a project, but much of that context remains trapped in individual conversations, sessions, tools, or people's heads.

Git preserves changes. READMEs explain projects. Issue trackers coordinate work. Documentation records selected knowledge. Agent instruction files tell agents how to behave.

What is missing is a lightweight way to make accumulated project understanding durable, searchable, portable, and reusable across humans, agents, IDEs, and work sessions.

Substrate aims to provide that layer.

---

## Design Principles

### Reuse before invention

Substrate should adopt established open conventions wherever they already solve a problem adequately.

Before defining a new Substrate primitive, ask whether an existing standard or convention already represents it.

Examples include:

- Git for history and collaboration
- Docs as Code for repository-local documentation
- Markdown for human-readable canonical text
- Open Knowledge Format for structured knowledge metadata
- `AGENTS.md` for portable agent instructions
- ADR / MADR for architectural and consequential decisions
- OpenSpec for specifications and managed change
- GitHub Spec Kit for structured specification-to-implementation workflows
- Diátaxis for documentation structure
- CODE and Double Diamond for knowledge and design-process concepts

Substrate should integrate these systems rather than replace them.

---

## Repository-native and tool-independent

Canonical project context should live in ordinary files inside or alongside the project.

A project should remain understandable after:

```text
git clone
```

even if Substrate itself is not installed.

Substrate may generate indexes, embeddings, graphs, summaries, caches, and other derived artifacts, but these must not become hidden sources of truth.

A useful rule is:

> Canonical state should be boring. Derived state may be sophisticated.

---

## Human-readable and agent-readable

Project context should work equally well for:

- a developer reading Markdown,
- a coding agent,
- a research agent,
- an IDE integration,
- a CLI tool,
- a future system that does not yet exist.

Substrate should therefore prefer open files, explicit relationships, stable metadata, and command-line interfaces over proprietary storage formats.

---

## Existing conventions as layers

Substrate can be understood as a composition layer over an existing ecosystem.

```text
Git / Docs as Code
        │
        ├── Markdown
        ├── OKF
        ├── AGENTS.md
        ├── ADR / MADR
        ├── OpenSpec
        ├── Spec Kit
        └── other project-native artifacts
                │
                ▼
             SUBSTRATE
                │
        ┌───────┼────────┐
        │       │        │
      Index   Search   Context
        │       │        │
        └───────┴────────┘
                │
                ▼
          Humans + Agents
```

Substrate's role is not primarily to define the files above. Its role is to understand how they relate and make them useful together.

---

## Knowledge lifecycle

Several existing frameworks provide useful language for thinking about how project context evolves.

Examples include:

```text
Capture → Organize → Distill → Express
```

and:

```text
Discover → Define → Develop → Deliver
```

Substrate does not necessarily need to impose either workflow literally.

The important shared idea is that project context has a lifecycle:

```text
uncertainty / input
        ↓
investigation
        ↓
distillation
        ↓
shared project understanding
        ↓
intentional change
        ↓
new observations and knowledge
```

Substrate should support this lifecycle without requiring one rigid directory taxonomy.

---

## Avoid a universal folder ontology

Early exploration considered top-level categories such as:

```text
knowledge/
research/
work/
operations/
```

and later verb-oriented models such as:

```text
explore/
define/
execute/
operate/
```

These were useful conceptual exercises, but Substrate should avoid making a novel folder taxonomy its central abstraction.

Different projects already have useful conventions.

A software project might contain:

```text
docs/
  adr/
  research/

openspec/
  specs/
  changes/
```

A research project might instead contain:

```text
papers/
experiments/
results/
docs/
```

Substrate should be able to understand both.

It may provide recommended defaults, but those defaults should remain optional and lightweight.

---

## Agent instructions

`AGENTS.md` should act as a universal entry point for agent behavior.

Rather than containing the entire project knowledge base, it should explain how agents are expected to interact with project context.

For example:

```text
Before substantial work:

- inspect existing project documentation;
- review relevant specifications and ADRs;
- search project context before inventing a new solution;
- treat exploratory research as evidence rather than settled truth.

During work:

- keep temporary reasoning ephemeral;
- update active specifications or plans when appropriate;
- record consequential decisions explicitly.

After substantial work:

- reconcile completed changes into current project truth;
- update durable documentation;
- preserve useful lessons;
- avoid storing raw conversation history as project knowledge.
```

Tool-specific instruction files can reference or mirror the same contract when necessary.

---

## Distill context, do not archive conversations

Agent conversations contain large amounts of temporary reasoning.

Substrate should not treat raw agent transcripts as the primary form of project memory.

Instead:

```text
ephemeral agent context
        ↓
      distill
        ↓
durable project artifact
        ↓
       Git
        ↓
future human or agent
```

A debugging session might therefore produce:

- an updated specification,
- a new ADR,
- a corrected runbook,
- a completed change record,
- or a short research note.

The conversation itself may be retained for debugging or provenance, but it should not be the main interface to project knowledge.

---

## Indexing

Substrate should build a disposable index over canonical project artifacts.

The index should be reconstructable at any time.

It may include:

- lexical search,
- embeddings,
- source-code symbols,
- imports and references,
- document metadata,
- OKF relationships,
- ADR links,
- specification relationships,
- test relationships,
- Git history,
- notebook structure,
- papers and research artifacts.

Embeddings are only one component.

Substrate should not reduce repository understanding to "vectorize the codebase."

A richer index may understand relationships such as:

```text
ADR-0017
    ↓ motivates

authentication specification
    ↓ modified by

oauth-refresh change
    ↓ implemented by

src/auth/refresh.ts
    ↓ tested by

tests/auth/refresh.test.ts
```

---

## Context retrieval

One of Substrate's most important capabilities should be task-specific context assembly.

For example:

```bash
substrate context \
  "implement refresh-token rotation" \
  --budget 6000
```

Rather than returning the nearest embedding chunks, Substrate should construct a coherent context package.

Example:

```text
Project orientation                 350 tokens
Current authentication spec         900
Relevant ADR                        550
Active change specification         800
Relevant source symbols           2100
Relevant tests                      900
Historical warning                  300
────────────────────────────────────────
Total                              5900
```

The objective is:

> Given a task and a context budget, provide the smallest coherent set of project information required to work effectively.

This is a stronger abstraction than generic semantic search.

---

## Bootstrap and validation

Substrate should make good project-context practices easy to adopt from day one.

Possible commands include:

```bash
substrate init
substrate check
substrate index
substrate search
substrate context
```

`substrate init` might:

- detect existing project conventions,
- create or update `AGENTS.md`,
- initialize optional ADR tooling,
- configure OpenSpec when desired,
- establish OKF-compatible metadata conventions,
- create a minimal documentation index.

It should adapt to the project rather than requiring the project to be reorganized around Substrate.

`substrate check` might validate relationships between existing standards:

```text
✓ AGENTS.md present
✓ ADRs conform to MADR
✓ OKF metadata valid
✓ OpenSpec changes consistent
⚠ completed change has not updated current spec
⚠ document references superseded ADR
⚠ imported research artifact lacks provenance
```

---

## Project views

Project-management interfaces should be treated as views over canonical project state rather than separate sources of truth.

A Kanban board, for example, might be derived from repository-native change or task artifacts.

```text
Repository state
      │
      ├── CLI
      ├── Kanban UI
      ├── IDE extension
      └── Agent interface
```

The interface is replaceable.

The project state is not.

External tools such as GitHub Issues, Linear, or Jira may be connected through adapters, but the project should remain usable if those integrations disappear.

---

## Research artifacts and paper ingestion

Academic papers are a natural Substrate input.

A paper-ingestion service could:

```text
PDF
 ↓
structured extraction
 ↓
OCR / figure understanding
 ↓
Markdown + structured document representation
 ↓
OKF metadata
 ↓
Substrate index
```

The resulting paper becomes both human-readable research material and machine-retrievable context.

Agents can then ask for a budgeted subset of a paper rather than injecting the entire PDF or Markdown conversion into a prompt.

The same model can extend to:

- notebooks,
- datasets,
- experiment reports,
- external documentation,
- design references,
- issue trackers,
- and other project evidence.

---

## Proposed scope

Substrate currently appears to have four core responsibilities.

### 1. Composition

Define how existing open project conventions fit together.

### 2. Bootstrap

Make those conventions easy to adopt in a new or existing project.

### 3. Index

Build a reconstructable structural, lexical, and semantic representation of project context.

### 4. Retrieve

Provide task-specific, token-budgeted context to humans and agents.

Substrate should avoid owning:

- source control,
- project-management methodology,
- an IDE,
- an agent framework,
- a vector database,
- model hosting,
- a proprietary knowledge format.

Those should remain replaceable components.

---

## Session notes — portability and collaboration framing (2026-09-15)

Tabled here mid-discussion to resume later. These are leanings from one design
conversation, not decisions — nothing below has been built or committed to.

### OKF: real, but very new — reuse the shape, not the authority

"Open Knowledge Format" (OKF) is a real, currently-existing spec, not the
Frictionless-Data-style thing this doc originally gestured at under the same
name. Published by Google Cloud, June 2026, v0.1: markdown files with a small
required YAML frontmatter (`type`, `title`, `description`, `resource`, `tags`,
`timestamp`) organized in directories, cross-linked via plain markdown links
into a knowledge graph. It formalizes exactly the informal
Obsidian/Hugo/LLM-wiki pattern this doc was already reaching for under
"hierarchical access/lookup, indexing."

Leaning: adopt the frontmatter *shape* now rather than inventing our own field
names — this is "reuse before invention" working as intended. But it's v0.1,
public for about a week at the time of this conversation, with no adoption
history — treat it as a tracked dependency to revisit at each version bump,
not a foundation to build validation logic tightly around. Don't let
`substrate check` assume today's field names survive to v1.0 unchanged.

### A self-critique: this session's own memory system is a placement anti-pattern

Claude Code's own per-project memory (an index file + frontmatter'd notes) was
raised as a working example of index+frontmatter in practice — but on
inspection it's a *bad* example of where that state should live: it's stored
in the tool's own private config directory, keyed by a hash of the working
directory, not in the repo. It doesn't survive `git clone`, and it's invisible
to any other agent or IDE that opens the same project. That's a direct
violation of this doc's own "repository-native and tool-independent"
principle. Lesson kept: copy the *mechanism* (index + frontmatter), not the
*placement*. Canonical Substrate state has to live inside the repository (or a
location that travels with it) for tool-switching continuity to actually work.

### Two portability problems, not one — likely two physical tiers

Three problems raised in conversation resolved into two distinct tiers plus a
scaffolding concern:

1. **Cross-tool continuity within one project** (open in VS Code + Codex today,
   Claude Code tomorrow, something else later) — addressed by tier placement
   alone, not a new mechanism: if canonical notes/index live as real files in
   the repo, any tool opening that repo sees the same accumulated context.
   Today's gap is that a lot of this state currently lands in a given tool's
   private, project-keyed config directory instead.

2. **Cross-project personal preferences** (tool/pattern preferences, style,
   recurring solutions — things you want with you in *every* project, not
   just one) — a genuinely separate, user-home-scoped tier. This is dotfiles
   territory (chezmoi/stow already solve "one canonical source, materialized
   into many tool-specific locations"). Several agent tools already have their
   own global-instructions file/location (e.g. a personal `CLAUDE.md` outside
   any project) that don't agree on filename or path. Leaning: a canonical
   `~/.substrate/skills/`-style source, frontmatter'd the same way as the
   project tier, with a thin adapter/symlink step materializing it into each
   tool's expected global location — the same trick AGENTS.md itself
   increasingly relies on for tools that don't read it natively yet.

3. **Off-the-shelf organization patterns for humans** (avoid the "dump
   everything in design-notes/" failure mode without being prescriptive) —
   this collapses into the pluggable-manifest idea already in this doc for
   decision logs (MADR vs. other patterns), just generalized: a small root
   manifest declares which information-architecture *preset* a project uses
   (e.g. Diátaxis, ADR/MADR-lite, a research-notebook shape, or fully custom),
   `substrate init --pattern <name>` scaffolds it, and `substrate check`/
   `index` only ever read the manifest — never a hardcoded taxonomy. Keeps
   "avoid a universal folder ontology" intact while still giving a new project
   a good default instead of a blank folder.

### Working shape so far (not final)

Two tiers — repo-local (project) and user-home (portable preferences) — each
using the same OKF-shaped frontmatter, each governed by a small manifest, with
a preset library for the repo tier's information architecture and an
adapter/symlink layer for the user tier reaching into each agent tool's own
global-config convention. Still open: the actual manifest schema, the adapter
mechanics per tool, and the preset library's initial contents.

---

## Working definition

> **Substrate is a batteries-included project context layer that composes existing open standards and repository conventions, builds disposable indexes over project knowledge and source material, and allows humans and agents to reconstruct the context they need to work effectively.**

A useful analogy is a Linux distribution:

Substrate does not need to invent all of its components.

Its value comes from selecting strong existing pieces, providing sensible defaults, making them interoperate, and supplying the missing glue.

The central design constraint is therefore:

> **Discover and reuse before inventing.**