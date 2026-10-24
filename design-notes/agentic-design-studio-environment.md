# Agentic Design Studio — Environment Report (DESIGN-001)

**Status:** Inventory complete, 2026-10-23. Everything below was observed
directly; nothing has been installed or changed yet. Proposed changes are
listed separately and none have been applied.
**Milestone:** [agentic-design-studio-mac-worker-milestone-v0.1.md](agentic-design-studio-mac-worker-milestone-v0.1.md)

## Decisions recorded

| Decision | Value |
| --- | --- |
| Worker machine | This Mac: Apple M1 MacBook Pro, user `dev` (normal account for the spikes; a restricted agent account may come later) |
| Design agent | New OpenClaw agent **Buckminster** (`buckminster`) with a narrow tool set, the first agent scoped to only its own tools |
| `DESIGN_STORE` | `/mnt/substrate/design-studio` (Substrate, SSD-backed) |
| Test source image | `hotel-room.jpg`: 1920×1080 sRGB JPEG, 261,483 bytes, sha256 `955562bb4541b0fc8d94f4c6ebdf3dbb84013dee12ad663494995c4ab4b320df`, no GPS/camera metadata, no people |
| Parent architecture note | Not written yet; not needed for this milestone |

## Overmind (`overmind-01`)

| Item | Observed |
| --- | --- |
| OpenClaw | `2026.9.6 (eb377ac)`, native, system user `openclaw` (uid 994, groups `openclaw`, `systemd-journal`) |
| Gateway | `bind: loopback`, port `18789`, `auth.mode: token` (SecretRef), `tailscale.mode: off` |
| Remote route | Externally managed `tailscale serve`: `https://overmind-01.<tailnet>.ts.net:18789` → `127.0.0.1:18789`, tailnet-only. Reached from the Mac: HTTP 200, valid TLS, 70 ms |
| `gateway.nodes` | Unset (runtime defaults: node plugin/MCP tools trusted, SSH-verified pairing on) |
| Existing nodes | One: Pixel 10 (Android), paired, disconnected, **reapproval pending** (unrelated to this work) |
| Agents | `main` (Kerrigan), `soma` (Soma). No design agent yet |
| Global tools | `tools.profile: "full"`, `web.search.provider: brave` |
| Per-agent tools | `main`: `deny ["garmin__*"]`, elevated on. `soma`: none |
| Node-hosted MCP support | Present: `mcp.tools.call.v1` is in the installed build, and the bundled docs match the milestone note |
| File Transfer plugin | `file-transfer` 2026.9.6, stock, **enabled** |
| GIMP for headless XCF validation | Not installed; `apt` candidate `gimp 3.2.2-1` (arm64) |
| `/mnt/substrate` | Bind of SSD `/substrate`, empty, `austin:austin 0775`; 1.4 TB free. `openclaw` **cannot write** there today |
| ACL tools | `setfacl` not installed |
| Backups | No independent backup destination exists yet (see [storage layout](storage-layout.md)). Committed checkpoints have no copy beyond the SSD |

## Mac worker

| Item | Observed |
| --- | --- |
| Hardware / OS | Apple M1, 8 GB RAM, macOS 26.6.2 (25G83) |
| Disk | 48 GiB free of 460 GiB (89% used) |
| GIMP | `/Applications/GIMP.app` **3.2.6**, native arm64. Never launched under `dev` (no `~/Library/Application Support/GIMP` profile yet) |
| uv / Python | `uv 0.12.15` at `/Users/dev/.local/bin/uv`, `uvx` alongside. Python 3.11, 3.12, 3.13 available (GIMP Agent MCP needs ≥3.11) |
| GIMP Agent MCP | PyPI latest is **0.5.0** (released 2026-09-08); pin it |
| Node.js | `v24.20.0` via **nvm** (`/Users/dev/.nvm/versions/node/v24.20.0/bin`); npm 11.19.0 |
| OpenClaw | **Not installed** (no CLI, no app, no `~/.openclaw`) |
| Transport tools | `/usr/bin/ssh`, `/usr/bin/rsync` (macOS `openrsync`, protocol 29), `/usr/bin/shasum`. SSH to Overmind works as `austin` |
| Power | Sleep disabled on AC; **sleeps after 1 min on battery**. Keep it on AC during spikes |

## Findings that change the plan

1. **Use the headless node host, not the macOS app.** OpenClaw's docs only
   describe node-hosted MCP for `openclaw node run`. The app embeds the same
   runtime, but nothing documents its MCP publishing. Neither is installed, so
   there is nothing to replace. Install the CLI at the Gateway's version
   (`openclaw@2026.9.6`).
2. **By default, a headless node can run any shell command on the Mac.** It
   advertises `system.run`/`system.which` and a browser proxy, and local exec
   approvals default to `full` with no prompt.
   - `--commands` can't be used to narrow this: it also disables MCP servers.
   - Lock the node down instead with:
     - `nodeHost.browserProxy.enabled: false` on the Mac;
     - a Gateway-wide `gateway.nodes.commands.deny` for `system.run`,
       `system.run.prepare`, `system.which`, `browser.proxy`,
       `browser.proxy.upload.v1`, `screen.snapshot`, `desktop.stream` and
       `computer.act`. No current node needs any of these; the Pixel declares
       none of them.
   - Only approve the node surface after checking `openclaw nodes pending`.
3. **Node-published tools are visible to every agent by default.** This is
   the same lesson as Garmin. MCP tools are named `<server>__<tool>`, so the
   GIMP tools should appear as `gimp__*`; confirm this for node-published
   tools in Spike C. Kerrigan and Soma need `deny: ["gimp__*"]`. Buckminster
   should get a restricted profile plus `gimp__*`, not `full`.
4. **Moving checkpoints: test the File Transfer plugin before adding an SSH
   account.** It is already enabled and pulls files over the paired node
   connection with SHA-256 checks and path allowlists, so it needs no new
   keys or account. Its agent tools are capped at **16 MB per file**. A
   layered 1080p XCF may exceed that, which Spike D will show. If it does,
   fall back to the rsync push in the milestone note.
5. **Overmind can validate XCFs itself.** Installing `gimp` (3.2.2,
   headless) on the Pi would let Overmind open each submitted XCF and check
   its layers before committing, independent of the Mac.
   - Cost: one package install, and peak RAM while it runs. Run validation
     serially, never alongside curate jobs.
   - The alternative is the note's "pending-validation until a fresh Mac
     checkout reopens it".

## Proposed changes (not applied)

**DESIGN-002, Mac only (no OpenClaw needed):**

```bash
open -a GIMP && sleep 20 && osascript -e 'quit app "GIMP"'   # create profile
/Users/dev/.local/bin/uvx --from 'gimp-agent-mcp==0.5.0' gimp-agent-mcp install-plugin
/Users/dev/.local/bin/uvx --from 'gimp-agent-mcp==0.5.0' gimp-agent-mcp doctor
# then: relaunch GIMP, Filters → Development → Start Agent Bridge, local MCP tests (Spike A)
```

Check the subcommand names against the 0.5.0 README before running.

**DESIGN-003, pairing (needs approval on Overmind):**

- **Storage (root, once):**

  ```bash
  sudo install -d -o austin -g openclaw -m 2775 /mnt/substrate/design-studio
  ```

  This gives `openclaw` group write on this one directory only, not
  Substrate-wide.
- **Agent:** `openclaw agents add buckminster` with its own workspace and a
  restricted tool profile. Add `deny: ["gimp__*"]` to `main` and `soma`.
- **Gateway:** `gateway.nodes.commands.deny` as in finding 2.
- **Mac:**
  1. Run `npm i -g openclaw@2026.9.6`.
  2. In `~/.openclaw/openclaw.json`, set `nodeHost.browserProxy.enabled: false`
     and `nodeHost.mcp.servers.gimp` with
     `command: "/Users/dev/.local/bin/uvx"` (absolute path, because of nvm and
     launchd PATH differences).
  3. Run it in the foreground first:

     ```bash
     openclaw node run --host overmind-01.<tailnet>.ts.net --port 18789 --tls --display-name macbook-m1 --pair <setup-link>
     ```

     The setup link comes from the Control UI Devices page.
  4. Approve the device and then its command surface on Overmind.

## Spike A results (DESIGN-002), 2026-10-23

**Gate A: passed.** GIMP Agent MCP 0.5.0 drove the live GIMP 3.2.6 window on
the Mac through a local stdio MCP client, with no OpenClaw involved.

- **Setup.** GIMP's first launch took about 2 minutes to create the profile
  `~/Library/Application Support/GIMP/3.2`.
- **Plugin.** `uvx --from 'gimp-agent-mcp==0.5.0' gimp-agent-mcp install-plugin`
  installed it to `.../3.2/plug-ins/gimp-agent-bridge`. `install-skills` was
  skipped because those skills target Claude Code/Cursor, not OpenClaw.
- **Bridge.** It is started manually from **Filters → Development → Start
  Agent Bridge** each time GIMP launches. `doctor` then reports
  `bridge_reachable: true` on `127.0.0.1:9877`. Ways to avoid the manual step:
  `gimp-agent-mcp shortcut` (a launcher with the bridge on) or the
  `gimp_launch(mode="gui")` tool. Neither is tested yet.
- **Tools.** 39 are exposed, matching the README. `gimp_status` reports
  `mode: gui`, `python_tool_enabled: true`.
- **Edit.** `gimp_open` on a working copy (never the source) gave image 1
  with a `Background` layer. `gimp_layer action=new` created
  "Rug placeholder" (760×190, `#2a6fdb`), then `action=set opacity=55`.
  `gimp_text` created a real `GimpTextLayer` named "Label". All three edits
  appeared in the open window.
- **Native save.** `gimp_export` with a `.xcf` path writes a native XCF
  (version 019): 4,905,129 bytes, sha256 `fedc422e…`. **No PDB call is
  needed; this resolves the open question in the milestone note.** The PNG
  preview is 2,043,423 bytes. The source JPEG hash is unchanged.
- **Reopen in the same GUI.** Names, order, opacity, positions and the text
  layer type all survived. Live IDs changed (layers 2/3/4 became 21/20/18,
  image 1 became 3), which confirms that IDs must never persist across
  sessions.
- **Reopen in a fresh process.** `gimp-console -i -n --quit` with a
  throwaway `GIMP3_DIRECTORY` and a `python-fu-eval` script loaded the XCF
  independently: 1920×1080, three layers (`Label` TextLayer, `Rug
  placeholder` at 55, `Background`). This is a usable, bridge-free validation
  step, and the same script could run on Overmind with `apt install gimp`.
- **The edits were visible live.** The operator confirmed the rectangle and
  label appeared in the open GIMP window as each call ran.
- **Finding: `gimp_close_image` doesn't close a displayed image in GUI
  mode.** It returned `{"closed": 1}`, but image 1 stayed listed, and the
  operator still saw its tab (`document.xcf-1.0` next to `-3.0`).
  - What does close it: deleting the image's display (the PDB procedure
    `gimp-display-delete`, or `Gimp.Display.get_by_id(n).delete()` via
    `gimp_run_python`). When the last display goes, the image goes with it.
    Verified: deleting display 1 removed image 1.
  - Displays don't expose which image they show, so map display to image by
    creation order or by checking the image list afterwards.
  - Spike E must close documents this way and then confirm with
    `gimp_list_images`.
  - Worth reporting upstream.
- **XCF size.** 4.9 MB for a 1080p image with two small overlays, well under
  File Transfer's 16 MB per-file cap. Larger overlays or more full-canvas
  layers will grow it.
- **Python tool.** `gimp_run_python` is enabled by default. Decide whether
  Buckminster gets it before Spike C; it runs arbitrary code as `dev`.

## Pairing results (DESIGN-003), 2026-10-23

**Gate B: passed. Gate C's remote status call: passed.** The remote edit
test is still to do.

**Gateway lockdown, applied before pairing.** `gateway.nodes.commands.deny`
is set to: `system.run`, `system.run.prepare`, `system.which`,
`system.execApprovals.set`, `browser.proxy`, `browser.proxy.upload.v1`,
`screen.snapshot`, `desktop.stream`, `computer.act`, `terminal.upload`,
`ollama.chat`, `ollama.models`. This was needed: an admin-minted join link
auto-approves everything the node declares, `system.run` included.

**Buckminster.**

- Created with
  `openclaw agents add buckminster --non-interactive --workspace ~/.openclaw/agents/buckminster/workspace`.
  Display name "Buckminster". `sandbox.mode: "off"`, to match Kerrigan and
  Soma; the default `non-main` would have sandboxed its other conversations.
- Tools: `profile: "minimal"`, `alsoAllow: ["group:fs", "group:memory",
  "view_image", "gimp_gimp_*"]`.
- Verified with real turns: it has the 38 GIMP tools and cannot run shell
  commands. Under Code Mode its `exec` only runs JavaScript; asked to run
  `id -un`, it reported no shell or process tool.
- The workspace still has OpenClaw's onboarding `BOOTSTRAP.md`, so identity
  and role files are not written yet.

**Tool naming.** Node-published MCP tools are named `<server>_<tool>` with a
**single** underscore, so the GIMP tools are `gimp_gimp_*`. They are not
`gimp__*` like Gateway-level MCP servers (`garmin__*`), and a `gimp__*` rule
silently matches nothing. Kerrigan (`main`) denies
`["garmin__*", "gimp_gimp_*"]` and Soma denies `["gimp_gimp_*"]`. Both were
verified with throwaway sessions (deleted afterwards): neither has any
`gimp_*` tool.

**`gimp_run_python` is off for now** (decided 2026-10-23). The Mac's node
config sets `env.GIMP_AGENT_ALLOW_PYTHON=0` and
`toolFilter.exclude: ["gimp_run_python"]`; 38 tools publish. It can be added
later if a spike needs it. Turning it off is not a sandbox:
`gimp_pdb_call` can still reach `python-fu-eval`.

**Mac node.**

- Installed with `npm i -g openclaw@2026.9.6` under nvm. Newer npm skips
  install scripts by default, so reinstall with
  `--allow-scripts=@google/genai,koffi,protobufjs,openclaw`.
- `~/.openclaw/openclaw.json` sets: `nodeHost.browserProxy.enabled: false`,
  `skills.enabled: false`, `autoUpdate.enabled: false` (the default is
  `true`, which would drift the node away from the Gateway's version), and
  `mcp.servers.gimp` (absolute `uvx`, pinned package, Python off).
- **Pairing.** On Overmind, `openclaw devices join-code --json` mints a
  single-use link. On the Mac,
  `openclaw connect --target-file <0600 file> --display-name macbook-m1`
  reads the link and deletes the file, so it never appears in arguments or
  logs.
- **Reconnecting** uses the saved device credential and needs no new link:
  `openclaw node run --host overmind-01.<tailnet>.ts.net --port 18789 --tls --display-name macbook-m1`.
- Declared commands (19): `desktop.stream`, `dir.fetch`, `dir.list`,
  `file.create`, `file.fetch`, `file.stat`, `file.write`, `fs.listDir`,
  `mcp.tools.call.v1`, `ollama.chat`, `ollama.models`,
  `system.execApprovals.get`, `system.execApprovals.set`, `system.run`,
  `system.run.prepare`, `system.which`, `terminal.upload`,
  `workspace.memory`, `workspace.skills`.
- Effective after Gateway policy: `fs.listDir`, `mcp.tools.call.v1`,
  `system.execApprovals.get`. The `file.*`/`dir.*` commands are not
  effective until the File Transfer plugin is given a node path policy
  (Spike D).
- Every connect logs `plugin tool publish failed: node pairing changed
  before request dispatch`, but all 38 tools are published anyway. This
  looks like a harmless race in the first attempt; keep an eye on it.

**Disconnect/reconnect.**

- With the node stopped, `nodes describe` showed `connected: false` and 0
  published tools, so Buckminster loses the GIMP tools.
- After reconnecting: `connected: true`, 38 tools, no pending approval.

**Persistence.** The spikes ran the node in the foreground. It has since been
installed as a launchd service with a pinned `--runtime-path`; see Wrap-up.

**Mac resources.** At pairing time, with GIMP open, the node reported about
160 MB of free RAM and a load around 4 on 8 GB. Watch this during heavier
edits.

## Spike C results, 2026-10-23

**Gate C: passed.** In one turn from Overmind, Buckminster changed the
`Label` text and moved `Rug placeholder` 120 px left, both inside one
`gimp_gimp_edit_batch` undo group. The operator saw both changes live, and
one Ctrl+Z reverted both. Buckminster looked up the image and layer IDs
fresh (image 3, layers 18/20) and didn't save.

**Finding: Buckminster couldn't see its own renders.** The images crossed
the node connection intact (`image/png`, 775 KB), but every
`gimp_gimp_render` result reached the model as `"omitted": true`.

- Cause: Code Mode's bridge between the JavaScript runner and tools is
  JSON-only, so image results can't cross it.
- Turning Code Mode off per agent doesn't help. OpenClaw then falls back to
  Tool Search, which nests calls the same way and also omits images.
- `tools.toolSearch` can only be set globally, not per agent. It was left
  alone to avoid changing Kerrigan's and Soma's tool surfaces.

**Fix: export, fetch, view.** `view_image` stays a direct tool even under
Code Mode. The loop is:

1. `gimp_gimp_export` a PNG into the project working directory on the Mac.
2. `file_fetch` it to Overmind.
3. `view_image` the returned local path.

Verified: Buckminster correctly read the label text, the rectangle's colour
and position, and the room objects, matching the exported file. That run
took 8 calls and about 67k tokens, against 28 calls and 378k for Spike C.

**What this required:**

- **Path policy.** `plugins.entries.file-transfer.config` is
  `{policyVersion: 2, nodes: {<macbook-m1 node id>: {ask: "off",
  allowReadPaths: ["/Users/dev/DesignStudio/workspaces/**"], maxBytes:
  16777216, followSymlinks: false}}}`. That is read-only, with no write
  paths.
- **Gateway opt-in.** `gateway.nodes.commands.allow: ["file.fetch"]`. All
  `file.*` and `dir.*` commands are marked dangerous and need this.
- **Node approval.** The node then requested an expanded command surface
  (its existing commands plus `file.fetch`), approved with
  `openclaw nodes approve`.
- **Agent tools.** `file_fetch` was added to Buckminster's `alsoAllow`.
- **Workspace docs.** Buckminster's `runbooks/gimp-worker.md` ("Seeing your
  work") and `AGENTS.md` now describe this as the only way to look at a
  document.

## Spike D results, 2026-10-23

**Gate D: passed.** Store, tools, and protocol:
[services/design-studio](../services/design-studio/README.md).

- **Store.** `/mnt/substrate/design-studio` (`austin:openclaw 2775`).
  Project: `design-studio-smoke-test`. Its source `hotel-room.jpg` is pinned
  as `sources/955562bb….jpg`.
- **Transport.** `file.fetch` through `openclaw nodes invoke`. The node
  reports a sha256 computed on the Mac, and Overmind recomputes it after the
  file lands. A 4.9 MB XCF crossed without trouble.
- **Checkpoint `0001-fedc42` committed** (parent none). Contents: the
  Spike A XCF (sha256 `fedc422e…`), its preview, and the Mac's
  fresh-process reopen result. The Overmind copy matches the manifest, and
  the operator could inspect it without the Mac.
  - Caveat: `0001` was verified before the reopen check started recording
    the XCF's hash. Its `worker-validation.json` has no `xcf_sha256`.
- **No GIMP on the Pi** (decided). Validation is a stdlib structural XCF
  parse plus a full PNG decode on Overmind, and a fresh-process GIMP reopen
  on the worker, tied to the file by hash.

**Failure tests.** All rejected, and HEAD stayed at `0001-fedc42`
throughout:

| Test | Result |
| --- | --- |
| Package missing `preview.png` | `file.fetch` `NOT_FOUND`; staging marked FAILED |
| XCF truncated at 1 MB, hashes honest | Rejected: "layer 'Background' tile past end of file" |
| One byte flipped after landing | Rejected: sha256 mismatch; commit refused (not verified) |
| Verified, then preview changed before commit | Commit re-verify rejected it and marked it FAILED |
| Two candidates built on the same HEAD (throwaway project) | First committed; second refused: "parent None != HEAD 0001-fedc42; restage" |

**What the tests changed in the tools:**

- The first truncation test **passed verification**. XCF keeps layer
  headers before pixel data, and the reused worker check wasn't tied to the
  file.
- Fix 1: the parser now walks every layer's hierarchy, level, and tile
  pointers.
- Fix 2: `worker-reopen-check` now records `xcf_sha256`, and verify requires
  it to match the manifest.

**Still manual.** The operator runs commits. Buckminster can export and
fetch, but cannot yet stage or commit, because it has no shell. Spike E
decides how the agent requests a publish.

## Spike E results, 2026-10-23

**Gate E: passed, with three caveats (below).** Buckminster ran every step
from Overmind.

**Agent-run checkpoints (exec allowlist).**

- `agents.entries.buckminster.tools.exec = {host: "gateway", mode:
  "allowlist"}`, plus `exec` in `alsoAllow`.
- A Gateway approvals entry for `buckminster` with one pattern:
  `/opt/overmind/services/design-studio/design-checkpoint`.
- Effective policy: Buckminster is `allowlist`/`ask off`. Kerrigan and Soma
  are unchanged (`full`).
- Verified: `design-checkpoint status` runs. `id`, a chained
  `design-checkpoint …; id`, and `ls` are all refused with `exec denied:
  allowlist miss`.
- Hardened the tool for agent use, because its arguments are now an attack
  surface: fixed store path, validated project and staging ids, and worker
  paths limited to `/Users/dev/DesignStudio/workspaces/`.
- Made `worker-validation.json` optional. The agent has no worker shell to
  run `gimp-console`, and Mac shell access stays off. When the file is
  present it is still bound to the XCF by hash.

**Steps:**

| Step | Result |
| --- | --- |
| Close the document | PDB route **failed**: the bridge can't convert an integer to `GimpDisplay`. Buckminster reported it honestly and updated its runbook. The operator quit GIMP (discarding changes) instead, which gave the milestone's "fresh GIMP process". |
| Worker offline, status | With the node stopped, Buckminster reported HEAD `0001-fedc42` from a live `design-checkpoint status`, said the GIMP tools were unavailable, and flagged the earlier unsaved state as unknowable. |
| Reconnect, resume | Buckminster started GIMP itself (`gimp_launch` gui). It opened the Mac copy only after `file_fetch` showed its sha256 matched 0001's manifest, inspected it with the export/fetch/view loop, recoloured the rug (`#b65d43`), and changed the label. It then staged, verified, and committed **`0002-3f2f0f`** (parent `0001-fedc42`) itself. Independently re-checked: 0001's files are byte-identical and both checkpoints are read-only. Cost: 49 calls, about 150 s, about 1.29M tokens (1.27M of them cache reads). |
| Mid-edit interruption | The node host was killed while GIMP ran a 120 px baked blur. Buckminster reported "the blur's outcome is unknown" and did not retry, save, or checkpoint. After reconnecting it inspected first, found the bridge unreachable, and did not relaunch or redo anything. |

**Caveats.**

1. **No restore to a worker that has lost its files.** The resume used the
   Mac's own copy, proven identical by hash. Pushing a committed checkpoint
   back to the Mac needs a transport. `file.write` (create-only, sha256)
   works, but `openclaw nodes invoke` passes params as one argv string,
   which Linux caps at 128 KB, so the CLI can't carry an XCF. Options:
   - the published `@openclaw/gateway-client` (requires a paired operator
     device; package 2026.8.1 vs Gateway 2026.9.6);
   - pairing Overmind itself as a node, so Buckminster can `file_fetch`
     from it and `file_write` (`sourceMediaId`) to the Mac;
   - a read-only SMB share mounted on the Mac.

   Undecided.
2. **The interruption test simulated a node-host crash, not a network
   drop.** Killing the node host also killed GIMP, because on macOS
   `gimp_launch` spawns GIMP as an attached child (`subprocess.Popen` with
   no `start_new_session`; Windows does detach). The unsaved scratch layer
   was lost; checkpoints and the working copy were not. Until this is fixed
   upstream, start GIMP independently of the node (the user, or the
   `gimp-agent-mcp shortcut` launcher). A true network-drop test still
   needs doing.
3. **Upstream bugs in GIMP Agent MCP 0.5.0, to report:**
   - `op_close_image` uses `image.delete()`, which fails while a window is
     open.
   - The PDB argument converter has no `GimpDisplay` case.
   - `gimp_launch` doesn't detach GIMP on POSIX.

## Wrap-up, 2026-10-23

- **Restore.** `design-checkpoint restore-command <project> [<id>]` prints
  the operator's `rsync` line and the expected sha256. Verified by restoring
  `0002-3f2f0f` to the Mac; the hash matched.
- **GIMP launcher.**
  [`make-gimp-launcher`](../services/design-studio/make-gimp-launcher)
  builds `~/Applications/GIMP Agent Bridge.app`, which runs
  `open -n -a GIMP --args … -b <start bridge>`. The bridge is reachable
  about 22 s after opening, with GIMP's parent PID 1. No menu click is
  needed.
- **Node service.** `openclaw node install … --runtime-path
  ~/.nvm/versions/node/v24.20.0/bin/node` installs the LaunchAgent
  `ai.openclaw.node` (`RunAtLoad`, `KeepAlive`, log
  `~/Library/Logs/openclaw/node.log`). It kept the same paired identity.
  After `kill -9`, launchd restarted it, it reconnected with 38 tools, and
  the launcher-started GIMP survived.
- **Network-drop test.** Tailscale went down on the Mac for 25 s during a
  baked 250 px blur. GIMP and the node process stayed alive, the blur
  finished, and the node reconnected by itself. Buckminster reported
  "appears to have taken effect" from a pixel check, said the tool's
  completion was unconfirmed, and did not retry.
- **Pattern.** Generalized in [remote workers](remote-workers.md).

## Risks

- The Mac's local exec defaults are broad until finding 2's denies are in
  place. Apply the denies before the first pairing, not after.
- With 8 GB RAM and 89% disk used, the Mac is fine for 1080p tests, but large
  multi-layer documents will be slow.
- nvm-installed OpenClaw won't be on `PATH` for a future launchd service.
  Stay in the foreground until the spikes pass, then decide whether to
  install it as a service.
- There is no backup of `DESIGN_STORE` until a backup destination exists.
