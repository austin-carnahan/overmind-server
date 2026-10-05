# Sandboxing and Trust

**Status:** PARTIAL — verified end-to-end on the live host as of 2026-10-02,
following a full migration off the Codex harness onto OpenClaw's built-in
runtime (see history below for why). One known regression (Docker/elevated
exec) is flagged and still open.

## Current architecture (verified 2026-10-02)

```text
Kerrigan (main) / Soma
  → built-in OpenClaw runtime (agentRuntime.id: "openclaw")
  → sandbox.mode: "off" — every session, any topic, consistent capability
  → delegation forced to a separate worker identity: subagents.requireAgentId
    + subagents.allowAgents: ["<agent>-worker"]

kerrigan-worker / soma-worker
  → separate agent identities, never used as a human-facing conversation
  → sandbox.mode: "all" — every session sandboxed unconditionally, podman
  → kerrigan-worker only: read-only reference binds (/reference/overmind,
    /reference/ssd1)
  → cheap model (gpt-6-luna), also forced onto the built-in runtime
```

The deciding idea: **trust is per agent identity, not per session key.**
Kerrigan and Soma are always trusted, in any conversation, because there's
no longer a session-key-based sandbox boundary on their own identity at
all. Isolation lives entirely in the separate worker identities, which are
*always* sandboxed regardless of who's asking — there's no "main" exemption
for a worker to accidentally land in.

### Why this replaced the earlier session-key-based model

The original model (`sandbox.mode: "non-main"`, per-chat `sandboxMode:
"off"` opt-outs for specific trusted sessions) worked, but caused a real,
OpenClaw-acknowledged "common surprise": a brand-new topical conversation
with the *same* trusted agent, from the *same* owner, started sandboxed by
default and needed an explicit manual opt-out to match Home's capability.
Investigating *why* led to a bigger finding, traced to source:

- OpenClaw's own named-operator-role `sandbox: "required"` mechanism only
  ever evaluates `actor.type === "human"`
  (`resolveCreatorSandbox` in `operator-role-policy-*.mjs`) — it has no
  visibility into agent-spawned sessions at all.
- Worse: on the **Codex harness** (which Kerrigan and Soma both ran on),
  Codex has its own **native `spawn_agent` delegation tool**, completely
  separate from OpenClaw's `sessions_spawn`. A real test confirmed a
  `spawn_agent` call produced **zero trace** in OpenClaw's session/audit
  system — it ran inside the same Codex thread as the parent, inheriting
  the parent's own capability, with no sandboxing, no tracked session key,
  nothing visible to `sandbox explain`. OpenClaw's own docs confirm the
  model is actively steered toward preferring `spawn_agent` over
  `sessions_spawn` for "Codex-native subagent work" — i.e. toward the path
  with no isolation, not away from it.

That meant the Codex harness's own native delegation mechanism could
silently bypass whatever isolation we built around `sessions_spawn`,
independent of anything we configured. Patching around it (prompt-level
"never use spawn_agent" instructions, denying it via tool policy) wasn't a
real fix — denying it isn't even possible without pushing the whole turn
onto Codex's "restricted native surface" (losing Code Mode and MCP
entirely), and prompt-level bans are not an enforcement boundary.

**The actual fix: stop running two execution systems.** OpenClaw's
built-in runtime has no native `spawn_agent` equivalent at all — delegation
only ever happens through `sessions_spawn`, which is fully tracked and
subject to `requireAgentId`/`allowAgents`/`sandbox: "require"`. Switching
both resident agents onto it, combined with dedicated always-sandboxed
worker identities, closes the gap structurally instead of compensating for
it.

### Migration verification (all passed, 2026-10-01/02)

Tested first with a disposable `test-runtime`/`test-worker` pair before
touching Kerrigan or Soma:

1. Built-in runtime runs normally on the existing ChatGPT/Codex subscription
   auth — confirmed via `docs/providers/openai/runtimes.md`: *"An explicit
   `agentRuntime.id: 'openclaw'` keeps a Codex-eligible route on OpenClaw."*
   No new login, same model, same credential profile.
2. Normal MCP access confirmed (real `garmin__search_foods` call).
3. Ordinary tool execution confirmed (`exec`, unsandboxed main session).
4. Delegation to a separately-configured Podman-sandboxed worker, forced via
   `requireAgentId`+`allowAgents`, correctly denied host write/read
   (`/opt/overmind` write: read-only fs; `/etc/shadow` read: permission
   denied).
5. **No native `spawn_agent` or Codex-specific delegation tool exists on
   the built-in runtime at all** — asked directly, confirmed absent.

Then migrated Soma, then Kerrigan, with the same real (not just configured)
checks at each step: runtime confirmed, MCP/host access confirmed from
Home *and* a brand-new never-opted-in topic, worker isolation confirmed
with real write/read probes against the real reference binds.

### Real regressions found during migration — don't assume a clean port

- **Existing conversation history doesn't survive a runtime switch.** Any
  session with substantial history accumulated under the Codex harness
  fails outright (`ChatGPT Responses stream terminated`,
  `failureKind: "provider-failure"`, 3 retries exhausted) when continued
  on the built-in runtime — confirmed on both agents' `main` and Android
  sessions. `sessions compact` doesn't fix it (returns "Already
  compacted" if prior compaction already ran). Brand-new sessions on the
  new runtime work perfectly. The fix: `openclaw gateway call
  sessions.reset --params '{"key":"<session key>"}'` for `main` (special
  key, can't be deleted), or `openclaw sessions delete <key> --agent <id>
  --yes` for others (recreated fresh on next message). This loses raw
  conversation history — not memory files, recipes, or other workspace
  state, which are untouched. Confirm with the user before resetting a
  conversation they've actually been using.
- **Docker/sudo-scoped host admin access broke, then was fixed.** Kerrigan's
  scoped Docker-read sudoers grant worked under the Codex harness but
  failed on the built-in runtime with "elevated execution is unavailable in
  this runtime" — the built-in runtime's own `exec` tool routes anything
  needing privilege escalation through OpenClaw's `tools.elevated` gate
  (default: disabled), which the Codex harness's own native exec apparently
  didn't enforce the same way. **Resolved 2026-10-05**: set
  `agents.entries.main.tools.elevated.enabled: true`. Confirmed with a real
  `sudo docker ps -a` call — succeeded, `garmin-mcp` listed correctly. No
  further `allowFrom` scoping was needed in this single-operator setup.

## Sandboxing backend

Rootless Podman, not Docker-group membership — a deliberate
privilege-boundary decision, since Docker-group membership is
root-equivalent (full access to `docker.sock`). Real one-time host
prerequisites for rootless Podman on a `useradd --system` account (none of
these apply automatically the way they would for a normal login user):

```bash
# subuid/subgid range allocation
sudo usermod --add-subuids 100000-165535 --add-subgids 100000-165535 openclaw
sudo -u openclaw podman system migrate

# systemd cgroup delegation for a non-interactive account
sudo loginctl enable-linger openclaw
```

Sandbox image: built from the inline Dockerfile in OpenClaw's own
sandboxing docs (`debian:bookworm-slim`, non-root `sandbox` user, with
`bash ca-certificates curl git jq python3 ripgrep` installed), plus one
real patch needed for repository research to actually work:

```dockerfile
FROM localhost/openclaw-sandbox:bookworm-slim
USER root
RUN git config --system --add safe.directory '*'
USER sandbox
```

Without this, `git log`/`git show` on a read-only bind-mounted repo fails
with "dubious ownership" (Git's own safety check against the container's
UID not matching the mounted repo's owner) — not a real security block,
just a usability gap. After rebuilding the image, run
`openclaw sandbox recreate --agent <id> --force` to retire existing
containers so new sessions pick it up.

Worker reference binds (`kerrigan-worker` only — Soma's research doesn't
need host filesystem access):

```json5
docker: {
  binds: [
    "/opt/overmind:/reference/overmind:ro",
    "/mnt/disks/ssd1:/reference/ssd1:ro",
  ],
  dangerouslyAllowExternalBindSources: true,  // required: both sources are
                                               // outside any agent workspace
}
```

`/mnt/disks/ssd1` is a single bind covering what would otherwise be four
separate mounts (`/mnt/substrate`, `/mnt/library`, `/mnt/models`,
`/mnt/downloads` are all bind-mounts of subdirectories of that one physical
disk, confirmed via `lsblk`/`fstab`) — bind the real physical mountpoint
once instead of each logical view separately.

Do not mount broad filesystem roots (`/`, `/home`, `/etc`) "for
convenience" — bind only the specific, reviewed paths a worker actually
needs, and default every bind to `:ro` unless a write is a genuine
requirement.

## MCP servers and tool access

Garmin is Soma's integration (`mcp.servers.garmin`, streamable-http,
`127.0.0.1:8001/mcp`, 55-tool `toolFilter.include` allowlist — expanded
from 46 with custom-food CRUD, `upsert_and_log`, nutrition daily
settings). **Correction to an earlier assumption:** MCP servers are *not*
agent-scoped by default — a brand-new disposable test agent got full
Garmin access with zero configuration, simply because nothing had ever
denied it. Scoping requires an explicit `tools.deny` on every agent that
shouldn't have it (`agents.entries.main.tools.deny: ["garmin__*"]` and
the same on `kerrigan-worker`) — denying on the *other* agents, not
relying on an allowlist on Soma, matches how OpenClaw's deny/allow
precedence actually works (a global allow can't be overridden by a
per-agent deny for the same names the other way around).

**Important limitation, stated plainly rather than let it imply false
security:** hiding MCP tool names from an unsandboxed, host-capable agent
(Kerrigan) is *not* a hard security boundary. Kerrigan can execute
arbitrary host commands — she could reach Garmin's HTTP endpoint directly
(`curl http://127.0.0.1:8001/mcp`) or read stored credentials from disk
regardless of what her OpenClaw tool list shows. The `tools.deny` entry
raises the bar from "trivial/accidental" to "deliberate code execution,"
which is worth having, but it is not a substitute for not giving an agent
host-admin capability and sensitive credentials on the same host in the
first place. This is an accepted, structural limitation of giving any
agent real host administration authority — not something more config can
close.

## Diagnostic commands for this architecture

```bash
openclaw sandbox explain --agent <id> --session <key> --json
  # → sandbox.sessionIsSandboxed should be false for main/soma, true for
  #   any *-worker session, regardless of which session key

openclaw agents list
  # confirm the full roster: main, soma, kerrigan-worker, soma-worker —
  # no leftover disposable test agents

openclaw sessions list --agent <worker-id> --json
  # delegated child sessions appear as agent:<worker-id>:subagent:<uuid>,
  # with spawnedBy/createdActor pointing back to the parent — this
  # provenance is exactly what native spawn_agent lacked
```

## Historical note: per-chat sandbox opt-outs (retired 2026-10-02)

Before this migration, trust was granted per *session key*: `non-main`
mode sandboxed everything except the fixed `agent:<id>:main` key, and
specific trusted conversations (e.g. the Android app's `agent:<id>:node-*`
session) needed an individual `sessions.patch` with `sandboxMode: "off"`
to match Home's capability. That mechanism still exists in OpenClaw and
is documented upstream, but it's no longer how Kerrigan or Soma get their
trust — superseded by the agent-identity-based model above. Kept here only
because the mechanism (`openclaw gateway call sessions.patch --params
'{"key":"<key>","sandboxMode":"off"}'`) may still be useful for a future
agent that *does* want session-key-based trust instead of the full
separate-worker-identity architecture.
