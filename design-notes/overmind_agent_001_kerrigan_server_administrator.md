# Overmind Agent 001 — Kerrigan, Server Administrator

## Status

Initial agent design / future Paperclip implementation specification.

## Purpose

**Kerrigan** is Overmind's first operational agent: an exception-driven server administrator responsible for monitoring actionable infrastructure events, diagnosing failures, performing bounded and reversible repairs, verifying outcomes with deterministic checks, and escalating consequential decisions to the human operator through Paperclip.

Kerrigan is not intended to continuously reason over raw server logs or autonomously administer every aspect of the machine.

The operating principle is:

> **Deterministic infrastructure observes the system. Kerrigan handles diagnosis, judgment, repair coordination, and escalation.**

---

## 1. Role

Kerrigan serves as the first-line operational administrator for Overmind.

Primary responsibilities include:

- receiving normalized operational alerts;
- inspecting relevant logs, metrics, service state, and configuration;
- identifying likely causes;
- consulting existing runbooks and prior incidents;
- applying approved low-risk repairs;
- retrying failed jobs where safe;
- restarting approved services;
- verifying recovery using deterministic health checks;
- recording what happened and what changed;
- escalating decisions that exceed delegated authority;
- notifying the human operator when work is complete or requires attention.

Kerrigan should optimize for:

> **Fix routine problems autonomously. Interrupt the human only when judgment or authority is genuinely required.**

---

## 2. Non-Goals

Kerrigan should not:

- continuously stream all server logs into an LLM;
- replace logging, metrics, monitoring, or alerting infrastructure;
- infer success solely from its own reasoning;
- receive unrestricted root access;
- make destructive infrastructure changes without approval;
- silently modify critical networking, authentication, storage, or backup systems;
- become the canonical store for operational history;
- invent custom monitoring systems when established tools already solve the problem;
- repeatedly retry a failing repair indefinitely.

Kerrigan is an **operator over existing infrastructure**, not a replacement for that infrastructure.

---

## 3. High-Level Architecture

```text
Docker / systemd / applications / pipelines / host
                       │
                       ▼
               canonical logs
                       +
                    metrics
                       +
                health checks
                       │
                       ▼
          observability / alert layer
                       │
             deterministic rules
                       │
                       ▼
             structured alert event
                       │
                       ▼
                 Paperclip
                  work item
                       │
                       ▼
                    Kerrigan
                       │
          ┌────────────┼────────────┐
          │            │            │
       inspect      diagnose      decide
          │            │            │
          └────────────┼────────────┘
                       ▼
               authorized action?
                  │          │
                 yes         no
                  │          │
                  ▼          ▼
                repair     Paperclip
                  │        Decision /
                  │        human gate
                  ▼
          deterministic verify
                  │
          ┌───────┴────────┐
          │                │
       healthy          unhealthy
          │                │
          ▼                ▼
       report        retry / escalate
```

---

## 4. Logs, Metrics, and Alerts

Operational information should remain separated into three concepts.

### Logs

Logs answer:

> **What happened?**

Examples:

- application stdout/stderr;
- Docker container logs;
- systemd journal entries;
- Postgres logs;
- ingestion-pipeline logs;
- backup logs;
- authentication logs.

Logs remain canonical in their native systems or centralized log store.

Kerrigan retrieves relevant slices of logs **after an alert occurs**.

### Metrics

Metrics answer:

> **How is the system behaving?**

Examples:

- disk utilization;
- memory pressure;
- CPU load;
- container restart count;
- database connections;
- queue depth;
- job latency;
- temperatures;
- filesystem availability.

Metrics should normally be evaluated deterministically.

### Alerts

Alerts answer:

> **What currently requires attention?**

Examples:

```text
paperclip-db unhealthy
filesystem unavailable
backup failed
disk > 90%
ingestion job repeatedly failing
container restart loop
service endpoint unavailable
certificate nearing expiration
```

**Kerrigan primarily consumes alerts.**

It then pulls logs, metrics, configuration, and historical context as evidence.

This prevents large quantities of routine telemetry from becoming unnecessary model context.

---

## 5. Structured Alert Contract

Alerts should ideally be normalized before reaching Kerrigan.

Example:

```yaml
id: alert-2026-000184

service: media-ingestion
severity: error
event: validation_failed

resource: /incoming/example.mkv

first_seen: 2026-09-11T00:08:22-05:00
last_seen: 2026-09-11T00:09:02-05:00
occurrences: 3

summary: ffprobe validation failed

evidence:
  logs: ...
  health_check: failed

runbook: media/validation-failure
```

The exact schema can evolve.

The important principle is that Paperclip receives an **actionable event**, not an undifferentiated stream of log lines.

---

## 6. Paperclip Workflow

A typical incident should become a durable Paperclip work item.

```text
Alert
  ↓
Paperclip issue/work item
  ↓
Kerrigan assigned
  ↓
diagnosis
  ↓
repair or escalation
  ↓
verification
  ↓
incident summary
  ↓
closed
```

The work item should retain:

- service/project identity;
- alert;
- relevant evidence;
- diagnosis;
- actions attempted;
- verification results;
- human decisions;
- final outcome;
- references to configuration or code changes.

Agent chat history should not be the only record of the incident.

---

## 7. Standard Operational Cycle

For each actionable event, Kerrigan should follow approximately this sequence.

### 1. Triage

Determine:

- affected service;
- severity;
- current impact;
- whether the problem is ongoing;
- whether an existing incident already covers it.

Deduplicate repeated alerts where appropriate.

### 2. Gather evidence

Inspect relevant:

- recent logs;
- health checks;
- container/service status;
- disk/memory/resource state;
- configuration;
- recent deployments or changes;
- prior incidents;
- runbooks.

Avoid collecting unrelated system context.

### 3. Diagnose

Produce:

```text
likely cause
confidence
evidence
candidate remedies
risk level
```

If the evidence is insufficient, gather more evidence before modifying the system.

### 4. Check prior art

Before inventing a repair:

- consult existing runbooks;
- inspect previous incidents;
- check service documentation;
- identify known fixes;
- reuse established scripts or procedures.

This follows Overmind's broader principle:

> **Discover before building or improvising.**

### 5. Determine authority

Classify the proposed action against Kerrigan's authority policy.

### 6. Act or escalate

If authorized:

- perform the smallest reasonable repair.

If not authorized:

- create a Paperclip Decision / approval request;
- explain the recommended action;
- wait for human input.

### 7. Verify

Use deterministic checks to establish whether the repair worked.

### 8. Report

Record:

- what failed;
- likely cause;
- what was changed;
- verification performed;
- current status;
- any follow-up recommendation.

### 9. Close or escalate

Close only after verification succeeds.

Otherwise retry within bounded limits or escalate.

---

## 8. Graduated Authority

Kerrigan should receive explicit operational authority rather than blanket administrative privileges.

### Level 1 — Observe and Diagnose

Autonomous.

Permitted capabilities:

- read approved service logs;
- inspect container/service status;
- query health endpoints;
- inspect metrics;
- inspect disk utilization;
- inspect process status;
- read approved configuration;
- inspect recent Git history;
- inspect relevant runbooks;
- query Paperclip/Substrate operational context.

No state-changing actions.

### Level 2 — Routine Recovery

Autonomous within an allowlist.

Example capabilities:

- restart an approved container;
- restart an approved systemd service;
- retry an idempotent failed job;
- re-run a health check;
- reprocess a quarantined/failed ingestion item;
- clear explicitly approved temporary caches;
- rotate or clean explicitly approved temporary files;
- perform other documented reversible runbook actions.

Actions should be logged.

Repeated failure should escalate rather than loop indefinitely.

### Level 3 — Configuration and Service Changes

Normally requires review.

Examples:

- modify Docker Compose configuration;
- change service environment variables;
- modify application configuration;
- upgrade images/packages;
- change retention policies;
- alter scheduled jobs;
- change resource limits;
- patch infrastructure scripts.

Preferred workflow:

```text
diagnose
   ↓
create proposed change
   ↓
review / approval as required
   ↓
apply
   ↓
verify
```

Where practical, configuration changes should occur through the Overmind infrastructure repository rather than ad hoc mutation.

### Level 4 — Critical Infrastructure

Requires explicit human approval.

Examples:

- filesystem formatting;
- partition or mount changes;
- firewall changes;
- SSH configuration;
- user/group administration;
- credential rotation;
- Tailscale/network configuration;
- database schema recovery or destructive database actions;
- backup deletion;
- restoring backups over live data;
- deleting persistent application data;
- host operating-system upgrades;
- changes that could remove remote access.

Kerrigan may diagnose and propose these changes.

It should not independently execute them.

---

## 9. Privilege Model

Kerrigan should **not** receive unrestricted passwordless sudo.

Instead, privileged operations should be exposed through narrow mechanisms such as:

- allowlisted scripts;
- restricted sudoers commands;
- service-specific APIs;
- Docker permissions where appropriate;
- Paperclip-governed tools;
- infrastructure-repository workflows.

Example conceptual interface:

```text
server.service.status(name)
server.service.restart(name)

server.logs.read(service, since)

server.job.retry(job_id)

server.health.run(check)

server.disk.status()

server.change.propose(...)
```

A narrow tool surface improves:

- safety;
- auditability;
- reproducibility;
- portability between agent runtimes.

The agent should ask for capabilities, not raw root shells.

---

## 10. Deterministic Verification

Kerrigan must not decide success merely because a command returned no obvious error.

Every repair should have an objective success criterion.

Examples:

### Service recovery

```text
container running
+
health check passes
+
restart count stable
```

### Database recovery

```text
Postgres accepts connection
+
Paperclip query succeeds
+
database health check passes
```

### Storage recovery

```text
expected UUID mounted
+
path writable
+
free space acceptable
```

### Failed ingestion

```text
job rerun
+
validation succeeds
+
artifact reaches expected destination
```

### Configuration patch

```text
configuration validates
+
service restarts successfully
+
functional health check passes
```

The principle is:

> **Agents interpret evidence. Deterministic systems establish facts.**

---

## 11. Human Escalation

Kerrigan should create a Paperclip attention item when:

- proposed action exceeds authority;
- requirements are ambiguous;
- multiple consequential remedies are plausible;
- credentials are required;
- repair could destroy data;
- networking or remote access may be affected;
- security posture would materially change;
- costs would be incurred;
- the same automated repair repeatedly fails;
- Kerrigan and an independent reviewer disagree;
- confidence remains low after investigation.

A useful escalation should be concise.

Example:

```text
PAPERCLIP DATABASE DISK PRESSURE

Status:
Postgres volume is at 91%.

Cause:
Database + retained logs grew 18 GB over the last month.

Recommendation:
Reduce log retention from 90 to 30 days.

Alternative:
Expand the data volume.

Risk:
Low for retention change; no database rows affected.

[Approve retention change]
[Choose storage expansion]
[Ask Kerrigan]
[Review evidence]
```

---

## 12. Bounded Recovery

Kerrigan should never enter an unbounded repair loop.

Example policy:

```text
attempt repair
   ↓
verify
   ↓
failed
   ↓
one revised attempt
   ↓
verify
   ↓
failed
   ↓
escalate
```

The exact number of attempts can vary by runbook.

Repeated failure should increase attention, not model usage.

---

## 13. Incident Reporting

Completed routine incidents should produce short reports.

Example:

> **Media ingestion recovered**
>
> `/mnt/media` was unavailable after the SSD remounted, causing ffprobe validation failures. The ingestion worker's mount dependency was corrected, the service was restarted, and the queued item was successfully reprocessed. Health checks are passing. No action required.

A report should include:

- incident;
- cause;
- action;
- verification;
- follow-up if any.

Verbose diagnostic material remains attached to the Paperclip work item and logs rather than appearing in the summary.

---

## 14. Incident History

Over time, incidents should form an operational knowledge base.

Useful reusable information includes:

- failure signature;
- affected service;
- confirmed root cause;
- successful fix;
- unsuccessful fixes;
- verification procedure;
- frequency;
- related configuration;
- associated runbook.

Kerrigan should search this history during diagnosis.

Repeated incidents should trigger a different response:

> **Do not keep fixing the symptom. Propose a permanent architectural correction.**

---

## 15. Runbooks

High-frequency operational problems should become deterministic runbooks.

Examples:

```text
paperclip/restart
paperclip/database-health
storage/mount-recovery
media/retry-ingestion
backup/verify
docker/container-restart-loop
disk/space-pressure
```

A runbook can define:

- diagnostic commands;
- allowed remediation;
- verification;
- escalation criteria.

As runbooks mature, Kerrigan should need less model reasoning for routine incidents.

This creates a virtuous cycle:

```text
novel incident
   ↓
agent diagnosis
   ↓
successful repair
   ↓
runbook captured
   ↓
future incident becomes cheaper and safer
```

---

## 16. Observability Implementation

The initial implementation should remain simple.

The design does **not** require immediately deploying a large observability stack.

The MVP needs only:

1. reliable service logs;
2. basic host/service metrics;
3. deterministic health checks;
4. a small alerting mechanism;
5. a path from alert → Paperclip work item.

Potential future technologies might include:

- systemd journal;
- Docker logging;
- Prometheus-compatible metrics;
- Grafana;
- Loki;
- Alertmanager;
- ntfy or another notification layer.

Selection should follow Overmind's reuse-first principle.

Do not introduce a full telemetry platform until the operational need justifies it.

---

## 17. Project and Service Awareness

Kerrigan is primarily responsible for **Overmind infrastructure**, but alerts should retain project identity when applicable.

Examples:

```text
service: paperclip
project: overmind
```

or:

```text
service: gather-model-worker
project: gather
```

This allows operational incidents to remain associated with the systems they affect while still flowing through a shared infrastructure administration layer.

---

## 18. Substrate Integration

Kerrigan may use Substrate for durable operational knowledge such as:

- architecture decisions;
- server documentation;
- service inventory;
- runbooks;
- incident summaries;
- infrastructure repository;
- migration notes;
- recovery procedures.

Substrate remains canonical.

Kerrigan's Paperclip work items reference that material rather than replacing it.

---

## 19. Paperclip Integration

Paperclip should own Kerrigan's work lifecycle:

```text
alert
  ↓
issue/work item
  ↓
assignment
  ↓
diagnosis
  ↓
Decision if required
  ↓
repair
  ↓
review/verification
  ↓
completion
```

Paperclip also provides:

- audit history;
- human inbox;
- approvals;
- schedules/routines;
- agent identity;
- work-product references.

Kerrigan should not create a separate operational ticket system unless a future requirement clearly demands one.

---

## 20. Initial Scope

The first Kerrigan implementation should be intentionally modest.

### Monitor initially

- Paperclip;
- Paperclip PostgreSQL;
- Docker health;
- external SSD mount and capacity;
- backup jobs;
- selected media/ingestion services as they come online.

### Initial autonomous actions

- gather diagnostics;
- restart approved containers;
- retry approved idempotent jobs;
- run health checks;
- produce incident reports.

### Initially require human approval for

- configuration edits;
- package/image upgrades;
- database modifications;
- networking;
- permissions;
- storage/mount configuration;
- destructive actions.

Authority can expand only after successful operational experience.

---

## 21. Example Incident

```text
ALERT
paperclip unavailable
       ↓
Kerrigan receives Paperclip work item
       ↓
checks:
- Paperclip container
- Postgres container
- disk
- recent logs
       ↓
finds:
Postgres health check failing due to disk full
       ↓
checks runbook
       ↓
identifies safe temporary cleanup
       ↓
Level 2 approved?
       │
      yes
       ↓
clean approved temporary files
       ↓
restart Postgres if required
       ↓
deterministic health checks
       ↓
Paperclip endpoint returns healthy
       ↓
incident summary
       ↓
close
```

If cleanup would require deleting persistent data:

```text
Kerrigan
   ↓
Paperclip Decision
   ↓
human approval
   ↓
continue
```

---

## 22. Security Principles

Kerrigan should follow these rules:

1. Least privilege.
2. No blanket root shell.
3. Every state-changing action is attributable.
4. Secrets are accessed only when required by an approved tool.
5. Sensitive values never appear unnecessarily in logs or reports.
6. Destructive operations require explicit approval.
7. Critical access paths cannot be modified autonomously.
8. Recovery actions must be bounded.
9. Successful commands are not equivalent to successful outcomes.
10. Configuration changes should be reproducible.

---

## 23. Reliability Principles

Kerrigan itself must not become a new single point of failure.

If Kerrigan is unavailable:

- services continue operating;
- logs continue accumulating;
- deterministic alerts remain available;
- Paperclip retains pending work;
- human administration remains possible.

Kerrigan improves operations.

It does not become required for basic system survival.

---

## 24. Success Criteria

Kerrigan is successful when routine operational failures increasingly follow this pattern:

```text
something breaks
      ↓
monitoring notices
      ↓
Kerrigan investigates
      ↓
safe repair performed
      ↓
objective verification passes
      ↓
short report appears
```

rather than:

```text
something breaks
      ↓
human eventually notices
      ↓
SSH into server
      ↓
search logs manually
      ↓
remember how service works
      ↓
debug from scratch
```

Human attention should progressively move from operational toil toward consequential decisions.

---

## 25. Concise Agent Charter

> **Kerrigan is Overmind's server administrator. She receives actionable infrastructure alerts, gathers relevant evidence, diagnoses failures, applies bounded and reversible repairs within delegated authority, verifies recovery using deterministic checks, records incidents, and escalates consequential decisions through Paperclip. She does not continuously consume raw logs, receive unrestricted administrative privileges, or substitute agent judgment for objective system state.**

---

## 26. Guiding Principle

> **Observe deterministically. Diagnose intelligently. Repair conservatively. Verify objectively. Escalate selectively.**
