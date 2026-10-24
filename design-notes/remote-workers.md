# Remote workers

**Status:** PARTIAL. The pattern was verified end to end on 2026-10-23 with
one worker (`macbook-m1`, GIMP for Buckminster). Evidence is in the
[Design Studio environment report](agentic-design-studio-environment.md).
Restoring files *to* a worker is still an operator step (see "Moving files").

A **remote worker** is another machine that does work for an Overmind agent:
a GUI application, a GPU, an OS-specific tool. The agent and the
authoritative state stay on Overmind. The worker holds only working copies
and can disappear at any time.

```text
Overmind (authoritative)                    Worker machine (disposable state)
  OpenClaw Gateway ── paired node link ──►   OpenClaw headless node host (launchd/systemd)
    agent (scoped tools)                       node-hosted MCP server(s) ─► local app (GIMP…)
    store on SSD (/mnt/substrate/…)  ◄── file.fetch (read-only, one dir) ── outbox/
    verifier/committer (exec-allowlisted)      working copies, scratch
```

## 1. One identity per machine: the headless node host

- Install the OpenClaw CLI on the worker at **the Gateway's exact version**,
  and set `nodeHost.autoUpdate.enabled: false`. The default (`true`) drifts
  the worker away from the Gateway.
- Use `openclaw node run` / `node install`, not a desktop companion app.
  Node-hosted MCP is only documented for the headless host, and running both
  creates two identities.
- Worker config (`~/.openclaw/openclaw.json`): `nodeHost.browserProxy.enabled:
  false`, `nodeHost.skills.enabled: false`, and only the MCP servers it
  actually needs, with absolute `command` paths.
- Run it as a **service** once it works in the foreground:
  `openclaw node install --host <gateway> --port 18789 --tls --display-name
  <name> --runtime-path <absolute node>`. Pin `--runtime-path` when Node comes
  from a version manager (nvm), because services don't get your shell's
  `PATH`.
  - Verified on macOS: LaunchAgent `ai.openclaw.node`, `RunAtLoad` +
    `KeepAlive`. After `kill -9`, launchd restarted it within seconds, and
    it reconnected under the same paired identity with no new approval.

## 2. Pair only after the Gateway is locked down

- **First** set `gateway.nodes.commands.deny` for everything no node needs:
  `system.run`, `system.run.prepare`, `system.which`,
  `system.execApprovals.set`, `browser.proxy`, `browser.proxy.upload.v1`,
  `screen.snapshot`, `desktop.stream`, `computer.act`, `terminal.upload`,
  `ollama.*`. This is required: an admin-minted join link auto-approves
  **everything** the node declares, `system.run` included. The deny list is
  Gateway-wide, so it covers every node.
- Mint a single-use link on Overmind (`openclaw devices join-code --json`).
  On the worker, run
  `openclaw connect --target-file <0600 file> --display-name <name>`; it
  reads the link and deletes the file, so the link never lands in argv or
  logs.
- Any later widening (for example `file.fetch`) shows up as a request in
  `openclaw nodes pending`. Read what it asks for before running
  `openclaw nodes approve`.
- Check the result with `openclaw nodes describe --node <name> --json`.
  `commands` is the effective set after policy, not what the node declared.

## 3. Publishing tools to exactly one agent

- MCP servers configured under the worker's `nodeHost.mcp.servers` publish
  their tools to the Gateway while the node is connected, and withdraw them
  when it disconnects. That gives free availability signalling: no worker,
  no tools.
- **Naming:** node-published tools are `<server>_<tool>` (one underscore),
  for example `gimp_gimp_status`. Gateway-level MCP uses `<server>__<tool>`.
  A rule written in the wrong form silently matches nothing.
- Node tools are visible to **every** agent by default. Give the worker its
  own agent with `tools.profile: "minimal"` plus an explicit `alsoAllow`,
  and add a `deny` for the new tool prefix on every other agent. Verify with
  a real turn in a throwaway session. Hiding tool names is hygiene, not a
  security boundary, for agents that have shells.
- Filter dangerous MCP tools at the worker too (`toolFilter.exclude`, plus
  any env switch the server offers).

## 4. Moving files

- **Worker → Overmind:** the File Transfer plugin's `file.fetch`. It needs
  all of:
  - `gateway.nodes.commands.allow: ["file.fetch"]` (every `file.*`/`dir.*`
    command is marked dangerous);
  - a per-node path policy in `plugins.entries.file-transfer.config.nodes`
    (`allowReadPaths` limited to one work tree, `ask: "off"`, `maxBytes`,
    `followSymlinks: false`);
  - a node approval.

  It returns a sha256 computed **on the worker**, which Overmind re-checks
  after the file lands. Limit: 16 MB per file.
- **Overmind → worker:** not automated yet. `file.write` is fine in itself
  (create-only by default, sha256-checked), but `openclaw nodes invoke`
  passes params as one argv string, which Linux caps at 128 KB. For now the
  operator restores with `rsync` from the worker, which already has SSH to
  Overmind. If agents need it: a read-only share in the existing Samba
  container, then pairing Overmind as a node, then a Gateway-client helper.

## 5. Authority stays on Overmind

- The worker produces candidates in an outbox. A deterministic tool on
  Overmind stages them, verifies them (worker vs local hashes, format-level
  checks), and commits atomically under an expected-parent check. Committed
  state is immutable. See
  [services/design-studio](../services/design-studio/README.md).
- The agent may run that tool through an **exec allowlist** naming exactly
  one program: `agents.entries.<id>.tools.exec = {host: "gateway", mode:
  "allowlist"}` plus a Gateway approvals allowlist entry. Since the agent
  now picks the tool's arguments, the tool must validate every input that
  decides a path.
- Verified: `id`, `ls`, and `<tool>; id` are all refused with
  `exec denied: allowlist miss`.

## 6. Failure model

| Event | Verified behaviour |
| --- | --- |
| Worker offline | Its tools vanish. The agent reports HEAD from Overmind and says the worker is unavailable. |
| Network drop mid-call (Tailscale down 25 s) | The node and the app keep running and the operation completes on the worker. The node reconnects by itself. The agent sees a failed call, inspects after reconnecting, reports "appears applied, completion unconfirmed", and does not retry. |
| Node-host crash | launchd restarts it. **An app the MCP server launched dies with it**, because GIMP Agent MCP's `gimp_launch` doesn't detach on macOS. |

Rules that follow from this:

- **Never auto-replay** an operation whose outcome is unknown. Reconnect,
  inspect, then decide.
- **Start GUI apps independently of the node**, through LaunchServices
  (`open -n -a …`), a login item, or the user. For GIMP, use
  [`make-gimp-launcher`](../services/design-studio/make-gimp-launcher),
  which builds "GIMP Agent Bridge.app" (bridge on at start, parent PID 1).
- Treat anything not committed on Overmind as possibly lost.

## 7. Agent-side gotchas

- **Code Mode and Tool Search drop images from tool results.** Their guest
  bridge is JSON-only. If the agent must *see* a worker's output, export it
  to a file, `file_fetch` it, then use `view_image`, which stays a direct
  tool. `tools.toolSearch` can only be set globally.
- Keep worker facts in the agent's `runbooks/<worker>.md`, and have the
  agent update it when it learns something.

## Adding a new worker: checklist

1. The Gateway deny list is in place; record the Gateway version.
2. Install the CLI at that version, auto-update off, minimal `nodeHost`
   config, absolute MCP commands.
3. Pair in the foreground (join-code plus `--target-file`); check
   `nodes describe`.
4. Scope the tools: a dedicated agent, `alsoAllow`, and denies on the others,
   verified by turns.
5. File access: a read-only path policy for one directory, the Gateway
   allow, a node approval.
6. Commit path: an outbox and a verifier on Overmind; exec allowlist only if
   the agent should commit.
7. Install the service (`--runtime-path`); kill test; network-drop test.
8. Start GUI apps independently of the node.
9. Document the worker in its agent's runbook and in `hosts/`.
