# Agents and Model Routing

**Status:** PARTIAL — current real config and resolution order are verified;
this will keep changing as model lineups change.

## Agents and workspace files

Two resident agents on `overmind-01` today:

### Kerrigan (`main`)

**Role:** resident Overmind systems operator — host administration,
troubleshooting, infrastructure change.

Workspace: `/home/openclaw/.openclaw/workspace`
(`AGENTS.md`, `SOUL.md`, `USER.md`, `IDENTITY.md`, plus `memory/`).

Primary architectural source of truth: `/opt/overmind` (the canonical
deployed repo checkout). Kerrigan is expected to inspect both canonical repo
state and live host state before durable infrastructure changes — not trust
either alone.

### Soma (`soma`)

**Role:** fitness, nutrition, and health-data coach.

Workspace: `/home/openclaw/.openclaw/agents/soma/workspace`
(`AGENTS.md`, `SOUL.md`, `USER.md`, `IDENTITY.md`, `BOOTSTRAP.md`,
`DREAMS.md`, plus `memory/`).

Primary external capability: Garmin MCP (`mcp.servers.garmin`, 46 curated
tools — health metrics, activities, training, nutrition read/write, workout
create/schedule). See
[MCP Servers and Tool Access](sandboxing-and-trust.md#mcp-servers-and-tool-access)
for the real sandboxing interaction.

### Workspace file responsibilities (both agents)

```text
AGENTS.md  → role, operating policy, workspace conventions, tool behavior
SOUL.md    → temperament, personality, communication style, boundaries
USER.md    → stable user preferences/directives (dated, superseded in place)
MEMORY.md  → curated durable decisions and learned context (main session only)
memory/    → recent/session-level raw notes
Skills     → repeatable specialist procedures, lazily loaded (name+description
             in every prompt; full SKILL.md read only when selected)
```

Both agents' `AGENTS.md` carry a near-identical "Model Routing and
Delegation" section describing the escalation ladder below in policy terms,
deliberately *without* hardcoding model names — those live in config, not in
the agent's own instructions, so the policy survives a future model lineup
change.

Native subagents only receive `AGENTS.md` from bootstrap — confirmed from
OpenClaw's own subagent docs: *"Sub-agent context only injects `AGENTS.md`
(no `SOUL.md`, `IDENTITY.md`, `USER.md`, `MEMORY.md`, or `BOOTSTRAP.md`)."*
Parent-only persona/identity/user context is instead folded into the spawn
call as turn-scoped instructions, specifically so children don't clone the
parent's persona. This is why operational/delegation policy belongs in
`AGENTS.md`, not `SOUL.md` — a Skill alone wouldn't reach subagents any more
reliably, but `AGENTS.md` is guaranteed to.

## Model routing and reasoning effort

Real current config (`openai/gpt-6-*` family):

```text
agents.defaults.model                                        = {"primary": "openai/gpt-6-sol"}
agents.defaults.subagents.model                               = "openai/gpt-6-luna"
agents.defaults.utilityModel                                  = "openai/gpt-6-luna"

agents.defaults.models["openai/gpt-6-luna"].params.thinking    = "low"
agents.defaults.models["openai/gpt-6-sol"].params.thinking     = "medium"
agents.defaults.models["openai/gpt-6-astra"].params.thinking   = "high"

agents.defaults.models["openai/gpt-6-sol"].agentRuntime.id     = "openclaw"
agents.defaults.models["openai/gpt-6-luna"].agentRuntime.id    = "openclaw"
agents.defaults.models["openai/gpt-6-astra"].agentRuntime.id   = "openclaw"

agents.entries.<id>.thinkingDefault                            = UNSET (deliberately)
agents.defaults.thinkingDefault                                 = UNSET
```

Rationale: Sol (mid-tier, built for coding/agentic work) as the shared
primary/parent model; Luna (high-volume, low-complexity) for routine
subagents and utility calls; Astra (flagship) reserved for explicit
escalation on exceptional difficulty.

**All three forced onto OpenClaw's built-in runtime**, not the Codex
harness both resident agents originally ran on. This is a 2026-10-02
architecture change, not the original default — see
[Sandboxing and Trust](sandboxing-and-trust.md) for the full reasoning
(Codex's native `spawn_agent` delegation bypassed our sandbox/audit
entirely) and the real migration regressions found (existing conversation
history doesn't survive the runtime switch; a Docker/elevated-exec
permission broke and needs re-granting). Confirmed via OpenClaw's own docs
that this keeps the exact same model and the exact same ChatGPT/Codex
subscription auth — `agentRuntime.id: "openclaw"` only changes which
runtime executes the turn, not which account or model answers it.

### Resolution order — the critical gotcha

Confirmed from OpenClaw's own thinking-levels doc, most-specific wins:

```text
1. Inline /think directive on a message
2. Session override (sticky, set by a directive-only message)
3. Per-agent thinkingDefault         (agents.entries.<id>.thinkingDefault)
4. Per-agent model default           (agents.entries.<id>.models[...].params.thinking)
5. Shared model default              (agents.defaults.models[...].params.thinking)
6. Global thinkingDefault            (agents.defaults.thinkingDefault)
7. Provider-declared fallback
```

**A per-agent `thinkingDefault` sits above per-model settings** and would
silently flatten the Luna=low/Sol=medium/Astra=high differentiation for that
agent. A **global** `thinkingDefault` sits below per-model settings, so it's
safe to use as a catch-all if desired — we chose to leave both unset rather
than risk the per-agent trap.

### Escalation mechanism

There is no separate router or automatic model-tier detection. Escalation is
just a `sessions_spawn` tool parameter the parent model chooses to set
(`model`, `thinking`), with a 3-tier precedence: explicit per-call override →
configured subagent default → inherited from parent. Both agents' `AGENTS.md`
encode *when* to escalate (ambiguity, destructive/irreversible ops,
consequential independent review) as policy; the actual model names stay in
config.

Prefer **economical workers for volume, stronger models for judgment** —
long or repetitive work alone is not a reason to escalate.

## Persistent agent state

Use the agent workspace for durable files that should survive sessions but
*not* be re-injected into every prompt turn — recipes, research notes,
reference files, small structured registries. Use memory files (`MEMORY.md`,
`memory/YYYY-MM-DD.md`) for durable decisions and context, not bulk
structured application data.

Prefer plain Markdown/YAML/JSON until actual scale justifies a database.
Workspaces live under real paths on the host filesystem
(`/home/openclaw/.openclaw/...`) — not disposable, not automatically backed
up by anything OpenClaw-specific. Treat them the same as any other durable
host state for backup purposes.
