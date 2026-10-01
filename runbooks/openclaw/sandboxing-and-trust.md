# Sandboxing and Trust

**Status:** PARTIAL — the trust model, sandbox config, mobile opt-out
procedure, and the Codex/MCP interaction are all verified end-to-end on the
live host as of 2026-10-01. This is the densest, fastest-moving part of the
whole OpenClaw setup — expect it to need updates as we add agents or change
harnesses.

## Session trust model

Don't equate `main session = trusted` / `non-main session = untrusted`. That
was the original working assumption and it was too coarse — it doesn't
distinguish a specific, known, persistent trusted conversation (e.g. a named
device's native app session) from an arbitrary new thread.

Current model:

```text
trusted operator conversation
  → explicit per-chat sandbox opt-out; may receive host/tool access
    equivalent to the agent's canonical main session

ordinary non-main conversation (new thread, channel DM, dashboard "New chat")
  → sandboxed by default, no opt-out

research / delegated worker (subagent)
  → sandboxed, with narrowly scoped read-only reference mounts, never
    standing host mutation authority
```

Trust is granted per **known, specific session key** (recorded below), not
by client type — a device being "the official mobile app" doesn't imply
trust by itself; the opt-out is applied explicitly and individually.

## Sandboxing

Default posture: `agents.defaults.sandbox.mode: "non-main"` — every session
except an agent's own canonical main session (`agent:<id>:main`, fixed, not
configurable) is sandboxed by default. Group/channel sessions always count as
non-main.

Real config in use (both agents inherit this from `agents.defaults.sandbox`
unless overridden):

```text
mode:            non-main
scope:           session       (one container per session, not shared)
backend:         podman        (rootless, not Docker)
workspaceAccess: ro
docker:
  image:         openclaw-sandbox:bookworm-slim
  readOnlyRoot:  true
  network:       none
  capDrop:       [ALL]
```

**Backend choice:** rootless Podman instead of adding `openclaw` to the
Docker group — a deliberate privilege-boundary decision, since Docker-group
membership is root-equivalent (full access to `docker.sock`). Real one-time
host prerequisites for rootless Podman on a `useradd --system` account (none
of these apply automatically the way they would for a normal login user):

```bash
# subuid/subgid range allocation
sudo usermod --add-subuids 100000-165535 --add-subgids 100000-165535 openclaw
sudo -u openclaw podman system migrate

# systemd cgroup delegation for a non-interactive account
sudo loginctl enable-linger openclaw
```

Sandbox image: built from the inline Dockerfile in OpenClaw's own sandboxing
docs (`debian:bookworm-slim`, non-root `sandbox` user, with
`bash ca-certificates curl git jq python3 ripgrep` installed). One real patch
on top of that recipe, needed for subagent repository research to actually
work (see below):

```dockerfile
FROM localhost/openclaw-sandbox:bookworm-slim
USER root
RUN git config --system --add safe.directory '*'
USER sandbox
```

Without this, `git log`/`git show` on a read-only bind-mounted repo fails
with "dubious ownership" (Git's own safety check against the container's UID
not matching the mounted repo's owner) — not a real security block, just a
usability gap. After rebuilding the image, run
`openclaw sandbox recreate --agent <id> --force` to retire existing
containers so new sessions pick it up (confirm first with
`openclaw sandbox list`).

Per-chat sandbox overrides are acceptable for **specific trusted persistent
conversations**. Do not disable sandboxing agent-wide or globally to fix one
trusted session.

## Android and mobile sessions

The native Android app creates/adopts a **dedicated device session**, not
the canonical `agent:<id>:main` session:

```text
agent:<id>:node-<device-suffix>
```

Both resident agents' Android sessions, confirmed trusted and opted out:

```text
agent:main:node-27eb2826b877   (Kerrigan)
agent:soma:node-27eb2826b877   (Soma)
```

Because these are `non-main` sessions, they inherit sandboxing by default —
this is *not* obvious from the Control UI label, which just shows the device
name. **Always inspect the real session key before assuming trust level**;
never guess from the display label.

### Per-chat opt-out procedure (verified, repeatable)

There is no dedicated CLI subcommand for this — it's a Gateway RPC method,
called through the generic RPC bridge:

```bash
# from a shell where `cd` has run first — see Diagnostics and Quirks
openclaw gateway call sessions.patch \
  --params '{"key":"<session key>","sandboxMode":"off"}' \
  --json
```

Pre-checks (all confirmed, not assumed):

1. Find the exact session key from `openclaw sessions list --agent <id> --json`
   — don't guess from the label.
2. Confirm `status: "done"` (idle) before patching; the Gateway refuses to
   change containment underneath a running turn anyway.
3. Confirm the session's `createdActor`/`createdVia` isn't bound to a named
   operator role with an immutable `sandbox: "required"` policy — that
   invariant can't be bypassed even by an admin.
4. `sandboxMode: null` clears the override and restores the configured
   policy, if ever needed.

Verify the result:

```bash
openclaw sandbox explain --agent <id> --session <session key> --json
# → sandbox.sessionIsSandboxed: false
# → sandbox.effectiveHostWorkspaceRoot: the real host workspace path,
#   not a /home/openclaw/.openclaw/sandboxes/workspace-* copy
```

The override persists across Gateway restarts and session resets. **New**
Android/other sessions do *not* inherit it automatically — this is a
one-session-at-a-time grant, by design.

**Safety-classifier note:** this exact RPC call can get hard-blocked by an
agent harness's own auto-mode safety classifier (flagged as "weakens
security") even when the human has explicitly authorized it in conversation
— no interactive approval prompt surfaces in that case. If that happens, the
human has to run the command themselves, switch out of auto mode for the
call, or add an explicit permission rule.

## MCP servers and tool access

MCP access is scoped intentionally by agent — Kerrigan has none configured
today; Soma has Garmin (`mcp.servers.garmin`, streamable-http,
`127.0.0.1:8001/mcp`, 46-tool `toolFilter.include` allowlist,
`codex.defaultToolsApprovalMode: "approve"`). Avoid exposing every sensitive
MCP integration to every agent by default.

Before concluding an MCP tool is "missing," distinguish these independently —
a failure at any one layer looks identical from the outside:

```text
1. MCP server health         → openclaw mcp probe <server> --json
2. MCP registration          → openclaw config get mcp.servers.<name>
3. agent tool policy         → agents.entries.<id>.tools
4. sandbox tool policy       → openclaw sandbox explain --session <key>
5. harness-specific restriction (see below)
6. session-specific state    → the exact session, not "the agent" in general
```

`openclaw mcp probe <server>` proves the server itself is healthy — it does
**not** prove a given agent session can see its tools. We hit this exact gap
twice (see [Diagnostics and Quirks](diagnostics-and-quirks.md)).

### Codex harness limitation — confirmed, unconditional, no workaround

When an agent runs on OpenClaw's **Codex harness** (`agentHarnessId:
"codex"`, both Kerrigan and Soma currently do), **any sandboxed session loses
all user-configured MCP servers for that turn** — dashboard or mobile, it
doesn't matter which. Confirmed from OpenClaw's own docs: *"When an OpenClaw
sandbox is active, the local Codex app-server process still runs on the
Gateway host. OpenClaw therefore disables Codex native Code Mode, user MCP
servers, and app-backed plugin execution for that turn."* Confirmed
empirically too: a sandboxed **dashboard** test session failed identically
to a sandboxed Android session, ruling out any channel-specific cause.

Why: the MCP connection is owned by the Codex app-server process running on
the Gateway host, *outside* the sandbox container. Letting a "sandboxed"
session keep using it would make the sandbox label fictional — the MCP tool
would still run with full host/network reach.

**No tool-policy allowlist fixes this.** The tools are not offered to the
model at all for a sandboxed Codex turn, regardless of `tools.allow`,
`agents.<id>.tools.allow`, or sandbox-scoped allow/deny. The experimental
`appServer.experimental.sandboxExecServer` flag does not help either — its
documented purpose is sandbox-backed *shell execution* streaming, not
restoration of user MCP servers.

**The only fix:** the same per-chat `sandboxMode: "off"` opt-out used for
trusted host-operator sessions, applied individually to any session that
genuinely needs MCP access (see Android/mobile procedure above). An ordinary
sandboxed session — a fresh dashboard chat, a channel DM, a subagent — is
*expected* to lack MCP tools, and that's correct, not a bug to chase.

**Future note, not solved here:** if sandboxed Soma subagents or channel
sessions ever need Garmin access, the fix isn't disabling sandboxing
globally — evaluate a different agent runtime/harness, or a future
OpenClaw-supported sandbox-to-MCP execution path.

## Subagents and repository access

Subagents remain sandboxed even when their parent agent is host-capable —
delegation never inherits the parent's unsandboxed status.

For repository-heavy research (reading docs, grepping source, reviewing Git
history, comparing implementation to design notes), expose only the specific
repositories needed, as **read-only Docker/Podman bind mounts**, scoped to
one agent via `agents.entries.<id>.sandbox.docker`:

```json5
{
  agents: {
    entries: {
      main: {
        sandbox: {
          docker: {
            binds: [
              "/opt/overmind:/reference/overmind:ro",
              "/mnt/disks/ssd1:/reference/ssd1:ro",
            ],
            // required: both sources are outside any agent workspace root
            dangerouslyAllowExternalBindSources: true,
          },
        },
      },
    },
  },
}
```

This is Kerrigan's real, live config — scoped to `agents.entries.main` only,
confirmed **not** to affect Soma (`agents.entries.soma.sandbox` stays unset,
inherits only the shared defaults with zero binds).

`/mnt/disks/ssd1` is a single bind covering what would otherwise be four
separate mounts (`/mnt/substrate`, `/mnt/library`, `/mnt/models`,
`/mnt/downloads` are all themselves bind-mounts of subdirectories of that one
physical disk, confirmed via `lsblk`/`fstab`) — bind the real physical
mountpoint once instead of each logical view separately.

Verified working inside a fresh sandboxed research session after this
config + an `openclaw sandbox recreate --agent main --force`:

- `ls`/`rg`/`git log` against both `/reference/overmind` and `/reference/ssd1`
  — real results, real Git history (after the safe.directory image fix).
- Write attempts (`touch /reference/overmind/...`) — fail: read-only
  filesystem.
- No access to `/etc/shadow`, `/home/austin`, or anything outside the
  explicit binds plus the normal sandbox workspace.

Do not mount broad filesystem roots (`/`, `/home`, `/etc`) "for convenience"
— bind only the specific, reviewed paths a worker actually needs, and
default every bind to `:ro` unless a write is a genuine requirement.
