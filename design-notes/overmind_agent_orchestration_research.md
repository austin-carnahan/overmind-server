# Overmind Agent Orchestration & Human Review: Open-Source Landscape

## Executive Summary

Overmind’s proposed “chief of staff → planning → independent review → implementation/research → review → human attention inbox” workflow is no longer a capability that obviously requires a custom application.

The most important finding is that **Paperclip itself now implements most of this design directly**. Its current control plane includes project-linked durable issues, agent workspaces, execution policies with review and approval stages, structured human interactions, an attention queue, a Decisions surface, audit history, routines, and a plugin/adapter model. Recent Paperclip releases add first-class propose/decide workflows and an explicit attention queue for work requiring human input. Its current repository also contains pipeline machinery with review stages that can approve, reject, or request changes back to an earlier stage.[^1][^2][^3]

That substantially changes the recommended Overmind architecture. Rather than building a separate “Overmind Inbox,” the default should be:

1. **Paperclip is the canonical work/orchestration/review system of record.**
2. **Substrate is the canonical project-context/workspace standard.**
3. A thin Overmind integration maps Substrate projects and context into Paperclip work.
4. Paperclip-native execution policies, Decisions, issue interactions, and—when sufficiently mature—Pipelines implement staged agent workflows and human review.
5. External systems are added only for capabilities Paperclip does not provide well.

The strongest external reference implementations are:

- **LangGraph + Agent Inbox** — the clearest independent reference for durable human-in-the-loop interrupts and an inbox UI.
- **HumanLayer** — the strongest orchestrator-neutral pattern for making “ask a human” and “require approval” capabilities part of the tool boundary.
- **Temporal** — the strongest general-purpose durable workflow foundation if Overmind eventually needs workflow guarantees beyond Paperclip.
- **Mastra** — an attractive TypeScript workflow/agent runtime with suspend/resume and human-in-the-loop support that can sit behind a Paperclip HTTP adapter.
- **n8n** — useful as an integration and notification edge, especially for Telegram/email/Slack-style approval notifications, but not a strong candidate for the canonical agent work system.

The practical recommendation is therefore **adopt before building**. Pilot the complete Overmind workflow using Paperclip primitives first. Only introduce a separate human-review service if the pilot reveals a concrete abstraction boundary that Paperclip cannot satisfy.

---

## 1. Target Capability

The desired Overmind experience is not simply “multi-agent chat.”

A user should be able to provide a high-level request such as:

> Investigate whether Gather should move model storage into a shared service and implement it if appropriate.

The system should be capable of:

- determining the relevant project;
- gathering project context from Substrate;
- decomposing the request;
- delegating planning or research;
- performing independent review;
- requesting human input only at meaningful decision points;
- resuming after that input;
- implementing or researching;
- reviewing the result;
- cycling through bounded revisions;
- surfacing completed or blocked work in a durable cross-project attention queue.

The desired user-facing abstraction is:

> **What needs my attention?**

not:

> Which agent terminal or chat thread was doing this?

That distinction is important when comparing existing systems. Many frameworks support multiple agents, but comparatively few provide durable work objects, review state, and a human attention surface.

---

## 2. Paperclip: Much Closer to the Desired System Than Expected

### 2.1 Paperclip is already a control plane rather than an agent framework

Paperclip describes itself as an orchestration/control-plane system for teams of heterogeneous agents. Its current README explicitly supports Claude Code, Codex, Cursor/CLI agents, Bash, HTTP/web agents, and external adapter plugins. Projects have workspaces; issues carry project/goal relationships, documents, attachments, work products, labels, blocker dependencies, and inbox state.[^1]

This is extremely aligned with Overmind’s desired separation:

```text
Substrate
  canonical project context
        │
        ▼
Paperclip
  work / orchestration / governance
        │
        ├── local coding agent
        ├── hosted coding agent
        ├── research agent
        ├── reviewer
        └── arbitrary HTTP/MCP-backed agent
```

Paperclip does not need to own the implementation of the agents. That makes it compatible with the requirement that Overmind remain model- and agent-runtime agnostic.

### 2.2 Execution policies already implement review loops

Paperclip’s governance system includes execution policies with ordered review and approval stages.[^1]

The agent-facing Paperclip skill documents the behavior directly:

- a work item entering review is assigned to the configured reviewer;
- the reviewer can approve by completing the stage;
- requesting changes moves the item back into progress;
- Paperclip returns it to the prior assignee/executor;
- subsequent completion can return it through the review path;
- review/approval state is persisted rather than existing only in a chat prompt.[^4]

This is extremely close to:

```text
implementer
    ↓
reviewer
   ↙ ↘
revise approve
  ↓
implementer
```

The design principle here is important: **the review loop is runtime state, not merely a prompt convention**.

### 2.3 Structured human interactions already resemble Overmind review cards

Paperclip also has first-class issue-thread interactions. Current documented interaction types include:

- `request_confirmation`
- `request_checkbox_confirmation`
- `request_item_verdicts`
- `ask_user_questions`
- `suggest_tasks`[^4]

These interactions support target binding to specific document revisions, idempotency keys, continuation policies that wake agents after a response, and stale-target handling when the underlying artifact changes.[^4]

This maps unusually well to the proposed Overmind inbox card:

```text
QUESTION
Should the registry be project-local or shared?

RECOMMENDATION
Shared.

[Accept]
[Reject]
[Ask question]
[Open plan]
```

A key design implication is that Overmind should **not invent its own approval-card protocol unless Paperclip’s proves insufficient**.

### 2.4 Paperclip now has an attention queue and Decisions surface

Paperclip’s July 20, 2026 release introduced an **Attention queue & Decisions** surface specifically to bring things that need human input into one place.[^2]

A later release expanded Decisions into a first-class **propose/decide** workflow:

- agents can propose multiple options rather than immediately act;
- decisions are durable;
- the attention feed prioritizes decision work;
- a Decisions desk provides triage and retention;
- decisions are audited and linked to their target objects.[^5]

This is essentially the core UX requirement in the Overmind design.

Therefore, the canonical human surface should initially be:

```text
Paperclip Attention / Decisions / Inbox
```

rather than:

```text
custom Overmind inbox
        ↓
Paperclip work state
```

Duplicating the state would create synchronization and lifecycle problems for little benefit.

### 2.5 Paperclip Pipelines are an especially close match to staged workflows

The current Paperclip repository contains pipeline machinery with stage types including working/review/done/cancelled behavior.

A current tutorial/smoke example defines a `final_review` stage where a human reviewer can:

- approve and move forward;
- request changes and return the case to drafting;
- reject and move the case to a cancelled/dropped state.[^3]

The implementation explicitly demonstrates:

```text
Drafting
   ↓
Final Review
   ├── approve → Publishing
   ├── changes → Drafting
   └── reject → Dropped
```

and records review decisions in event history.[^3]

That is structurally almost identical to the Overmind design/review/implementation/review concept.

**Caution:** Pipelines appear to be newer and less established than basic issues/execution policies. For an initial Overmind implementation, use stable Paperclip primitives first and treat Pipelines as a feature to evaluate rather than a mandatory dependency.

### 2.6 Paperclip supports extensibility without a fork

Paperclip’s current architecture includes an instance-wide plugin system and external adapter plugins. The README describes plugins as out-of-process workers with capability-gated host services, job scheduling, tool exposure, and UI contributions.[^1]

This creates a clean route for Overmind-specific behavior:

```text
Paperclip
   │
   └── Overmind/Substrate plugin or adapter
          ├── resolve project
          ├── retrieve context
          ├── locate repos/worktrees
          ├── attach Substrate resources
          └── write outputs back
```

This is preferable to modifying Paperclip internals.

---

## 3. Where Paperclip Is Still Not the Entire Answer

Paperclip is evolving rapidly, and current issue history shows that its governance machinery is still being hardened.

Recent and historical issues include:

- edge cases in execution-policy participant routing;
- work items reaching `done` despite external conditions such as an unmerged pull request;
- requests for inherited/default execution-policy templates;
- concerns around approval lifecycle semantics and single-consumption behavior.[^6][^7][^8]

These do not invalidate Paperclip as the strongest fit. They indicate that Overmind should distinguish:

### Work/review state

Paperclip is well suited to own:

- who is doing the work;
- whether it is planning, implementing, or in review;
- which human decision is pending;
- task/blocker relationships;
- work artifacts and discussion;
- audit state.

### Objective external predicates

Paperclip should not be trusted to infer that an external fact is true merely because an approval stage completed.

Examples:

```text
PR actually merged
deployment actually healthy
tests actually pass
backup actually completed
migration actually verified
```

These should be enforced by deterministic tools/CI/checks and surfaced back into Paperclip.

This follows the same architecture already being adopted elsewhere in Overmind:

> agents express intent and supervision; deterministic software verifies objective state.

---

## 4. LangGraph + Agent Inbox

### Fit: Excellent reference implementation, moderate direct fit with Paperclip

LangGraph has mature support for durable human-in-the-loop execution. Its interrupt mechanism saves graph state, can wait indefinitely for human input, and resumes after a structured response. Human decisions can approve, edit, reject, or respond to pending actions.[^9]

The separate **Agent Inbox** project is explicitly an “inbox UX for interacting with human-in-the-loop agents.” It connects to one or more LangGraph deployments and renders pending interrupts for human action.[^10]

This may be the closest independent open-source implementation of the *UI metaphor* Overmind originally described.

### What to borrow

Agent Inbox provides a useful reference for a generic interruption schema:

```text
HumanInterrupt
  action_request
  description
  allowed_decisions
  context

HumanResponse
  approve
  edit
  reject
  respond
```

That is much better than arbitrary conversational strings such as “ask Austin something.”

The Overmind/Paperclip design should preserve similarly typed human interactions.

### Why not adopt it as Overmind’s main inbox

Agent Inbox is designed around LangGraph interrupt semantics and expects LangGraph deployment identifiers/APIs.[^10]

Therefore, using it directly would either:

1. make LangGraph a dependency of the orchestration layer; or
2. require writing an adapter that translates Paperclip interactions into LangGraph interrupts.

That would duplicate functionality Paperclip now provides natively.

### Best use in Overmind

Use LangGraph for **individual complex agents** if they need their own internal durable graph:

```text
Paperclip issue
     ↓
HTTP adapter
     ↓
LangGraph research agent
     ↓
internal interrupt / subworkflow
```

Paperclip remains the outer work system. LangGraph owns the internal state machine of that particular worker.

---

## 5. HumanLayer

### Fit: Best orchestrator-neutral human-contact abstraction

HumanLayer’s core idea is exceptionally clean: human approval is enforced at the **tool/function boundary**, not left to the LLM’s discretion. Its `require_approval` and `human_as_tool` patterns are designed for long-running “outer-loop” agents that sometimes need human authorization or answers.[^11]

Conceptually:

```text
agent
  ↓
dangerous_tool()
  ↓
HumanLayer gate
  ↓
human approves / rejects
  ↓
tool executes or returns feedback
```

This is highly portable because the pattern does not fundamentally depend on a particular planner or LLM.

### Why it matters to Overmind

If Paperclip ceased to be the preferred orchestrator tomorrow, the conceptual contract we would want to retain is remarkably close to HumanLayer:

```text
request human decision
wait durably
receive typed response
resume work
```

This makes HumanLayer a strong **architectural reference** for keeping the human-attention boundary independent of agent reasoning.

### Agent Control Plane

The HumanLayer ecosystem also includes Agent Control Plane (ACP), a Kubernetes-native durable agent scheduler supporting MCP tools and human approvals.[^12]

However, ACP is currently alpha and expects Kubernetes. That is excessive infrastructure for a personal Overmind server, particularly given the goal of avoiding unnecessary distributed-system complexity.

### Recommendation

Do **not** deploy HumanLayer merely to duplicate Paperclip approvals.

Do borrow its core abstraction when designing Overmind-specific tools:

> Any consequential tool should be able to declare that approval is required independently of whatever model calls it.

Paperclip’s governed MCP/tool approval machinery can likely implement this principle directly.

---

## 6. Temporal

### Fit: Strongest durable-workflow fallback, but too low-level for the first implementation

Temporal is fundamentally different from Paperclip. It is a general-purpose durable execution engine rather than an agent work manager.

Its documented human-approval pattern allows workflows to block on an external decision delivered through a Signal. The approval can include approver identity, reason, timestamp, multiple outcomes, escalation, and timeout behavior; the workflow history provides a durable audit trail.[^13]

Temporal’s agent examples demonstrate that an AI workflow can pause for days, survive worker restarts, receive a human decision, and continue from the same execution state.[^14]

That is a stronger durability primitive than “keep a database row saying the task is awaiting approval.”

### Where Temporal wins

If Overmind eventually runs high-value or very long-lived workflows such as:

```text
research campaign lasting weeks
company incorporation process
multi-system deployment
financial/accounting workflow
hardware procurement and installation
long scientific experiment pipeline
```

Temporal has attractive semantics around:

- retries;
- timers;
- signals;
- replay;
- durable waits;
- idempotency patterns;
- workflow versioning.

### Why not use it now

Temporal does **not** provide the human work inbox or project-centered agent UX we want.

We would need to build:

```text
Temporal
+ work-item model
+ project model
+ inbox UI
+ agent assignment
+ reviewer roles
+ Substrate integration
```

which Paperclip already largely supplies.

### Recommended relationship

Temporal is an **escape hatch beneath Paperclip**, not a replacement today.

A future Paperclip agent/tool could start a Temporal workflow for a particularly durable external process and expose its status as a Paperclip work item.

---

## 7. Mastra

### Fit: Attractive TypeScript inner workflow engine

Mastra is a TypeScript framework for agent applications. Its workflow system provides explicit graph-like control flow with sequential, branching, and parallel steps, and it supports suspend/resume for human input. It persists workflow state so suspended executions can resume later.[^15]

This aligns naturally with Overmind’s likely implementation language and server stack.

### Potential role

Mastra makes sense if one Paperclip “employee” needs an internally structured workflow such as:

```text
gather context
   ↓
parallel research
   ↓
synthesize
   ↓
critic
   ↓
revise
   ↓
return artifact
```

That service can be deployed independently and called by Paperclip through HTTP.

### Why not make Mastra the system of record

It provides workflow/agent building blocks, but not the rich cross-project human attention/task-management layer that Paperclip now provides.

Using it as the outer orchestrator would put Overmind back in the business of building an inbox and project work UI.

### Recommendation

Potentially excellent **agent-runtime layer behind Paperclip**, especially for custom TypeScript agents.

---

## 8. n8n

### Fit: Excellent integration edge, weak canonical work layer

n8n is a self-hostable workflow-automation system with broad integrations. Its application nodes can participate in human-in-the-loop AI tool review, and it has direct integrations for channels such as Telegram, Gmail, Slack-like systems, and many other services.[^16][^17]

This makes it attractive for the optional notification surfaces envisioned in the Overmind design.

For example:

```text
Paperclip decision created
        ↓ webhook
       n8n
   ┌────┼─────┐
   ↓    ↓     ↓
Telegram Email Phone/push
```

The reply can then be routed back to Paperclip.

### Why not make n8n canonical

n8n is fundamentally an automation/workflow builder. It is not naturally a project-aware agent work system with reviewer roles, durable agent work products, Substrate project context, and a cross-project attention model.

It is also “fair-code” rather than conventionally OSI-open-source, which makes it somewhat less attractive as a foundational dependency for an openly shareable Overmind architecture.

### Recommendation

Use n8n later if it materially simplifies **notification and external-service integration**. Do not use it to replace Paperclip’s work/attention state.

---

## 9. Comparative Assessment

| System | Durable work state | Human review/approval | Inbox/attention UI | Agent/runtime agnostic | Project/task management | Paperclip fit | Recommended role |
|---|---|---|---|---|---|---|---|
| **Paperclip** | Strong | Strong | **Strong and improving** | **Strong** | **Strong** | Native | Canonical outer control plane |
| **LangGraph + Agent Inbox** | Strong | Strong | **Strong** | Low–moderate | Limited | Via HTTP adapter | Inner agent graphs / UI reference |
| **HumanLayer** | Moderate | **Excellent tool-level abstraction** | Channel-oriented | **Strong** | Weak | Conceptual/native-tool overlap | Approval design reference |
| **Temporal** | **Excellent** | Strong | Requires custom UI | **Excellent** | Weak | Via agent/tool integration | Extreme durability escape hatch |
| **Mastra** | Strong | Strong | Limited | Moderate–strong | Limited | **Good via HTTP** | TypeScript custom agent workflows |
| **n8n** | Strong workflow state | Tool approvals | Messaging channels | Moderate | General workflows | Good via webhook/API | Notification/integration edge |

The central insight is that the systems are complementary because they operate at different layers.

---

## 10. Recommended Overmind Architecture

### Layer 1 — Substrate

Owns portable project context:

```text
projects
repos
notes
papers
decisions
artifacts
references
index/retrieval conventions
```

Substrate should remain independent of Paperclip.

### Layer 2 — Paperclip

Owns work:

```text
issues
delegation
agent identities
goals
review stages
approvals
attention queue
decisions
work products
audit history
schedules
budgets
```

This is the canonical agent-work system of record.

### Layer 3 — Agent runtimes

Paperclip can invoke heterogeneous workers:

```text
Codex
Claude Code
local coding agents
local LLM workers
Mastra services
LangGraph agents
research services
arbitrary HTTP agents
```

Each worker may use whatever internal framework best suits the task.

### Layer 4 — Deterministic verification

Objective facts are checked by deterministic systems:

```text
Git / GitHub
CI
tests
linters
deployment health checks
filesystem state
database checks
monitoring
```

Paperclip receives and reasons about these results but should not substitute an approval for an external predicate.

### Layer 5 — Optional notification bridge

n8n or a small custom bridge can provide:

```text
Telegram
email
mobile notifications
Slack
other messaging
```

These are secondary interaction surfaces. Paperclip retains canonical state.

---

## 11. Proposed Overmind Workflow Profile

Instead of building software immediately, define a **Paperclip workflow convention**.

### Implementation work

```text
1. Chief of Staff receives intent
2. Resolve Substrate project
3. Create durable parent issue
4. Planning agent produces revisioned plan artifact
5. Independent reviewer evaluates plan
6. If risk/ambiguity threshold exceeded:
      create Paperclip Decision / human interaction
7. Implementation agent receives approved plan
8. Deterministic tests/validation run
9. Independent implementation reviewer checks work
10. Request changes → return to implementer
11. Automated acceptance or human final review based on policy
12. Complete issue and preserve artifacts/history
```

### Research work

```text
1. Research request
2. Planner scopes questions
3. Optional plan review
4. Parallel research agents
5. Synthesis
6. Evidence/critique pass
7. Human review only for decisions or consequential conclusions
8. Save final artifact into Substrate
```

### Escalation policy

The workflow should interrupt the human for:

- irreversible or destructive actions;
- high-cost external actions;
- security/credential changes;
- substantial architecture decisions;
- genuine requirement ambiguity;
- unresolved reviewer disagreement;
- repeated failed revision cycles.

Everything else should attempt bounded autonomous completion first.

---

## 12. What Overmind Should Build

The research suggests a much smaller custom surface than originally assumed.

### Build or configure

**A Substrate → Paperclip context bridge**

Given a Paperclip project/issue, resolve:

- Substrate project;
- relevant repositories;
- project context capsule;
- search/index access;
- paths/workspaces;
- canonical output locations.

**Workflow templates/policies**

Define repeatable conventions for:

- design-review-implement-review;
- research-review-synthesize;
- low-risk maintenance;
- high-risk infrastructure changes.

**Reviewer prompts/skills**

Independent reviewers need stable rubrics:

```text
Does this satisfy the request?
Does it contradict project decisions?
Were objective checks run?
Are risks identified?
Is human judgment actually required?
```

**Notification adapters only if useful**

Telegram/email/etc. should be added after the Paperclip inbox itself is proven.

### Do not build yet

- another task database;
- another inbox;
- another approval protocol;
- another agent registry;
- another workflow engine;
- a second copy of Paperclip state.

---

## 13. What to Pilot First

A useful Overmind proof-of-concept would use one real software task.

### Pilot

Use the Overmind project itself.

Request:

> Add a small, reversible server-management capability.

Workflow:

1. Submit to Chief of Staff.
2. Chief of Staff creates project-linked issue.
3. Planner writes a plan.
4. Reviewer evaluates it.
5. Force one human Decision before implementation.
6. Implementer changes an isolated Git worktree.
7. Run automated verification.
8. Reviewer either requests changes or approves.
9. Human receives final review item.
10. Approve and merge manually.

### Evaluation questions

At the end, ask:

- Did Paperclip's existing attention surface make the pending decision obvious?
- Was the plan easy to inspect without reading agent logs?
- Did request-changes routing work cleanly?
- Could the user ask follow-up questions in context?
- Did artifacts remain attached to the work item?
- Did Substrate provide enough project context?
- Was any state duplicated outside Paperclip?
- Where did the workflow actually feel awkward?

Only those observed gaps should become Overmind-specific software requirements.

---

## 14. Strategic Recommendation

The original Overmind review-inbox design remains useful as a **requirements document**, but it should no longer be interpreted as a commitment to build a custom inbox.

Paperclip’s 2026 evolution has moved it directly into this problem space. Its attention queue, Decisions, structured interactions, execution policies, project workspaces, agent adapters, and emerging pipeline system cover most of the intended control plane.

The best architectural posture is therefore:

> **Paperclip is pinned, but not embedded.**

Overmind should depend on a narrow conceptual contract:

```text
durable work item
project identity
artifact references
typed human decision
review state
external agent invocation
```

Today Paperclip implements that contract.

If a future orchestrator becomes better, Substrate remains unchanged and agent runtimes remain unchanged. Only the control-plane adapter changes.

This preserves the desired portability without forcing Overmind to prematurely create another orchestration standard.

---

## 15. Bottom Line

The strongest available implementation is already the tool currently pinned for Overmind.

**Use Paperclip natively for:**

- Chief-of-Staff delegation
- durable project-linked work
- review/approval stages
- human questions
- attention/inbox
- Decisions
- work products
- audit history
- schedules/heartbeats
- heterogeneous agent invocation

**Use existing external tools selectively:**

- **LangGraph** for sophisticated internal agent graphs.
- **Agent Inbox** as a UX/schema reference for human interrupts.
- **HumanLayer** as a design reference for tool-level approval independence.
- **Temporal** if truly durable multi-day/multi-system business workflows outgrow Paperclip.
- **Mastra** for custom TypeScript agent services.
- **n8n** for external notifications and SaaS/app glue.

The next Overmind implementation step should therefore be **configuration and integration, not a new application**.

---

## Sources

[^1]: Paperclip AI, **Paperclip repository / README**, current master. https://github.com/paperclipai/paperclip
[^2]: Paperclip AI, **Paperclip v2026.720.0**, July 20, 2026. https://github.com/paperclipai/paperclip/blob/master/releases/v2026.720.0.md
[^3]: Paperclip AI, **Pipelines tutorial smoke implementation**, current master. https://github.com/paperclipai/paperclip/blob/master/scripts/smoke/pipelines-tutorial-smoke.sh
[^4]: Paperclip AI, **Paperclip agent skill — execution policies and issue-thread interactions**, current master. https://github.com/paperclipai/paperclip/blob/master/skills-releases/paperclip/v0/SKILL.md
[^5]: Paperclip AI, **Releases — Decisions v1**, 2026. https://github.com/paperclipai/paperclip/releases
[^6]: Paperclip AI issue #11145, **Issues can reach done while their pull request is still open**. https://github.com/paperclipai/paperclip/issues/11145
[^7]: Paperclip AI issue #11390, **Autonomous workflow orchestration: review routing, task policy inheritance, workspace safety, and bounded recovery**. https://github.com/paperclipai/paperclip/issues/11390
[^8]: Paperclip AI issue #12482, **Approvals are read-state, not single-consumption**, August 29, 2026. https://github.com/paperclipai/paperclip/issues/12482
[^9]: LangChain, **Human-in-the-loop and LangGraph interrupts**. https://docs.langchain.com/oss/python/langchain/human-in-the-loop and https://docs.langchain.com/oss/python/langgraph/interrupts
[^10]: LangChain AI, **Agent Inbox**, open-source HITL inbox UI. https://github.com/langchain-ai/agent-inbox
[^11]: HumanLayer, **HumanLayer human oversight patterns**. https://github.com/humanlayer/humanlayer
[^12]: HumanLayer, **Agent Control Plane**. https://github.com/humanlayer/agentcontrolplane
[^13]: Temporal, **Approval Pattern**. https://github.com/temporalio/documentation/blob/main/docs/design-patterns/approval.mdx
[^14]: Temporal, **Google ADK human-in-the-loop durable workflow sample**. https://github.com/temporalio/samples-go/blob/main/googleadk/humanintheloop/workflow.go
[^15]: Mastra, **Mastra README / Workflows and Human-in-the-loop**. https://github.com/mastra-ai/mastra
[^16]: n8n, **Documentation — workflow automation and AI tooling**. https://docs.n8n.io/
[^17]: n8n, **Telegram integration / human-review-capable application integrations**. https://docs.n8n.io/integrations/builtin/app-nodes/n8n-nodes-base.telegram/
