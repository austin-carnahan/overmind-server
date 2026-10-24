# Kerrigan MVP — OpenClaw Resident Operator + Paperclip Work Control

## Status

Current implementation design for Kerrigan V1.

This note supersedes the **runtime and interaction assumptions** in the earlier Kerrigan designs, while preserving their core operating principles:

- broad jurisdiction does not imply broad standing privilege;
- authorize objectives, not individual commands;
- durable changes return to canonical state;
- agents reason, deterministic systems verify;
- discover and reuse before inventing new machinery.

The goal is deliberately small: **get Kerrigan operating usefully on Overmind within a short implementation window, then let real use drive the next layer of architecture.**

---

## 1. V1 Goal

Kerrigan is Overmind's first persistent resident agent.

A successful V1 should let the human say things like:

> Inspect why this service is unhealthy and fix it if the repair is routine.

> Implement this approved configuration change and verify it.

> Check upstream documentation before changing anything.

> Turn the successful repair into a runbook.

Kerrigan should be able to carry those requests through without requiring the human to manually shuttle context between chat, repositories, SSH sessions, documentation, and Paperclip.

V1 is successful when the normal loop becomes:

```text
human intent
    ↓
Kerrigan
    ↓
retrieve relevant project context
    ↓
inspect live state
    ↓
research if needed
    ↓
change canonical source
    ↓
apply / deploy
    ↓
deterministically verify
    ↓
record durable outcome
```

---

## 2. Architecture

```text
                         HUMAN
                           │
                  chat / OpenClaw UI
                           │
                           ▼
                       KERRIGAN
                    OpenClaw agent
                           │
                 Claude or Codex
                           │
          ┌────────────────┼─────────────────┐
          │                │                 │
          ▼                ▼                 ▼
      Substrate        Web / Browser      Ops Tools
   project context      + subagents      shell / Git /
      + runbooks                         Docker / systemd
          │
          └────────────────┬─────────────────┘
                           │
                           ▼
                        OVERMIND

                     PAPERCLIP
              structured work-control plane
              tasks / approvals / history
```

### OpenClaw owns the resident-agent experience

OpenClaw provides:

- Kerrigan's persistent conversational session;
- model/runtime configuration;
- tool access;
- MCP integrations;
- web/browser access;
- subagent spawning;
- reusable skills;
- access from additional channels later if useful.

Kerrigan should remain useful even when no Paperclip issue is active.

### Paperclip owns structured work

Paperclip is used where explicit work structure adds value:

- implementation tasks;
- operational incidents;
- scheduled work;
- approvals;
- review;
- delegation;
- execution history;
- work that should remain auditable after the conversation ends.

Paperclip is **not** Kerrigan's primary chat interface and is **not** the canonical store for Overmind knowledge.

Kerrigan may receive a Paperclip assignment or create/link a work item when a conversation becomes substantial enough to warrant durable tracking.

### Claude / Codex provide reasoning

Use existing subscription-backed Claude or Codex access initially.

Do not introduce API billing, local models, Hermes, or additional runtime layers unless actual usage creates a reason.

---

## 3. Kerrigan's V1 Role

Kerrigan is the resident operator for the Overmind environment.

Initial responsibilities:

- inspect service and host state;
- inspect relevant logs and configuration;
- work directly with canonical infrastructure repositories;
- make bounded configuration changes;
- deploy and restart approved services;
- validate configuration before deployment;
- verify outcomes after changes;
- consult current upstream documentation when needed;
- capture successful repeated repairs as runbooks or skills;
- keep live state and canonical state reconciled;
- escalate actions outside granted authority.

V1 should focus primarily on the Overmind server itself.

Do not expand Kerrigan into a universal life assistant, researcher, project manager, or software-development organization during this phase.

---

## 4. Tools and Access

Kerrigan should begin with the smallest useful tool set.

### Read / inspect

- filesystem access to approved Overmind workspaces;
- Git status/history/diff;
- Docker/container state;
- systemd/service state;
- logs;
- process and resource inspection;
- mounted filesystem/storage inspection;
- existing health checks;
- existing runbooks and design notes.

### Modify / operate

- edit approved repository/config files;
- Git commit where appropriate;
- Docker Compose validation and deployment;
- restart/reload bounded services;
- rerun deterministic jobs or health checks;
- rebuild disposable indexes or caches where explicitly permitted.

### Research

Kerrigan gets direct:

- web search;
- web fetch;
- browser access.

For larger research tasks, Kerrigan may spawn **ephemeral subagents**.

Subagents should normally:

- have read-only project context;
- search documentation and the web;
- investigate alternatives or upstream changes;
- return concise findings and sources to Kerrigan;
- have no standing authority to mutate Overmind.

No dedicated Researcher agent is needed for V1.

---

## 5. Authority Model

Preserve the existing global action classes.

### Observe

Examples:

- read logs;
- inspect Git;
- inspect config;
- query status and health;
- read project context.

Default: **autonomous**.

### Routine

Examples:

- restart a service;
- retry an idempotent job;
- rerun a health check;
- rebuild a derived index;
- clear a safe temporary cache.

Default: **autonomous when inside the approved task scope**.

### Configuration

Examples:

- edit Compose/configuration;
- change application settings;
- update service images;
- modify Substrate conventions/config.

Default: **allowed only when the request or Paperclip task grants configuration authority**.

### Destructive

Examples:

- delete canonical files;
- purge important data;
- truncate databases;
- destructive migration.

Default: **explicit human approval**.

### Critical

Examples:

- firewall;
- SSH/access configuration;
- Tailscale;
- users/groups;
- partitions/filesystems;
- credential rotation;
- restore-over-live;
- OS upgrade.

Default: **explicit human approval**.

The operating model remains:

```text
broad role
+
bounded resources
+
task-scoped authority
+
global risk policy
```

not:

```text
Kerrigan has root
```

---

## 6. Canonical-State Rule

Kerrigan may make live changes while diagnosing or recovering a system, but completed work must end in the canonical source.

```text
live experiment / repair
        ↓
verify
        ↓
represent in repo / config / runbook
        ↓
validate again
        ↓
commit / record
```

Examples:

```text
Compose change     → infrastructure repo
runbook            → operational docs
Substrate decision → canonical design/config
service setting    → tracked config where practical
```

Kerrigan's memory, OpenClaw session history, and Paperclip history are **not** substitutes for canonical state.

---

## 7. Deterministic Verification

Kerrigan must not infer success solely from a successful command.

Examples:

```text
service change
→ health endpoint / service state passes

deployment
→ config validates + target service becomes healthy

media workflow
→ representative test artifact reaches expected state

Substrate change
→ index rebuild succeeds + representative retrieval works

backup workflow
→ restore verification succeeds
```

Where no deterministic verification currently exists, V1 may document that gap rather than building an elaborate monitoring platform immediately.

---

## 8. Minimal Substrate Needed for V1

Do not build a large Substrate platform before Kerrigan exists.

V1 Substrate is primarily **conventions over ordinary files**.

The minimum useful project structure is:

```text
overmind/
├── designs/
├── decisions/
├── references/
├── runbooks/
├── work/
└── project / agent guidance
```

Existing directory layout and repositories remain authoritative where already established. Do not reorganize working infrastructure merely to satisfy this conceptual structure.

### Minimal metadata

New project/work documents may use lightweight frontmatter:

```yaml
---
id: overmind-0042
type: design
stage: explore
project: overmind
related:
  - kerrigan
---
```

Initial lifecycle:

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

Do not require all historical documents to be migrated before V1.

### Retrieval

Start with:

- filesystem conventions;
- filenames and frontmatter;
- `rg` / lexical search;
- Git;
- direct document reads.

Do **not** require for V1:

- a vector database;
- a custom context server;
- a new knowledge graph;
- a custom project UI;
- semantic indexing of everything.

The first retrieval question is simply:

> Can Kerrigan reliably find the relevant design, decision, config, and runbook without the human manually pasting them into chat?

If not, improve the convention or retrieval layer based on observed failures.

---

## 9. Skills and Operational Learning

Repeated successful work should become reusable knowledge.

The progression is:

```text
novel task
   ↓
Kerrigan reasons through it
   ↓
successful verified procedure
   ↓
runbook and/or OpenClaw skill
   ↓
future execution becomes cheaper and more deterministic
```

Use a **runbook** when the procedure should remain understandable and useful outside OpenClaw.

Use an **OpenClaw skill** when procedural tool-use guidance materially improves future agent execution.

Often the same event may update both.

The desired long-term effect is **less repeated model reasoning for routine operations**, not more.

---

## 10. Paperclip Seam

Do not create a Paperclip issue for every conversational turn.

Use Paperclip when work becomes:

- multi-step and durable;
- scheduled;
- delegated;
- approval-sensitive;
- incident-like;
- important enough to audit or track to completion.

A simple handoff pattern:

```text
conversation with Kerrigan
        ↓
task becomes substantial
        ↓
Paperclip work item created / linked
        ↓
Kerrigan executes
        ↓
durable outputs return to canonical state
        ↓
Paperclip retains execution history
```

Substrate/project files own long-term project knowledge.

Paperclip owns active work state.

OpenClaw owns the resident conversational agent experience.

---

## 11. V1 Implementation Sequence

Keep the first implementation narrow.

### Step 1 — Run OpenClaw on Overmind

- install/configure OpenClaw;
- create Kerrigan;
- authenticate one primary model using an existing Claude or Codex subscription;
- establish a persistent chat surface.

### Step 2 — Give Kerrigan read-only operational visibility

Connect the known Overmind workspaces and basic inspection tools.

Verify Kerrigan can answer:

- what services are running;
- where their canonical config lives;
- whether a service is healthy;
- what recent relevant changes occurred;
- which existing design/runbook applies.

### Step 3 — Establish minimal Substrate conventions

- identify canonical design/runbook/work locations;
- add minimal metadata to new work;
- add agent/project guidance;
- ensure Kerrigan can retrieve context using ordinary search.

Do not perform a wholesale migration.

### Step 4 — Enable bounded routine operations

Permit a small set such as:

- service restart;
- Compose validation;
- approved service deployment;
- safe job retry;
- deterministic health verification.

Keep destructive and critical actions blocked.

### Step 5 — Connect Paperclip

Use Paperclip for one real implementation task or incident.

Prove the seam:

```text
task
→ Kerrigan
→ implementation
→ verification
→ canonical update
→ Paperclip completion record
```

### Step 6 — Exercise research subagents

Give Kerrigan a task that requires checking current upstream documentation.

Verify that an ephemeral research subagent can:

- gather relevant evidence;
- remain read-only;
- return a useful concise result;
- avoid polluting Kerrigan's main context with unnecessary detail.

### Step 7 — Capture one learned procedure

Take one successful operation and turn it into a runbook and/or reusable OpenClaw skill.

That closes the first learning loop.

---

## 12. Initial Test Tasks

Prefer boring tasks with deterministic outcomes.

Good V1 tests:

1. **Inventory and explain one existing managed service.**
2. **Diagnose a deliberately simple service failure.**
3. **Perform one approved configuration change and deploy it.**
4. **Research an upstream version/configuration question before acting.**
5. **Implement one small Substrate convention in the Overmind project.**
6. **Convert one successful repair into a reusable runbook/skill.**

Avoid making the first task:

> Re-architect Overmind.

The first milestone is reliable operational glue, not maximal autonomy.

---

## 13. Explicit Non-Goals for V1

Do not add yet:

- dedicated Researcher or other permanent specialist agents;
- NemoClaw/OpenShell;
- Hermes;
- local model infrastructure;
- custom orchestration software;
- custom project-management UI;
- comprehensive semantic indexing;
- autonomous destructive actions;
- broad passwordless sudo;
- a universal capability graph;
- a complete migration of historical project files.

Each may be reconsidered later based on evidence from actual Kerrigan use.

---

## 14. V1 Success Criteria

Kerrigan V1 is working when all of the following are true:

- Kerrigan is persistently reachable through OpenClaw;
- Kerrigan can retrieve relevant Overmind design and operational context without manual copy/paste;
- Kerrigan can inspect live server state;
- Kerrigan can perform at least one bounded routine/configuration task;
- the result is deterministically verified;
- durable changes are represented in canonical state;
- one substantial task can be tracked through Paperclip;
- Kerrigan can delegate a read-only research task to a subagent;
- one successful workflow is captured as a reusable runbook or skill;
- destructive and critical actions remain outside autonomous authority.

The V1 thesis is:

> **OpenClaw gives Kerrigan a persistent body; Claude or Codex provides reasoning; Substrate provides durable context; Paperclip provides structured work control; Overmind's existing tools and services provide the capabilities.**
