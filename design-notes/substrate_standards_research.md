# Substrate as a Standard: Adoption Options and Recommendation

## Executive summary

Substrate does not need a new foundational metadata format. Two open specifications now cover most of the problem from complementary directions:

1. **Open Knowledge Format (OKF) v0.2** is an unusually close match for Substrate's human- and agent-facing layer. It defines a portable knowledge bundle as ordinary Markdown files with YAML frontmatter, is explicitly vendor-, model-, agent-, runtime-, and storage-neutral, and is designed for humans, agents, UIs, and search indexes to consume directly. OKF v0.2 also adds first-class provenance, verification, freshness, lifecycle, and attestation metadata.[^1][^2]
2. **RO-Crate 1.3** is a mature, Recommendation-status specification for describing arbitrary files, URLs, software, publications, datasets, people, workflows, and provenance as a linked-data graph. Its formal **profile** mechanism is specifically intended for communities to define narrower conventions on top of the base standard without creating a new incompatible format.[^3][^4]

The strongest recommendation is therefore **composition rather than invention**:

- Use **OKF as the canonical day-to-day knowledge convention** inside a Substrate project: project index, notes, decisions, paper summaries/references, status, context, and other human-authored or agent-maintained knowledge.
- Treat repositories, PDFs, datasets, figures, generated artifacts, and other non-Markdown resources as canonical files or external resources referenced from OKF.
- If Substrate eventually needs richer typed relations among arbitrary resources, create or generate an **RO-Crate view** and, only if justified, define a small **Substrate RO-Crate Profile** rather than inventing a new graph/schema language.
- Use **AGENTS.md** for behavioral instructions to coding agents, rather than putting agent-specific operational instructions into the Substrate metadata model.[^5]
- Use **MCP Resources/Tools** as an agent-access layer for search/read/context retrieval; MCP should not define the on-disk Substrate format.[^6]
- Consider **Agent Client Protocol (ACP)** for IDE-agent interoperability, but keep it outside the data model because it solves editor-to-agent communication, not project knowledge representation.[^7]
- Reuse domain standards such as **CodeMeta**, **CITATION.cff**, DOI/BibTeX, and W3C PROV where they already describe a resource well rather than creating duplicate Substrate-only metadata.[^8][^9]

This approach leaves a meaningful role for “Substrate” without requiring a monolithic Substrate application. **Substrate can be a profile, convention, and interoperability contract**: what constitutes a project workspace, how resources are referenced, what is canonical versus derived, what context an agent may expect, and how indexing/search systems should expose results with provenance.

The practical first experiment should be deliberately small: choose one real project, represent its knowledge layer as an OKF v0.2 bundle, add AGENTS.md to code repositories, use the open-source `openknowledge` CLI to validate/search/view/serve the bundle over MCP, and measure whether this already provides 80–90% of the desired Substrate experience before writing custom infrastructure.[^10][^11]

---

## 1. What the refined Substrate concept actually requires

The relevant target is not a “second brain” application. It is a portable project-context contract with several properties:

- **Human-readable without special software.** A project should remain intelligible as files in a directory or Git repository.
- **Agent-readable without a specific agent vendor.** Paperclip, an IDE agent, a local model, or a future agent should be able to understand the same project.
- **Project-centered.** Notes, decisions, artifacts, repository references, datasets, and contextual material primarily belong to project workspaces.
- **Capable of shared resources.** A paper, dataset, person, or repository can be relevant to multiple projects without physically duplicating the resource.
- **Indexable.** Search implementations should be able to build lexical, semantic, metadata, and code indexes over the workspace.
- **Provenance-preserving.** Retrieved or generated context should lead back to canonical sources.
- **Implementation-agnostic.** The standard should not require pgvector, Qdrant, Obsidian, Paperclip, VS Code, or a particular LLM.
- **Gracefully degradable.** If all AI software disappears, the project should still be a coherent collection of Markdown, code, PDFs, datasets, and normal metadata.
- **Extensible without fragmentation.** New project-specific concepts should not require inventing a mutually incompatible ecosystem.

That requirement set strongly favors adopting existing open formats and composing them by layer.

---

## 2. Candidate 1: Open Knowledge Format (OKF)

### What it is

Google Cloud introduced the **Open Knowledge Format** on June 12, 2026 as a vendor-neutral, human- and agent-friendly specification intended to formalize the emerging “LLM wiki” pattern.[^1] Version 0.2 followed on July 24, 2026 with expanded provenance, trust, freshness, lifecycle, and attestation concepts.[^2]

Its core is intentionally small: an OKF bundle is a directory of **Markdown files with YAML frontmatter**. The current v0.2 specification says there is no schema registry, no central authority, and no required tooling. A bundle can live in Git, on a filesystem, behind a static file server, or inside another product.[^12]

The specification explicitly names humans, agents, UIs, search indexes, and deterministic code as consumers. It also explicitly avoids prescribing storage, serving, query infrastructure, a fixed concept taxonomy, or a model/runtime.[^12]

That is almost exactly the architectural boundary Substrate wants.

### Why it maps well to Substrate

An OKF concept can carry fields such as:

- `type`
- `title`
- `description`
- `resource`
- `tags`
- provenance sources
- generator identity/time
- verification records
- lifecycle status
- staleness/freshness signals

The body remains ordinary Markdown. Relationships between concepts can be expressed with normal links. A bundle can also use `resource` or source references to point to underlying assets outside the Markdown representation.[^12]

A Substrate project could therefore look like:

```text
projects/gather/
├── index.md
├── status.md
├── decisions/
│   ├── a2ui-boundary.md
│   └── model-selection.md
├── research/
│   ├── human-in-loop-segmentation.md
│   └── xforms-engine.md
├── papers/
│   └── references.md
├── artifacts/
└── repos/
    ├── gather-mobile/
    └── gather-web/
```

The Markdown files would be ordinary OKF concepts. A paper note might point to a DOI or a canonical PDF; a project decision might cite the paper note; an agent-created summary could declare what produced it and when it should be considered stale.

This is considerably better than creating `substrate.yaml` from scratch unless Substrate discovers requirements OKF genuinely cannot express.

### Particularly valuable feature: machine-maintained knowledge trust

The v0.2 additions are unusually relevant to an agent-operated workspace. A knowledge base continuously maintained by agents needs a way to distinguish:

- human-authored versus machine-generated content;
- current versus stale content;
- verified versus unverified claims;
- source-derived versus speculative summaries;
- canonical resources versus generated projections.

OKF v0.2 directly targets that problem with provenance, `generated`, `verified`, lifecycle, freshness, and attestation conventions.[^2][^12]

A Substrate-specific convention could say, for example, that generated project capsules MUST identify their source files and generation time, and SHOULD carry a staleness policy. That is far more interoperable than inventing custom frontmatter keys privately.

### Important limitation: relationships are intentionally weakly typed

OKF deliberately remains minimal. It does not try to become a universal ontology. The specification therefore does not give us a rich typed graph for statements such as:

- Paper A **supports** Decision B.
- Repository C **implements** Design D.
- Dataset E **was generated by** Workflow F.
- Artifact G **supersedes** Artifact H.

Plain links create graph edges, but their semantics are generally expressed in prose rather than a strongly typed relationship model.

For most notes and project context, this is a feature: it keeps authoring simple. For machine reasoning across heterogeneous resources, it can become a limitation. That is where RO-Crate becomes complementary rather than competitive.

### Maturity risk

OKF is extremely young. It was introduced only in June 2026 and reached v0.2 in July.[^1][^2] Google is already integrating it into Knowledge Catalog and explicitly positioning bundles as exchangeable agent context, but the independent ecosystem is still emerging.[^13]

That means Substrate should rely on **the plain Markdown/Git portability**, not on the permanence of any particular OKF implementation. Fortunately, that is exactly how the specification is designed.

**Assessment: strongest candidate for the canonical human/agent knowledge convention.**

---

## 3. Candidate 2: RO-Crate 1.3

### What it is

RO-Crate is a much more mature specification for packaging and describing “research objects.” Version **1.3**, published June 22, 2026, is a formal Recommendation from the RO-Crate community.[^3]

An RO-Crate is typically a directory tree containing `ro-crate-metadata.json`, a JSON-LD document that describes the crate and its resources. Unlike OKF, its model is explicitly designed to treat arbitrary files and addressable resources as entities. The graph can describe files, URLs, software, people, organizations, publications, datasets, workflows, licenses, provenance, and relationships among them.[^3]

That maps unusually well onto the broader Substrate resource world:

```text
Project
├── Git repository
├── PDF paper
├── dataset
├── notes
├── experiment output
├── figure
├── software environment
└── people / organizations / provenance
```

### The critical feature: profiles

RO-Crate has a formal **profile** mechanism specifically for the problem Substrate is considering.[^4]

A profile can define:

- which entity types are expected;
- which properties are required or recommended;
- additional vocabularies;
- validation rules;
- packaging conventions;
- versioned conformance identifiers;
- relationships to other profiles.

Crates declare profile conformance via `conformsTo`, and a crate may conform to multiple profiles.[^4]

This suggests a powerful alternative to publishing a new “Substrate specification” from zero:

> **Substrate could become an RO-Crate Profile describing a project workspace.**

Such a profile might define expectations for entities such as:

- Project
- Repository / SoftwareSourceCode
- ScholarlyArticle
- Note / CreativeWork
- Decision
- Dataset
- Artifact
- Person / Organization
- generated context projections

The profile could reuse schema.org, CodeMeta, PROV-O, and other existing vocabularies and introduce only the minimum new terms needed.

### Why RO-Crate is stronger than OKF for resources

RO-Crate is much better when the important object is not Markdown.

A 40-page PDF, a model checkpoint, an image, a source repository, a dataset, or an external DOI can be directly represented as a typed entity with metadata and relationships. There is no need to pretend every resource is fundamentally a wiki page.

This is attractive for shared papers. Substrate could maintain one canonical paper resource and have multiple project crates or project concepts reference it. The physical location of the PDF does not need to determine the semantic project membership.

### Why RO-Crate should probably not be the daily authoring surface

Its canonical metadata is JSON-LD. That is machine-friendly and interoperable, but substantially less pleasant than Markdown + frontmatter for ordinary project work.

A human should not have to manually edit a large `@graph` every time a design note becomes relevant to another project. An IDE agent can manipulate JSON-LD, but doing so makes the metadata graph feel like infrastructure rather than an ordinary shared workspace.

Therefore, RO-Crate is strongest as:

- a **derived representation/export** generated from simpler canonical conventions; or
- a formal profile layer for relationships that need stronger semantics and validation.

It does not need to replace OKF's authoring ergonomics.

### Ecosystem and maturity

RO-Crate has independent libraries and tooling. `ro-crate-py`, for example, can create and consume crates from Python and is Apache-2.0 licensed.[^14] The specification itself is also Apache-2.0.[^15]

This maturity matters if Substrate eventually wants a standard that can survive beyond one home-server implementation.

**Assessment: strongest candidate for the formal resource graph/profile layer; too heavy to require for every daily edit.**

---

## 4. OKF and RO-Crate are complementary

The two specifications optimize for almost opposite ends of the problem:

| Requirement | OKF v0.2 | RO-Crate 1.3 |
|---|---|---|
| Pleasant human authoring | **Excellent** | Moderate/poor by hand |
| Plain Markdown/Git | **Native** | Metadata is JSON-LD |
| Agent-readable | **Excellent** | Excellent |
| Arbitrary files first-class | Reference-oriented | **Excellent** |
| Typed relationships | Minimal | **Strong** |
| Provenance | Good, simple conventions | **Rich graph model** |
| Community/profile extension | Loose conventions | **Formal Profiles** |
| Research/software metadata | Generic | **Strong** |
| Search/index implementation mandated | No | No |
| Runtime/agent vendor mandated | No | No |
| Maturity | Very young | **Mature** |

The cleanest model is therefore:

```text
CANONICAL HUMAN WORK SURFACE
OKF Markdown + Git + ordinary resources
              │
              │ derive / project
              ▼
FORMAL RESOURCE GRAPH WHEN NEEDED
RO-Crate / Substrate RO-Crate Profile
              │
              ▼
DERIVED INDEXES
full text / embeddings / code maps / graph
              │
              ▼
AGENT ACCESS
MCP / filesystem / IDE agent interfaces
```

Crucially, the RO-Crate representation should initially be **generated**, not independently hand-maintained. Two manually maintained metadata sources would create drift and defeat the purpose of a portable convention.

---

## 5. Complementary standards that should remain separate layers

### AGENTS.md: behavior and working instructions

AGENTS.md is a simple open format that acts as a predictable “README for agents.” It is intended for setup commands, testing requirements, style rules, repository boundaries, and similar coding-agent instructions.[^5] Its public site reports adoption across tens of thousands of open-source projects.[^16]

Substrate should use it rather than inventing agent-specific instruction fields.

A project can therefore separate:

```text
OKF / Substrate knowledge
“What is true about this project?”

AGENTS.md
“How should a coding agent behave while working here?”
```

That separation prevents Paperclip, VS Code, Codex, Claude Code, or another agent runtime from becoming part of the knowledge format itself.

### MCP: runtime access, not storage

The Model Context Protocol provides a standardized runtime surface for exposing resources and tools to agents. For Substrate, an MCP server could provide operations such as:

```text
substrate.search(project, query)
substrate.read(uri)
substrate.references(project)
substrate.context(project, task, budget)
```

MCP resource URIs are a suitable transport-level identity for files and other context, but MCP should **not** define how the underlying workspace is stored.

A current design nuance matters: the MCP **Roots** feature is deprecated in the 2026 specification line. New Substrate integration should therefore use explicit tool parameters, resource URIs, and server configuration rather than building a dependency around MCP Roots.[^6][^17]

### ACP: IDE-agent interoperability

The Agent Client Protocol standardizes communication between code editors/IDEs and coding agents and supports local and remote scenarios.[^7] It is useful for the requirement that Substrate remain **work-context agnostic**: an agent should not need VS Code-specific internals to work on the project.

However, ACP is an access/control protocol, not a project metadata format. Substrate should remain useful whether or not ACP is present.

### CodeMeta and CITATION.cff: reuse software metadata

CodeMeta provides a JSON-LD representation for software metadata built around schema.org and currently publishes 3.x contexts.[^8] CITATION.cff provides a human- and machine-readable format for software citation and is directly recognized by common development tooling such as GitHub.[^9]

If a repository already contains `CITATION.cff` or CodeMeta, Substrate should **reference/ingest it**, not copy its fields into a new Substrate schema.

### W3C PROV-O: provenance vocabulary when richer semantics are needed

PROV-O is the W3C Recommendation for interoperable provenance and defines the core Entity/Activity/Agent model.[^18] RO-Crate can coexist with or specialize provenance vocabulary where needed.

Substrate should not recreate its own generalized provenance ontology.

---

## 6. A surprisingly useful existing implementation: Open Knowledge CLI

The independent `openknowledge-sh/openknowledge` project is an Apache-2.0 CLI around OKF bundles.[^10] It is very young and currently small, so it should not become a hard architectural dependency. But it already implements a remarkable fraction of the Substrate MVP experiment:

- validate an OKF bundle;
- search it;
- browse it with a local viewer;
- query it;
- export HTML, JSON, graph, and RDF representations;
- connect multiple sources;
- expose it over MCP;
- invoke agent workflows.[^10][^11]

Most interestingly, its MCP search tool is **explicitly token-budgeted**: the current implementation defaults to about 2,400 estimated tokens and 12 sources, with configurable limits.[^11]

That is directly aligned with the Substrate indexing goal:

> retrieve enough context for reliable work without repeatedly placing an entire project into an agent prompt.

The tool also follows a useful architectural rule: viewer, search, MCP, exports, and agents operate over the **same knowledge base** rather than maintaining incompatible representations.[^19]

For an MVP experiment, that is more valuable than writing a custom pgvector service immediately.

### Commonplace: proof that the same files can power a human UI

Commonplace is an extremely young open-source wiki that stores its canonical content as an OKF-compatible Git repository. It provides a Markdown editor, knowledge graph, and an MCP surface while keeping the frontend stateless relative to the Git source.[^20]

It is far too new to make a foundational dependency, but it proves a useful point: the same OKF project can support both a human-readable wiki/browser and agent access without creating a proprietary storage model.

That is almost exactly what Substrate wants for papers and notes.

---

## 7. Papers and shared resources

The refined Substrate model needs to avoid forcing a paper to belong physically to exactly one project.

A clean solution is to separate **resource identity** from **project relevance**.

For example:

```text
library/papers/
└── 10.1234-example.pdf

projects/gather/
└── research/hitl-segmentation.md

projects/thesis/
└── literature/segmentation.md
```

The two OKF concepts can both reference the same canonical DOI/PDF resource. An index can treat those references as project membership edges without duplicating the PDF.

If simple links/tags are sufficient, OKF alone can represent this convention. If Substrate later needs explicit semantics such as:

```text
Paper A --supports--> Decision B
Paper A --evaluates--> Method C
Paper A --relevantTo--> Project D
```

then RO-Crate's typed resource graph and profile mechanism are a more appropriate extension point than inventing new YAML relationship syntax.

A future human paper browser could simply be another consumer of the same resource metadata/index. It does not need to own the paper library.

---

## 8. What Substrate should standardize

If Substrate becomes shareable, its useful contribution is likely **not** a new serialization format. It is a narrower interoperability profile for project work.

A Substrate convention could specify:

### Project identity

Every project has a stable identifier, name, root, status, and optional relationships to parent/related projects.

### Canonical resource classes

A minimum vocabulary/convention for:

- project;
- repository;
- note;
- decision;
- paper/publication;
- dataset;
- artifact;
- reference;
- person/organization;
- generated context/capsule.

Where an established vocabulary already exists, Substrate maps to it rather than replacing it.

### Project relevance

Resources can be project-local or shared. Project membership is semantic, not determined solely by physical directory placement.

### Canonical versus derived state

Canonical:

- source files;
- repositories;
- notes;
- papers;
- decisions;
- datasets;
- artifacts intended for preservation.

Derived/rebuildable:

- embeddings;
- vector indexes;
- lexical indexes;
- repo maps;
- extraction caches;
- chunk stores;
- temporary agent worktrees;
- automatically generated context summaries unless intentionally promoted.

### Provenance requirements

Search/index results SHOULD identify canonical source URI/path and sufficient location metadata to reopen the source. Generated knowledge SHOULD record source and generation/verification information using existing OKF/PROV conventions.

### Context-budget behavior

Indexing implementations SHOULD support bounded retrieval rather than treating maximal context as optimal.

### Agent-neutral access

Implementations MAY expose MCP, direct filesystem access, HTTP APIs, ACP-integrated clients, or other mechanisms. None is normative for the on-disk format.

This is a genuinely shareable standard surface.

---

## 9. What Substrate should *not* standardize yet

Avoid turning implementation preferences into interoperability requirements.

Substrate v0.x should not require:

- a particular vector database;
- a particular embedding model;
- a particular chunk size;
- Postgres, pgvector, Qdrant, or OpenSearch;
- Paperclip;
- VS Code;
- Obsidian;
- a particular local LLM;
- a particular agent framework;
- a particular directory name for every artifact category;
- a single human UI;
- one canonical search ranking algorithm.

Those are reference-implementation choices, not project-context semantics.

This is especially important because the AI tooling layer is changing much faster than Markdown, Git, URIs, JSON-LD, and established metadata vocabularies.

---

## 10. Recommended architecture

### Layer 1 — Canonical project/work surface

Use normal directories, Git repositories, Markdown, PDFs, data files, source code, and other native formats.

### Layer 2 — OKF knowledge convention

Use OKF v0.2 for project indexes, notes, decisions, status, resource summaries, source/provenance metadata, and human/agent-readable links.

### Layer 3 — Domain metadata reuse

Recognize DOI/Crossref/BibTeX for papers, CodeMeta/CITATION.cff for software, and other established metadata when present.

### Layer 4 — Optional RO-Crate projection/profile

Generate RO-Crate metadata when richer resource typing, packaging, provenance, or interoperability is useful. Define a Substrate RO-Crate Profile only after real project usage identifies stable semantics that deserve formalization.

### Layer 5 — Derived retrieval/indexes

Implementations may build:

- full-text indexes;
- embeddings/vector stores;
- code-symbol maps;
- citation graphs;
- metadata indexes;
- generated project capsules.

These are always rebuildable from canonical resources.

### Layer 6 — Agent access

Expose bounded search/read/context through MCP or another replaceable protocol. Keep tool-specific behavioral instructions in AGENTS.md and similar established conventions.

### Layer 7 — Clients

Any number of clients can consume the same project:

- VS Code / IDE agents;
- Paperclip agents;
- human wiki/browser;
- Obsidian;
- command line;
- local search UI;
- future tools.

No client becomes the owner of Substrate.

---

## 11. Proposed Substrate MVP experiment

Before writing custom indexing infrastructure, run one real project through the existing ecosystem.

### Phase A — Choose a demanding project

Use a project that contains:

- multiple repositories;
- design decisions;
- papers;
- notes;
- generated artifacts;
- enough historical context that retrieval is actually useful.

### Phase B — Create an OKF project layer

Do not reorganize every underlying file immediately. Create a compact OKF knowledge surface that references existing canonical resources.

Example:

```text
project/
├── index.md
├── status.md
├── decisions/
├── research/
├── references/
├── AGENTS.md
└── repos/
```

Use OKF v0.2 metadata rather than creating new frontmatter conventions unless necessary.

### Phase C — Pilot existing tooling

Use Open Knowledge CLI to:

1. validate the bundle;
2. search it with explicit token budgets;
3. view it locally;
4. expose it read-only through MCP;
5. connect an IDE agent and a Paperclip/local agent to the same bundle.[^10][^11]

### Phase D — Test the real questions

Measure whether agents can answer tasks such as:

- “Where did we decide the model-selection boundary?”
- “Which papers support this design?”
- “What repository symbols implement this architecture?”
- “What changed since the current project status note was generated?”
- “Give me a 2,000-token context package for this coding task.”

Measure retrieval quality, tokens consumed, stale-result rate, and how often the agent still has to crawl large directory trees.

### Phase E — Add only the missing layer

If exact code search is weak, add Aider/Tree-sitter-style repo maps.

If semantic retrieval is weak, add a vector index.

If shared resources and relationships are too ambiguous, prototype an RO-Crate projection.

If typed relationships become stable and valuable across projects, draft a Substrate RO-Crate Profile.

This sequence makes custom implementation evidence-driven.

---

## 12. Decision matrix

| Option | Fit | Lock-in risk | Maturity | Human ergonomics | Machine semantics | Recommendation |
|---|---:|---:|---:|---:|---:|---|
| Invent Substrate format | Potentially perfect | Medium | None | Can design | Can design | **Do not do yet** |
| OKF only | Very high | Very low | Young | **Excellent** | Moderate | **Adopt for MVP** |
| RO-Crate only | High | Very low | **High** | Moderate | **Excellent** | Use selectively |
| OKF + generated RO-Crate | **Highest** | Very low | Mixed | **Excellent** | **Excellent** | **Best long-term direction** |
| Existing second-brain app schema | Medium | Higher | Varies | Varies | Varies | Avoid as foundational format |
| MCP as “the standard” | Low for storage | Low | Evolving | N/A | Runtime only | Use as access layer |

---

## 13. Recommendation

The current evidence argues strongly **against inventing Substrate from scratch**.

The preferred near-term definition is:

> **Substrate is a project-context interoperability profile built primarily on Open Knowledge Format conventions, normal files/Git, and established domain metadata, with optional RO-Crate projection for richer typed resource graphs and MCP for runtime agent access.**

This leaves a valuable open-source contribution available without duplicating existing standards.

If the convention proves useful across real projects, the shareable deliverable might eventually be:

```text
Substrate Profile v0.1
├── normative conventions
├── OKF mapping
├── optional RO-Crate profile
├── JSON/YAML validation where useful
├── example projects
├── interoperability tests
├── indexing/retrieval recommendations
└── reference adapters
```

The key is that a conforming workspace does **not** require the Overmind server, Paperclip, a Substrate daemon, or any particular database. Overmind can be the reference implementation proving that the convention works across human, IDE-agent, research, and local-agent workflows.

The real differentiator is therefore not a new database or knowledge application. It is a **well-defined, portable project-context contract that composes existing standards into a workspace both people and agents can reliably share.**

---

## Sources

[^1]: Google Cloud, “Introducing the Open Knowledge Format,” June 12, 2026. https://cloud.google.com/blog/products/data-analytics/how-the-open-knowledge-format-can-improve-data-sharing
[^2]: Google Cloud, “Open Knowledge format v0.2 tackles agentic trust,” July 24, 2026. https://cloud.google.com/blog/products/data-analytics/okf-v0-2-adds-trust-signals/
[^3]: Research Object Crate community, “RO-Crate Metadata Specification 1.3,” June 22, 2026. https://www.researchobject.org/ro-crate/specification/1.3/
[^4]: Research Object Crate community, “RO-Crate Profiles.” https://www.researchobject.org/ro-crate/specification/1.3/profiles.html
[^5]: AGENTS.md project, “AGENTS.md — a simple, open format for guiding coding agents.” https://agents.md/
[^6]: Model Context Protocol, “SEP-2577: Deprecate Roots, Sampling, and Logging.” https://modelcontextprotocol.io/seps/2577-deprecate-roots-sampling-and-logging
[^7]: Agent Client Protocol, “Introduction.” https://agentclientprotocol.com/get-started/introduction
[^8]: CodeMeta Project, “The CodeMeta JSON-LD Representation.” https://codemeta.github.io/jsonld/
[^9]: Citation File Format. https://citation-file-format.github.io/
[^10]: Open Knowledge, GitHub repository. https://github.com/openknowledge-sh/openknowledge
[^11]: Open Knowledge, “openknowledge mcp.” https://github.com/openknowledge-sh/openknowledge/blob/main/Wiki/features/commands/mcp.md
[^12]: GoogleCloudPlatform/knowledge-catalog, “Open Knowledge Format v0.2 Specification.” https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md
[^13]: Google Cloud, “Using OKF with Knowledge Catalog to serve context for agents,” August 26, 2026. https://cloud.google.com/blog/products/data-analytics/scale-okf-bundles-across-an-organization-with-knowledge-catalog
[^14]: ResearchObject, `ro-crate-py`. https://github.com/ResearchObject/ro-crate-py
[^15]: ResearchObject, RO-Crate repository/license. https://github.com/ResearchObject/ro-crate
[^16]: AGENTS.md project homepage, adoption information. https://agents.md/
[^17]: Model Context Protocol, “The 2026-07-28 Specification.” https://blog.modelcontextprotocol.io/posts/2026-07-28/
[^18]: W3C, “PROV-O: The PROV Ontology,” W3C Recommendation, April 30, 2013. https://www.w3.org/TR/prov-o/
[^19]: Open Knowledge, “Tooling Model.” https://github.com/openknowledge-sh/openknowledge/blob/main/Wiki/features/tooling-model.md
[^20]: Commonplace Wiki, GitHub repository. https://github.com/commonplace-wiki/commonplace
