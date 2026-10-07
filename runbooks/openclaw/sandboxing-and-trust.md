# Sandboxing and Trust

**Status:** PARTIAL — verified end-to-end on the live host as of 2026-10-07.
Deliberately simple by design: plain built-in-OpenClaw defaults, no custom
worker-isolation architecture. Delegated-work isolation is an explicitly
deferred, separate future project — see the note at the bottom.

## Current architecture (verified 2026-10-07)

```text
Kerrigan (main) / Soma
  → built-in OpenClaw runtime (agentRuntime.id: "openclaw")
  → sandbox.mode: "off" — every session, any topic, consistent capability
  → ordinary sessions_spawn delegation, no forced agentId, no separate
    worker identity — a spawned child is just agent:<id>:subagent:<uuid>
    under the same identity, with the same capability as its parent
```

Only two agents exist: `main` (Kerrigan) and `soma` (Soma). No separate
worker-agent identities. The deciding idea, stated plainly: **different
conversations with the same agent should primarily differ in context, not
capability.** Home, a brand-new topic, and a delegated subagent all get the
same tools and host access, because nothing in the current config
distinguishes them. Isolating delegated work is a real, separate question —
deliberately not solved here (see bottom).

## History: why this took three iterations to get right

### Iteration 1 — session-key-based trust (`non-main` + per-chat opt-outs)

Original model: `sandbox.mode: "non-main"` sandboxed everything except the
one fixed `agent:<id>:main` key; specific trusted conversations (the
Android app's session) needed an individual `sessions.patch` with
`sandboxMode: "off"` to match Home. Worked, but caused a real,
OpenClaw-acknowledged "common surprise": a brand-new topic with the *same*
trusted agent started sandboxed by default.

### Iteration 2 — agent-identity-based trust with separate worker identities

Investigating the iteration-1 friction surfaced a bigger, real problem:
Kerrigan and Soma were running on the **Codex harness**, which has its own
native `spawn_agent` delegation tool, completely separate from OpenClaw's
`sessions_spawn`. A real test confirmed a `spawn_agent` call produced
**zero trace** in OpenClaw's session/audit system — full parent capability,
no sandboxing, nothing visible to `sandbox explain`. OpenClaw's own docs
confirm the model is actively steered toward `spawn_agent` over
`sessions_spawn` for "Codex-native subagent work." That meant Codex's own
delegation path could silently bypass any isolation built around
`sessions_spawn`, independent of config.

The fix at the time: migrate off Codex onto OpenClaw's built-in runtime
(`agentRuntime.id: "openclaw"`, confirmed to work with the existing
ChatGPT/Codex subscription auth — no native `spawn_agent` equivalent exists
there at all), set `sandbox.mode: "off"` on both resident agents for
topic-consistency, and — to preserve *some* delegated-work isolation given
that "off" removes sandboxing from an identity's own spawned children too —
introduce dedicated, always-sandboxed `kerrigan-worker`/`soma-worker`
identities with `subagents.requireAgentId`/`allowAgents` forcing all
delegation through them.

This worked and was verified thoroughly (runtime, MCP, host access, and
real write/read isolation probes all passed). But it added two persistent
agent identities and forced-routing config whose only purpose was
delegated-work isolation — complexity the resident agents' own design
didn't call for, and a real departure from plain OpenClaw defaults.

### Iteration 3 — back to plain defaults, isolation deferred (current)

Explicit decision: keep the Codex-harness fix (built-in runtime, `sandbox.mode:
"off"` for topic-consistency — both genuinely needed and unrelated to the
worker-identity question), but **remove the worker-identity layer
entirely**. `kerrigan-worker`/`soma-worker` deleted (`openclaw agents delete
<id> --force`, then `rm -rf` their leftover workspace directories — the CLI
doesn't always clean those up). `subagents.requireAgentId`/`allowAgents`
removed from both agents. Delegation is now ordinary `sessions_spawn`
behavior: a spawned child is `agent:<id>:subagent:<uuid>` under the same
identity, with the same capability as its parent — no isolation, by
deliberate choice, until a dedicated future project addresses it properly.

Per-spawn `model`/`thinking` selection was **never** tied to agent identity
either way — a point worth remembering, since it's easy to conflate "needs
a separate agent" with "needs different model/effort," and they're
unrelated. `sessions_spawn`'s own `model`/`thinking` parameters handle that
regardless of whether the child shares the parent's identity.

## Real regressions hit along the way (all resolved)

- **Existing conversation history doesn't survive a runtime switch.**
  Any session with history accumulated under the Codex harness fails
  outright (`ChatGPT Responses stream terminated`, `failureKind:
  "provider-failure"`, retries exhausted) when continued on the built-in
  runtime. `sessions compact` doesn't fix it. Fix: `openclaw gateway call
  sessions.reset --params '{"key":"<session key>"}'` for `main` (fixed key,
  can't be deleted), or `openclaw sessions delete <key> --agent <id> --yes`
  for others (recreated fresh on next message). Loses raw history only —
  memory files, recipes, workspace state are untouched. Confirm with the
  user before resetting a conversation they've actually used.
- **Docker/sudo-scoped host admin access needs `tools.elevated` on the
  built-in runtime.** Kerrigan's scoped Docker-read sudoers grant worked
  under Codex but failed on the built-in runtime ("elevated execution is
  unavailable in this runtime") — its `exec` tool routes privilege
  escalation through `tools.elevated.enabled` (default off), which Codex's
  native exec didn't enforce the same way. Fix:
  `agents.entries.main.tools.elevated.enabled: true`. Confirmed with a real
  `sudo docker ps -a` call.
- **"Worker turn session key does not match its placement."** Traced to
  source (`worker-turn-failure-*.mjs`): `resolvePlacementIdentityField`
  throws this whenever a **persisted placement record** exists whose
  `sessionKey` doesn't match a new turn's claim — i.e. stale leftover
  placement state from an earlier interrupted run, unrelated to
  `sandbox.mode`. Hits any `sessionTarget: "isolated"` automation
  (OpenClaw's own built-in weekly Skill Workshop review, in this case).
  **Do not disable the automation as a workaround** — that silences the
  symptom and leaves the real automation broken. Fix: `openclaw gateway
  call sessions.reset --params '{"key":"<affected cron session key>"}'`
  clears the stale placement. Verify with `openclaw cron run <job-id>
  --wait --wait-timeout 5m --json` — should return
  `"completionStatus": "succeeded"`.
- **Git "dubious ownership" on Kerrigan's own direct host commands.**
  Running as the `openclaw` Unix user against a repo owned by a different
  user (`austin`) trips Git's safe-directory check even outside a sandbox.
  Not yet given a permanent fix — currently handled ad hoc per command. If
  it becomes a recurring friction, the fix is a host-level
  `git config --system --add safe.directory /opt/overmind`.

## Sandboxing backend (for if/when it's needed again)

Rootless Podman, not Docker-group membership, remains the right choice if
sandboxing is reintroduced for any agent — Docker-group membership is
root-equivalent. Real one-time host prerequisites for rootless Podman on a
`useradd --system` account:

```bash
sudo usermod --add-subuids 100000-165535 --add-subgids 100000-165535 openclaw
sudo -u openclaw podman system migrate
sudo loginctl enable-linger openclaw
```

Sandbox image, if rebuilt: `debian:bookworm-slim`, non-root `sandbox` user,
`bash ca-certificates curl git jq python3 ripgrep`, plus (needed for any
repository research to work at all):

```dockerfile
FROM localhost/openclaw-sandbox:bookworm-slim
USER root
RUN git config --system --add safe.directory '*'
USER sandbox
```

Without this, `git log`/`git show` on a bind-mounted repo fails with
"dubious ownership" — Git's own safety check, not a real security block.

## MCP servers and tool access

Garmin is Soma's integration (`mcp.servers.garmin`, streamable-http,
`127.0.0.1:8001/mcp`, 55-tool `toolFilter.include` allowlist). **MCP
servers are not agent-scoped by default** — a disposable test agent got
full Garmin access with zero configuration simply because nothing had
denied it. Kerrigan has an explicit `tools.deny: ["garmin__*"]` for
hygiene; this is independent of the sandbox/runtime work above and kept as
agent-hygiene, not revisited in the iteration-3 simplification.

**Stated plainly, not implied:** hiding MCP tool names from an
unsandboxed, host-capable agent is not a hard security boundary. Kerrigan
can execute arbitrary host commands — she could reach Garmin's HTTP
endpoint directly or read stored credentials from disk regardless of her
OpenClaw tool list. `tools.deny` raises the bar from "accidental" to
"deliberate," which is worth having, but isn't a substitute for not giving
an agent host-admin capability and sensitive credentials on the same host.

## Diagnostic commands

```bash
openclaw agents list
  # confirm the roster: just main, soma — no leftover worker/test agents

openclaw sandbox explain --agent <id> --session <key> --json
  # sandbox.sessionIsSandboxed should be false everywhere right now —
  # Home, any topic, any spawned subagent, for both agents

openclaw sessions list --agent <id> --json
  # delegated children appear as agent:<id>:subagent:<uuid>, same agent,
  # not a separate identity

openclaw cron run <job-id> --wait --wait-timeout 5m --json
  # manually trigger an automation to verify end-to-end rather than
  # waiting for its real schedule; check completionStatus
```

## Deferred: delegated-work isolation

Explicitly out of scope for the current architecture. Right now, a
subagent spawned by Kerrigan or Soma has exactly the same capability as
its parent — no sandbox, no scoped filesystem access, nothing. This is a
known, accepted gap, not an oversight. If/when it's worth solving:

- The session-key-based approach (`non-main` mode) is simple but
  reintroduces the topic-inconsistency friction that iteration 1 and 2
  were both trying to fix.
- The separate-worker-identity approach (iteration 2, above) works and was
  fully verified, but adds real persistent complexity — extra agents,
  forced routing config — that's hard to justify without an actual
  security requirement driving it.
- Whatever approach is chosen, re-verify worker isolation with the exact
  same empirical tests used in iteration 2: real write attempts against a
  canonical repo (expect read-only filesystem failure), real reads of
  `/etc/shadow` or another host secret (expect permission denied), and
  confirmation that the isolation actually traces back to the sandbox
  boundary and not to something that happens to look similar.

Treat this as its own project with its own acceptance criteria, not
something to compensate for inside the resident-agent config again.
