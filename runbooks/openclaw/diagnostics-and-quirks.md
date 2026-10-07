# Diagnostics and Quirks

**Status:** PARTIAL by design — this is meant to keep growing. Append
concise, empirical entries rather than letting it become a narrative log.

## Diagnostics

First-line commands, all confirmed useful in practice:

```bash
openclaw config get <path>                 # confirm live config, not assumed
openclaw config set <path> <value> --merge --dry-run   # validate before writing
openclaw config schema                     # authoritative; don't assume docs match
openclaw models list
openclaw sessions list --agent <id> --json # real session keys, not display labels
openclaw sandbox explain --agent <id> --session <key> --json
openclaw sandbox list
openclaw sandbox recreate --agent <id> --force   # after image/bind config changes
openclaw mcp probe <server> --json         # server health only, not session visibility
openclaw mcp doctor
openclaw gateway call <method> --params '<json>' --json   # generic RPC bridge,
                                            # e.g. sessions.patch, sessions.get —
                                            # anything without its own CLI subcommand
```

When a tool is missing, inspect the **effective session**, not global
config. Always distinguish:

```text
configured  ≠  healthy  ≠  visible to this agent  ≠  usable in this session
```

A tool can pass every earlier check and still fail at the last one (see the
Codex/MCP sandbox quirk below) — don't stop investigating at "the server
probes clean."

## Known quirks

### `sudo -u openclaw` inherits an inaccessible cwd — looks exactly like a real bug, isn't

Running `sudo -u openclaw bash -lc '<command>'` from an interactive SSH
session inherits the **caller's** working directory (e.g. `/home/austin`) as
the child process's cwd — which the `openclaw` user has no permission to
traverse. This doesn't break simple commands, but it breaks anything that
does an *explicit* `chdir` in a spawned child process (Node's
`child_process.spawn` with an explicit `cwd` option does this). We hit this
twice, and both times it looked exactly like a real OpenClaw CLI bug:

- `openclaw qr` failed with `spawn /usr/bin/node EACCES; snapshot staging
  root ...: free disk space/quota or set XDG_CACHE_HOME` — looked like a
  disk-space or AppArmor problem. Root cause, confirmed by reading the
  actual source (`createSqliteSnapshotStagingDirectory` →
  `sqlite-readonly-worker`): an internal worker process tries to spawn
  `process.execPath` with an explicit `cwd`, and that `chdir` failed.
- `openclaw sandbox explain` failed the identical way.

**Fix:** always `cd` to somewhere the target user can access before running
anything as that user:

```bash
sudo -u openclaw bash -lc 'cd && openclaw sandbox explain ...'
```

Plain `node --version` or a `child_process.spawn` call *without* an explicit
`cwd` option works fine regardless — only code paths that explicitly set
`cwd` on a spawned child are affected. Don't waste time on AppArmor/disk
theories before ruling this out first; it's one `pwd` check
(`sudo -u openclaw bash -lc 'pwd'`) away from confirmed.

### Android "main" conversations are dedicated `node-*` sessions, not the agent's `main` key

The Control UI/mobile app shows a device label ("OpenClaw App · Pixel 10 ·
...") that gives no indication this is actually
`agent:<id>:node-<suffix>`, a distinct, `non-main` session key — not
`agent:<id>:main`. `sandbox.mode: non-main` therefore sandboxes native
mobile conversations by default, silently, unless you've specifically
checked. Always resolve the real session key before reasoning about its
trust level.

### Codex sandboxed turns disable user MCP servers — unconditional, no tool-policy fix

See [Sandboxing and Trust](sandboxing-and-trust.md#mcp-servers-and-tool-access)
for the full writeup. The short version: `openclaw mcp probe` succeeding
proves nothing about whether a *sandboxed* Codex-harness session can use
that server — it can't, period, regardless of tool policy.

### `mcp.*` config changes need an explicit Gateway restart; most other config does not

From the original Soma build ("0 MCP tools" debugging saga): `openclaw
config set`, `openclaw mcp add`, `openclaw mcp tools`, `openclaw mcp
configure` all need `sudo systemctl restart openclaw-gateway.service` before
the change reaches the live Gateway process — **regardless of what the CLI's
own "Change will apply without restarting the gateway" message says.**
Verify with a fresh PID (`ps aux | grep openclaw-gateway`) before trusting
anything downstream.

This does *not* generalize to all config changes — in this same project,
model-routing (`params.thinking`), `plugins.entries.device-pair`, and
per-agent `sandbox.docker.binds` changes all took effect live, exactly as
their own CLI messages claimed, confirmed by immediately spawning a real test
session afterward. The `mcp.*` namespace specifically is the one proven to
lie about this; don't assume the same caution universally applies, but don't
assume it never applies either — verify with a real spawned turn, not just
the CLI's own claim.

### Read-only mounted Git repos need `safe.directory` baked into the sandbox image

`git log`/`git show` against a bind-mounted repo (UID mismatch between the
sandbox container user and the mounted repo's host owner) fails with
"dubious ownership" unless `git config --system --add safe.directory '*'` is
baked into the sandbox image itself. Not a security issue — Git's own
safety check — but it silently breaks the "review Git history" use case for
research subagents if missed.

### Per-chat sandbox overrides persist, but don't propagate

A `sessions.patch` sandbox opt-out sticks to that exact session key forever
(survives Gateway restarts), but a **new** session — even from the same
device, even for the same agent — starts sandboxed again by default. This is
intentional (opt-outs are meant to be deliberate, one at a time), but easy to
forget if a trusted device's app ever gets reinstalled or its session
otherwise resets.

### An agent's own safety classifier can silently block an explicitly-approved action

Some sensitive action categories (loosening a sandbox boundary, e.g.) can be
hard-blocked by an assistant's own auto-mode safety classifier even after
the human has explicitly authorized the specific action in conversation — no
interactive approval prompt appears for the human to click through. If a
command that should work gets refused with something like "denied by auto
mode classifier," that's the signal — the fix is having the human run the
command directly, not retrying through another tool or encoding. Seen twice:
once for a sandbox-loosening `sessions.patch`, once for enabling
`tools.elevated.enabled`.

### Switching agent runtime breaks existing conversation history

A session's stored transcript is tied to the harness it was built under.
Forcing `agentRuntime.id: "openclaw"` on a model that was previously running
the Codex harness makes any session with pre-existing history fail outright
on its next turn — `ChatGPT Responses stream terminated`,
`failureKind: "provider-failure"`, exhausts all 3 retries, every time.
Confirmed on both `main` sessions and both Android sessions for Kerrigan and
Soma. `openclaw sessions compact <key>` does not fix this (returns "Already
compacted" if compaction already ran once). A **brand-new** session on the
new runtime works perfectly from the first turn.

The only fix found: reset/recreate the session rather than trying to carry
old history forward. For the fixed `main` key (can't be deleted):
`openclaw gateway call sessions.reset --params '{"key":"agent:<id>:main"}'`.
For any other key: `openclaw sessions delete <key> --agent <id> --yes`
(recreated fresh on next message). This loses raw conversation history —
not memory files, recipes, or workspace state, which live separately and
are unaffected. Confirm with the user before doing this to a conversation
they've actually been using; it's not reversible.

### Codex harness and OpenClaw's built-in runtime enforce host-exec privilege differently

A scoped sudoers grant (e.g. read-only Docker access) that worked fine for
an agent running the Codex harness can fail after switching that agent to
OpenClaw's built-in runtime, with an error like "elevated execution is
unavailable in this runtime." The built-in runtime's own `exec` tool routes
anything needing privilege escalation through OpenClaw's own
`tools.elevated` gate (`tools.elevated.enabled`, default `false`), which the
Codex harness's native exec path apparently didn't enforce the same way.
Don't assume a sudoers grant "just works" the same across a runtime switch —
re-test real privileged operations explicitly, not just file read/MCP/basic
exec, and expect to need `agents.entries.<id>.tools.elevated.enabled: true`
(plus whatever `allowFrom` scoping is appropriate) to restore it.

## Change log

```text
2026-09-29/30 — Soma build
Built Soma (Garmin MCP, 46-tool curated catalog), diagnosed the "0 MCP
tools" saga (root cause: Gateway needs an explicit restart after mcp.*
config changes — NOT tool-catalog size, that hypothesis was explicitly
retired after further testing), and the rootless-Podman sandbox backend
(subuid/subgid allocation + loginctl enable-linger, both real one-time
prerequisites on a useradd --system account).

2026-09-30 — Model/thinking config, Android pairing, Kerrigan sandbox trust
Set real per-model params.thinking (Luna=low/Sol=medium/Astra=high),
confirmed the thinkingDefault precedence trap (per-agent overrides
per-model; global doesn't). Fixed Android mobile pairing via
plugins.entries.device-pair.config.publicUrl (not OpenClaw's own managed
Tailscale mode, which would have collided with an existing Funnel route on
port 443). Unsandboxed Kerrigan's trusted Android session
(agent:main:node-27eb2826b877) via sessions.patch sandboxMode:"off"; added
scoped read-only reference binds (/opt/overmind, /mnt/disks/ssd1) for
Kerrigan's sandboxed research subagents only, confirmed Soma unaffected.

2026-10-01 — Soma Android MCP access
Confirmed the Codex-harness sandboxed-turn MCP limitation is unconditional
(reproduced with a sandboxed dashboard session too, ruling out an
Android-specific cause). Applied the same per-chat sandboxMode:"off"
opt-out to Soma's Android session (agent:soma:node-27eb2826b877); verified
real Garmin search_foods call succeeds there now, and that an unrelated
sandboxed Soma session still correctly lacks Garmin access.

2026-10-02 — Migrated Kerrigan and Soma off the Codex harness
Root-caused the session-key-based trust model's awkwardness to a real gap:
Codex's native spawn_agent delegation bypassed OpenClaw's sandbox/audit
system entirely (zero session trace, confirmed empirically), independent
of any sessions_spawn-level config. Fix: forced agentRuntime.id:"openclaw"
for sol/luna/astra; built two dedicated always-sandboxed worker identities
(kerrigan-worker, soma-worker) with requireAgentId+allowAgents forcing all
delegation to them; set both resident agents' sandbox.mode to "off",
replacing per-chat opt-outs entirely. Verified with disposable test agents
first, then both real agents: runtime confirmed, MCP/host access confirmed
from Home and a brand-new never-opted-in topic (the original complaint,
now resolved), worker isolation confirmed with real write/read probes.
Scoped Garmin properly (tools.deny on main/kerrigan-worker) after finding
it had never actually been agent-restricted. Found and accepted two real
regressions: existing conversation history doesn't survive the runtime
switch (reset via sessions.reset/sessions delete, approved by the user);
Kerrigan's Docker sudoers grant needs tools.elevated.enabled re-granted
(open, blocked by Claude Code's own permission classifier, needs the human
to apply it directly). Removed disposable test agents after migration.

2026-10-07 — Reverted kerrigan-worker/soma-worker, back to plain defaults
The 2026-10-02 worker-identity architecture worked but was more than the
resident agents actually needed — explicit decision to remove it and
accept that delegated-work isolation is unsolved for now (own future
project), prioritizing "different conversations with the same agent
differ in context, not capability" over worker isolation. Deleted
kerrigan-worker/soma-worker (config + leftover workspace directories —
`agents delete` doesn't always clean those up, rm -rf needed too);
removed subagents.requireAgentId/allowAgents from both agents. Kept the
two things that were genuinely Codex-migration fixes, not worker-identity
scaffolding: agentRuntime.id:"openclaw" and tools.elevated.enabled.
Separately root-caused "Worker turn session key does not match its
placement" properly this time (had previously only disabled the
triggering automation, which was explicitly called out as not an
acceptable fix): a stale persisted placement record from an earlier
interrupted run, unrelated to sandbox.mode. `sessions.reset` on the
affected cron session key clears it; verified by manually running both
affected automations end-to-end to completion. Restored
skills.workshop.autonomous.mode to "auto".
```
