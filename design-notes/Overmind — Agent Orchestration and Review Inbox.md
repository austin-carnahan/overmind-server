# Overmind — Agent Orchestration and Review Inbox

## Status

Future capability / architectural design note.

## Purpose

Overmind should support asynchronous agent work across multiple projects while preserving a clear human review loop.

The intended experience is:

```text
User intent
    ↓
Chief of Staff
    ↓
Project identification
    ↓
Planning / research / implementation workflow
    ↓
Automated review
    ↓
Human review inbox when necessary
```

The user should not need to monitor individual agent conversations or manually remember which delegated tasks are waiting for attention.

Instead, Overmind should maintain a **canonical cross-project review inbox** containing work that requires a human decision, answer, approval, or final review.

---

# 1. Core Principle

Agent orchestration should optimize for:

> **Delegate aggressively, interrupt the human selectively.**

Agents should be able to perform routine planning, research, implementation, testing, and revision independently.

Human attention should be requested when:

- a consequential decision must be made;
- requirements are genuinely ambiguous;
- an agent lacks authority to proceed;
- two plausible approaches require a preference;
- a plan changes project scope substantially;
- implementation introduces meaningful risk;
- automated reviewers disagree;
- completed work is ready for final acceptance.

The review inbox therefore acts as the boundary between autonomous execution and human judgment.

---

# 2. Chief-of-Staff Entry Point

The user should be able to provide high-level instructions without manually selecting projects or agents.

Example:

> “Figure out whether we should move Gather model storage into a shared service and implement it if it makes sense.”

The Chief of Staff should:

```text
interpret request
      ↓
identify project
      ↓
retrieve Substrate context
      ↓
classify work type
      ↓
create work item
      ↓
choose workflow
      ↓
delegate
```

The Chief of Staff is primarily a **router, coordinator, and summarizer**, not necessarily the agent that performs the substantive work.

It should understand:

- project boundaries;
- current goals;
- relevant repositories;
- Substrate context;
- task dependencies;
- agent capabilities;
- risk and approval policies.

---

# 3. Standard Work Cycle

The default implementation workflow should use staged independent review.

```text
                USER REQUEST
                     │
                     ▼
              CHIEF OF STAFF
                     │
                     ▼
              DESIGN AGENT
             plan / proposal
                     │
                     ▼
            DESIGN REVIEWER
                │         │
          approve│         │revise
                ▼         └──────→ Design Agent
          HUMAN GATE?
             │     │
           no│     │yes
             │     ▼
             │   INBOX
             │     │
             └─────┘
                ↓
         IMPLEMENTATION AGENT
                │
                ▼
        IMPLEMENTATION REVIEWER
           │              │
        accept          revisions
           │              │
           │              └────→ implementation/design
           ▼
       HUMAN REVIEW?
        │       │
      no│       │yes
        ▼       ▼
      DONE    INBOX
```

This workflow intentionally separates:

1. design;
2. review of design;
3. execution;
4. review of execution.

The same pattern can be adapted for research.

---

# 4. Research Workflow

A research task should follow a similar structure:

```text
Research request
      ↓
Research planner
      ↓
Plan reviewer
      ↓
Research agent(s)
      ↓
Synthesis agent
      ↓
Evidence/review agent
      ↓
Human review if required
```

Multiple research agents may operate in parallel on different questions or sources.

The synthesis agent should not merely concatenate outputs. It should reconcile evidence, identify disagreement, and produce a coherent result.

A review agent should then check:

- whether the original question was answered;
- whether important claims are supported;
- whether conflicting evidence was handled;
- whether gaps remain;
- whether the result is suitable for human review.

---

# 5. The Overmind Review Inbox

The inbox should be the canonical place where agent workflows request human attention.

It should not behave like an email inbox full of verbose agent chatter.

Each item should be a concise **decision or review object**.

Example:

```text
Gather
──────────────────────────────
Model dependency refactor

STATUS
Plan approved by reviewer.
Human decision required.

QUESTION
Should model revisions remain pinned
per instrument or track latest compatible?

RECOMMENDATION
Pin exact revision.

WHY THIS MATTERS
Changes persistence semantics and reproducibility.

[Approve recommendation]
[Choose latest-compatible]
[Ask question]
[Open full plan]
```

The important design goal is:

> present the smallest useful decision surface first, while allowing arbitrary drill-down.

---

# 6. Inbox Item Types

The review inbox should distinguish at least these classes of attention:

```text
APPROVAL
Agent has a recommended action and needs authorization.

QUESTION
Agent cannot reliably infer a requirement.

REVIEW
Work is complete and ready for human inspection.

EXCEPTION
Something failed or deviated from the expected workflow.

CONFLICT
Agents or evidence disagree materially.

NOTICE
Important result worth seeing but no action required.
```

Not every completed task should generate an inbox item.

Routine successful work can simply be recorded in activity history.

---

# 7. Drill-Down Model

Every inbox card should support progressive disclosure.

The first level should answer:

```text
What happened?
Why am I seeing this?
What decision do you need from me?
What do you recommend?
```

From there the user can drill into:

```text
summary
  ↓
agent reasoning / review comments
  ↓
plan
  ↓
implementation diff
  ↓
tests / evidence
  ↓
Substrate sources
  ↓
individual agent conversations
```

The user should never be forced to read full agent transcripts merely to understand an approval request.

---

# 8. Conversational Review

Inbox items should support threaded questioning.

For example:

> “Why are you recommending option B?”

The responsible agent or reviewer can answer using the work item's accumulated context.

The user might then ask:

> “What would option A cost us six months from now?”

The thread remains attached to the work item rather than becoming an unrelated conversation.

After discussion:

> “Okay, go with B.”

should resolve the gate and automatically resume the suspended workflow.

---

# 9. Human Gates

Workflows should define explicit gates rather than relying on agents to improvise when they need permission.

Example:

```yaml
gates:
  architecture_change:
    human_review: true

  dependency_update:
    human_review: false

  destructive_database_change:
    human_review: true

  ordinary_test_fix:
    human_review: false
```

Eventually policies can differ by project.

A mature, low-risk project workflow might permit more autonomy than a new or consequential one.

---

# 10. Risk-Based Escalation

Not every design needs human approval.

Overmind should eventually assign work a risk/uncertainty profile based on factors such as:

- reversibility;
- scope of filesystem/code changes;
- production impact;
- destructive operations;
- cost;
- security implications;
- confidence;
- reviewer agreement;
- novelty of the decision.

A small reversible refactor might flow:

```text
design → review → implement → test → merge
```

without interruption.

A database migration might flow:

```text
design → independent review → HUMAN APPROVAL → implement
```

The goal is not maximum autonomy.

The goal is **appropriate autonomy**.

---

# 11. Project-Aware Inbox

Every work item should belong to a project whenever possible.

Example dashboard:

```text
OVERMIND INBOX

3 need attention
────────────────────────────

Gather                  2
River Signal            1
Overmind                0

Recently completed      7
Running                 5
Blocked                 2
```

Selecting a project should show its pending reviews alongside current agent activity and recent completed work.

The user should also be able to view one unified inbox across all projects.

---

# 12. Substrate Integration

Substrate should supply the shared context layer for agent work.

A work item should retain references to the Substrate material used during execution:

```text
project
repos
notes
decisions
papers
artifacts
retrieved context
```

Agents should retrieve project context from Substrate rather than depending on giant persistent conversation histories.

Outputs should return to the project workspace.

Example:

```text
substrate/gather/
    ↓
agents read context
    ↓
work performed
    ↓
design / research / code / artifact written back
    ↓
index updates
    ↓
future agents can retrieve it
```

The review inbox is therefore not another knowledge silo.

It is a **workflow view over project state already grounded in Substrate**.

---

# 13. Work Items as Durable Objects

Every delegated task should have a durable identifier and state.

Conceptually:

```yaml
id: work-2026-00481
project: gather

request:
  ...

workflow: implementation

state: awaiting-human-review

agents:
  planner: ...
  plan_reviewer: ...
  implementer: ...
  reviewer: ...

artifacts:
  plan: ...
  implementation: ...
  review: ...

questions:
  - ...

decisions:
  - ...

created_at: ...
updated_at: ...
```

Agent conversations may come and go.

The **work item** is the persistent object.

---

# 14. State Machine

A simple shared state machine might include:

```text
queued
↓
planning
↓
plan-review
↓
awaiting-human
↓
approved
↓
executing
↓
implementation-review
↓
revision
↓
awaiting-final-review
↓
completed
```

Additional terminal states:

```text
cancelled
failed
blocked
superseded
```

Research workflows may use equivalent states such as `researching`, `synthesizing`, and `evidence-review`.

---

# 15. Agent Independence

Independent review should be genuinely independent.

The reviewer should receive:

- the task;
- relevant requirements;
- the plan or implementation;
- relevant Substrate context;

but should not simply inherit the producing agent's conclusion as unquestioned truth.

This encourages useful disagreement.

A reviewer can:

```text
approve
approve-with-notes
request-revision
escalate-to-human
reject
```

Repeated agent disagreement should automatically become an inbox item rather than cycling indefinitely.

---

# 16. Revision Loops

Agents should be allowed bounded revision loops.

Example:

```text
implementation
      ↓
review
      ↓
revision requested
      ↓
implementation
      ↓
review
```

After a configurable number of failed iterations, Overmind should escalate:

> “The implementation agent and reviewer have failed to converge after three cycles.”

This prevents autonomous loops from consuming unlimited inference or compute.

---

# 17. Notifications vs. Inbox

Telegram, Signal, email, phone notifications, or future clients may be useful surfaces, but they should not own workflow state.

They should function as:

```text
notification
+
lightweight interaction surface
```

For example:

> Gather task needs approval: choose pinned revision vs compatible-latest.

A Telegram reply might resolve the work item.

But the canonical object remains in Overmind.

This prevents project history from being fragmented across messaging systems.

---

# 18. Overmind Work Dashboard

A future human interface might have four primary views:

```text
INBOX
Things requiring human attention.

ACTIVE
Agents currently working.

PROJECTS
Work grouped by Substrate project.

HISTORY
Completed, rejected, failed, and superseded work.
```

The default view should emphasize the inbox rather than showing an impressive-but-useless visualization of dozens of agents moving around.

The central UX question is:

> “What needs me?”

---

# 19. Review Experience for Code

A completed coding task should surface:

```text
task summary
reviewer verdict
files changed
tests run
test results
notable design decisions
risks / unresolved issues
diff
```

The user should be able to:

```text
approve
request changes
ask a question
open in IDE
reject
```

“Open in IDE” should connect directly to the relevant Substrate repository/worktree.

---

# 20. Review Experience for Research

A completed research task should surface:

```text
answer / synthesis
confidence
key findings
important evidence
disagreements / uncertainty
sources
open questions
```

The user should be able to drill from a finding directly into the supporting source or Substrate paper.

Follow-up research should create a child work item linked to the original.

---

# 21. Local and Hosted Models

The orchestration model should be indifferent to where intelligence runs.

Example:

```text
Chief of Staff
      ↓
local model

routine planner
      ↓
local model

code implementation
      ↓
local coding model

hard reviewer
      ↓
frontier hosted model

routine verification
      ↓
local model
```

Paperclip or another orchestration layer should choose models according to role, capability, privacy, latency, and cost.

The workflow definition should not depend on one model vendor.

---

# 22. Example End-to-End Interaction

User:

> “Look into whether we should replace the current Gather model registry architecture.”

Overmind:

```text
Chief of Staff
→ classifies as Gather architecture work

Design Agent
→ investigates current implementation
→ creates proposal

Design Reviewer
→ identifies two viable designs
→ considers one consequential
→ escalates
```

Inbox:

```text
GATHER — Model Registry Architecture

Decision required.

Two viable approaches remain.

A. Project-local registry
B. Shared registry service

Reviewer recommends B because three upcoming
workflows require cross-project model reuse.

[Choose B]
[Choose A]
[Ask why]
[Review proposal]
```

User:

> “Why isn't A enough?”

Reviewer answers in-thread.

User:

> “Okay, choose B.”

Workflow resumes:

```text
Implementation Agent
→ implements B
→ tests

Implementation Reviewer
→ catches migration bug
→ sends back

Implementation Agent
→ fixes migration

Reviewer
→ approves

Inbox:
Final implementation ready for review.
```

The user reviews the diff and accepts it.

Work item becomes complete.

---

# 23. MVP

The first version does not require a sophisticated UI.

A useful MVP could consist of:

1. durable Paperclip work items;
2. project association;
3. planner → reviewer → implementer → reviewer workflow;
4. explicit `awaiting-human` state;
5. a simple local web inbox;
6. threaded questions on work items;
7. approve / reject / revise actions;
8. links to plans, artifacts, code diffs, and Substrate context;
9. bounded agent revision loops;
10. activity/history view.

Messaging integrations can come later.

---

# 24. Success Criterion

Overmind reaches the intended experience when the user can routinely begin work with:

> “Look into X.”

or:

> “Implement Y.”

and then leave.

Overmind should determine the project, gather context, delegate the work, review it, iterate where possible, and return only when human judgment is useful.

The user's primary interaction with asynchronous agent work becomes:

> **an inbox of meaningful decisions and completed work, not a collection of agent conversations.**

---

# Architectural Summary

Overmind should treat agent orchestration as a workflow system rather than a chatbot system.

```text
                           USER
                            │
                       Chief of Staff
                            │
                    project + workflow
                            │
             ┌──────────────┴──────────────┐
             │                             │
         agent cycle                  Substrate
             │                        context
     design → review                       │
        ↓                                  │
     execution                             │
        ↓                                  │
      review                               │
        │                                  │
        └──────────────┬───────────────────┘
                       ▼
                 HUMAN ATTENTION?
                   │          │
                  no         yes
                   │          ▼
                   │        INBOX
                   │          │
                   └──────────┘
                       ↓
                   continue
                       ↓
                    complete
```

The defining principle is:

> **Agents do the work. Reviewers supervise the agents. The inbox protects human attention.**