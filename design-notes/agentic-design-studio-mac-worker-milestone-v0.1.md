# Agentic Design Studio — Mac GIMP Worker Milestone

**Status:** Implementation plan / not yet executed  
**Version:** 0.1  
**Date:** 2026-10-23  
**Parent architecture:** `agentic-design-shopping-workbench.md`  
**Primary execution adapter:** [GIMP Agent MCP](https://github.com/SarutobiSasuke8/gimp-agent-mcp), initial pinned package **0.5.0** (verify installed/available version before setup)  
**Owners:** Overmind operator / Kerrigan (coordination); Design Agent (edits); Mac worker (GIMP runtime)  
**Execution style:** short, independently verifiable spikes; stop and record observations at each gate.

## 0. Mission and definition of done

Establish a reusable **remote graphical worker** pattern: an agent on the always-on **Overmind** OpenClaw gateway manipulates a **live GIMP 3 document on an M1 MacBook Pro**, publishes a **valid, layered XCF checkpoint** plus preview and provenance to persistent Overmind storage, survives a Mac disconnect, and **resumes from the published checkpoint** once a worker is available again.

**Acceptance demonstration (all required):**

1. From a conversation with the **Design Agent running on Overmind**, select the paired Mac node and invoke GIMP Agent MCP hosted on that node; no separate OpenClaw gateway is installed on the Mac.
2. An edit requested from Overmind visibly updates the **same open GIMP window** a human is observing on the Mac. Edits retain independent named layers and remain manually editable.
3. The agent saves a real `.xcf` project, an exported `.png` preview, and a checkpoint manifest. A versioned checkpoint is transferred to, verified on, and published by Overmind, not merely left on the Mac.
4. After closing the Mac GIMP document and disconnecting the Mac node, Overmind still knows the last verified checkpoint and reports the worker unavailable. No uncertain operation is silently retried.
5. After reconnecting, the worker checks out that committed checkpoint, opens the XCF in a **fresh GIMP session**, verifies its layers and preview, performs one further edit, and publishes a second, parent-linked checkpoint.
6. Demonstrate failure safety: a half-transferred, corrupt, or incomplete checkpoint cannot replace the most recent committed checkpoint.

**Not in this milestone:** Comfy Cloud, AI object removal, Pinterest ingestion, shopping agent, browser-hosted desktop, multi-worker scheduling, general-purpose worker framework, custom diffusion pipelines, unattended purchases. Do not expand scope to these until the acceptance demonstration passes.

## 1. Architecture and ownership

```text
Human (chat with Overmind / local Mac GUI)
                 |
   Overmind — OpenClaw Gateway
   Kerrigan -> Design Agent
   project registry + durable artifact store
                 |
        paired node connection
   (SSH tunnel or trusted Tailscale WS)
                 |
   M1 MacBook Pro — one node identity
   OpenClaw macOS companion/node host
      nodeHost.mcp.servers.gimp
                 |
   GIMP Agent MCP (local stdio process)
                 |
  authenticated 127.0.0.1 bridge
                 |
   GIMP 3, interactive window, XCF
   local project checkout + scratch
                 |
     rsync/SSH checkpoint staging
                 v
  Overmind verifies + atomically commits
```

**Responsibility contract:**

| Owner | Responsibility | Not authoritative for |
| --- | --- | --- |
| **Overmind** | Project manifest, original assets, committed checkpoints, previews, revision graph, worker availability, audit log | Live GIMP image/layer IDs |
| **Mac worker** | Open GIMP application, MCP bridge, working copy, temporary exports, local inspection | Published history or canonical project state |
| **Design Agent** | Interpret edit intent, operate MCP tools, inspect output, request checkpoint publish/recovery, report uncertainty | Unverified claims that a publish succeeded |
| **Human** | Design decisions, observing/intervening in the same GIMP GUI, approvals for sensitive actions | Machine integrity checks |

**Invariants:** originals immutable; published checkpoints immutable; one active writer for a project working revision; working state is not a committed checkpoint; worker-local image/layer IDs never persist as cross-session identifiers; published artifacts must not depend on absolute Mac paths to reopen. The artifact protocol must not depend on the chosen GIMP MCP implementation.

## 2. Environment prerequisites / no assumptions

### Overmind inventory (record actual results)

- Identify current OpenClaw version, gateway connection and authentication mode, user/service context, existing node list, current Design Agent identity/tools/policies, canonical storage volume and remaining space.
- Establish `DESIGN_STORE` on a persistent, backed-up Overmind volume, **not** a temporary container filesystem. Proposed default **only if it fits existing mounts**: `/srv/overmind/design-projects`.
- Ensure Mac can reach Overmind via existing SSH or trusted Tailscale route. Do not expose the OpenClaw Gateway or GIMP bridge publicly.
- Confirm the machine hosting Overmind can receive checkpoint transfers via a specifically authorized SSH/SFTP/rsync account or equivalent transport.

### Mac inventory (record actual results)

- M1 MacBook Pro, macOS version, logged-in user, disk space, native Apple Silicon GIMP 3.2.x build, `uv`/`uvx`, Python compatibility, OpenClaw macOS app (preferred) or headless node host (fallback, **not both**).
- If using the macOS app, it already includes a node-host runtime. Use **one node identity** for this machine. If its version cannot publish node-hosted MCP tools, record blocker, evaluate an update, or **replace**, rather than supplement, it with one headless node.
- GIMP and the MCP stdio server must run **on the same Mac**. A remote Overmind-side MCP process cannot attach to a localhost-only GIMP bridge on the Mac without a separate relay.
- Record absolute paths discovered using `command -v uvx`, `command -v ssh`, etc. GUI-launched macOS processes may have a different `PATH` from a terminal.

**Baseline report:** `environment.md` with exact versions, commands run, node ID/name, network mode, storage paths, known restrictions, and any pre-existing services affected. Never overwrite the existing Overmind gateway configuration blindly.

## 3. Small implementation spikes, in order

### Spike A — local GIMP + bridge on the Mac

**Goal:** Prove the editing adapter works *locally* before connecting Overmind.

1. Install the official GIMP 3.2.x Apple Silicon application if absent. Launch it once, then quit so its profile exists.
2. Install `uv` if needed. Install **the pinned v0.5.0 bridge** following upstream instructions. Illustrative terminal commands (verify syntax against the pinned release and replace if necessary):

   ```bash
   uvx --from 'gimp-agent-mcp==0.5.0' gimp-agent-mcp install-plugin
   uvx --from 'gimp-agent-mcp==0.5.0' gimp-agent-mcp doctor
   # Optional headless smoke test, separately from the live GUI:
   uvx --from 'gimp-agent-mcp==0.5.0' gimp-agent-mcp smoke
   ```

3. Fully restart GIMP after the plugin installation. In the GUI choose **Filters → Development → Start Agent Bridge**; verify its local authenticated bridge is running and `doctor`/status reflect the live instance.
4. In a *local* test MCP client, or a temporary minimal test harness, start the server via the documented stdio entrypoint. Verify `gimp_status`, `gimp_list_images`, `gimp_context` and an image/layer operation. Do not confuse a passing **headless** smoke test with live GUI compatibility.
5. Make a sample project with at least background + one editable overlay/text layer. Render and inspect a preview, save XCF, quit and reopen it. Test GIMP's XCF save through documented tool support; if needed use discovered GIMP PDB procedures—record the exact call rather than assuming a nonexistent `gimp_save` tool.

**Gate A:** Same live window, named layers, native XCF reopens correctly. Document test calls and any manual UI steps. If failed, resolve here; do not proceed to remote integration.

### Spike B — pair the Mac as an Overmind node

**Goal:** Prove native, authenticated, reusable remote execution without another gateway.

1. Configure the **OpenClaw macOS companion** in Remote-over-SSH or trusted direct Tailscale mode against Overmind. Favor the existing SSH path if simpler.
2. On Overmind, inspect node state. If pairing is requested, approve the **device request**, then the **separate node command-surface request** as applicable. Example CLI flow (IDs must come from actual output):

   ```bash
   openclaw devices list
   openclaw devices approve <device-request-id>   # only if pending
   openclaw nodes pending
   openclaw nodes approve <node-request-id>      # only if pending
   openclaw nodes status
   openclaw nodes describe --node <mac-node-id>
   ```

3. Confirm that one Mac node is connected and exposes the expected MCP tool-call command surface; avoid simultaneously running the companion node and a headless `openclaw node run` process.
4. Limit system command execution and broad node capabilities to what is necessary; separately check node approvals, Gateway policies, and per-agent tool policy.

**Gate B:** Overmind sees one stable, paired Mac node; a harmless approved operation succeeds, disconnect/reconnect is visible, and other agents have no unintended Mac access.

### Spike C — publish GIMP Agent MCP from the Mac node

**Goal:** Let an Overmind Design Agent invoke the Mac's local GIMP MCP server.

1. On the **Mac**, locate its active OpenClaw `openclaw.json` (`openclaw config file` where available; confirm against app/worker configuration). Add a node-hosted MCP definition rather than an Overmind Gateway-level definition.
2. Example configuration fragment only; **merge with existing config** and substitute an absolute executable path for `uvx` if required:

   ```json5
   {
     nodeHost: {
       mcp: {
         servers: {
           gimp: {
             command: "/ABSOLUTE/PATH/TO/uvx",
             args: ["--from", "gimp-agent-mcp==0.5.0", "gimp-agent-mcp", "serve"],
             // After discovery, optionally restrict advertised tools:
             // toolFilter: { include: ["gimp_*" ] }
           }
         }
       }
     }
   }
   ```

3. Restart the Mac's **active node host** so configuration is reloaded; inspect logs if the MCP process fails to start. Node-hosted MCP tools are published through OpenClaw's `mcp.tools.call.v1`; the Gateway does not need a matching server definition.
4. Ensure the effective node command surface has approved MCP tool calls and the Design Agent's tool policy grants only the intended GIMP capabilities. Do not grant blanket shell or Python execution merely to make the spike pass.
5. Ask the **Overmind Design Agent** to call `gimp_status`, enumerate images and inspect the explicit image context. Make one nontrivial, reversible layer edit. Confirm the change is visible in the **same Mac GIMP GUI**.
6. Record the tool names actually exposed in this OpenClaw version and any policies/approvals applied. Test a short disconnect/reconnect and tool rediscovery (but not mid-edit yet).

**Gate C:** An instruction issued to the Overmind agent changes the live local GIMP document via its node-hosted MCP. If the node tool is missing: inspect pairing, `mcp.tools.call.v1` approval, `nodeHost.mcp.servers` on **Mac**, node-host restart, process `PATH`, bridge status, and agent tool policy—in that order.

### Spike D — durable checkpoint publish from a local checkout

**Goal:** Commit one immutable, independently verifiable, editable checkpoint on Overmind.

1. Prepare a modest test photo plus a synthetic overlay; checkout only the needed assets to `DESIGN_WORKDIR` on the Mac (proposed default: `~/DesignStudio/workspaces/<project-id>`). Never edit the canonical source in place.
2. Open an identified project image in GIMP; **use explicit image IDs during this session only**. Put a visible, named editable overlay/text or furniture layer above the original; confirm the original layer remains unmodified.
3. Save the working document as a complete `.xcf` to the Mac's local staging directory. Export a `.png` preview separately. Record both paths and SHA-256 checksums. The manifest includes checkpoint metadata and asset hashes; see §4.
4. Transfer artifacts **to an unpublished staging directory on Overmind** over trusted SSH/rsync (or another explicitly authorized transport). The agent should not have to ssh into the Mac from Overmind: the Mac can push approved deliverables to Overmind.
5. **Verify on Overmind** that all required files exist and match the declared hashes and expected manifest/schema. Check the preview decodes. Reopen the XCF in a fresh GIMP process (either immediately via a fresh Mac checkout or via a documented non-GIMP validation step followed by an explicit round-trip test). Pixel inspection alone is not sufficient for an XCF.
6. Only after required checks pass, **atomically rename** the completed staging folder into an immutable `checkpoints/<id>/` path on the same filesystem and update project `HEAD`/manifest with an expected-parent check. Log the commit result. Staging directories must never be reported as published.
7. Confirm an operator can inspect the committed preview/XCF from Overmind storage; the Mac-local working copy may then be deleted without losing the published checkpoint.

**Gate D:** One checkpoint is committed with valid hashes, independently openable XCF, named layers, preview, provenance and a correct `HEAD`. Simulate a corrupted or interrupted transfer; confirm `HEAD` remains unchanged and the staging directory is visibly failed or recoverable.

### Spike E — disconnect and resume from committed state

**Goal:** Prove continuity does not depend on a surviving Mac process or filesystem session.

1. Close the project in GIMP. Disconnect the Mac node or turn off networking **after the checkpoint is committed**. Keep Overmind online.
2. Ask the Design Agent for project status. It must report: last committed checkpoint ID, available artifact locations, worker offline/unavailable, and whether any operation is still in an **unknown** state. It must not imply that the unsaved GIMP GUI is durable.
3. Reconnect the Mac node. Deliberately use a fresh GIMP process or newly opened document and a **new local checkout** fetched from committed Overmind storage.
4. Independently verify the checkout's hashes and that the XCF opens with the expected named layers, dimensions, and a visually consistent preview; **rediscover live GIMP image/layer IDs**.
5. Request one additional reversible edit and publish **checkpoint 0002** with `parent_checkpoint_id=0001`. Check that checkpoint 0001 remains unchanged and either one can be reopened.
6. Run a separate interruption experiment: break connectivity **while** a test edit is in flight. When reconnecting, read status, document/layer state and snapshots *before* deciding whether to retry. Do **not** silently replay a potentially completed edit. If an edit was never committed, resume from the last committed XCF or explicitly choose to salvage local working state as a new revision after inspection.

**Gate E (milestone completion):** Overmind can reliably recover and continue from committed artifacts, even after the Mac's live GIMP state is discarded. A second checkpoint is verifiable and linked to the first; no double-applied edit occurs after the interruption test.

## 4. Artifact contract (V1)

Proposed canonical Overmind layout; substitute the actual approved persistent volume:

```text
$DESIGN_STORE/
  projects/<project-id>/
    project.json                 # project metadata + committed HEAD pointer
    sources/                     # immutable source files
    assets/                      # imported assets, immutable by content hash
    checkpoints/
      0001-<short-id>/
        document.xcf              # editable master
        preview.png               # human/agent inspection
        checkpoint.json           # self-contained metadata + hashes
      0002-<short-id>/...
    staging/<commit-id>/          # incomplete/unpublished; never HEAD
    history/events.jsonl          # append-only project-level operations
```

**Suggested checkpoint manifest** (example values are illustrative, *not* generated state):

```json
{
  "schema_version": 1,
  "project_id": "design-studio-smoke-test",
  "checkpoint_id": "0001-abc123",
  "parent_checkpoint_id": null,
  "created_at": "2026-10-23T20:00:00Z",
  "agent_id": "design-agent",
  "worker_id": "macbook-m1",
  "toolchain": {
    "gimp_version": "RECORD_ACTUAL",
    "gimp_agent_mcp_version": "0.5.0",
    "openclaw_version": "RECORD_ACTUAL"
  },
  "files": {
    "document.xcf": {"sha256": "REPLACE", "bytes": 0},
    "preview.png": {"sha256": "REPLACE", "bytes": 0}
  },
  "layers_expected": ["Background", "Overlay"],
  "canvas": {"width": 1200, "height": 800},
  "description": "Original image plus editable overlay",
  "source_asset_ids": ["source-original-sha256"],
  "validation": {"xcf_reopened": true, "layers_checked": true}
}
```

**Publication and recovery semantics:**

- **Checkout:** copy the committed XCF and referenced assets, verify hashes, then open locally. Use local disk for active editing; never operate GIMP directly on an SSH network mount.
- **Checkpoint ID:** monotonically ordered label plus unique suffix. Filenames are immutable after commit.
- **Staging:** upload everything to a unique path under `staging/`; compare recorded bytes and SHA-256 on both sides; reject missing files and manifest/schema inconsistencies.
- **Validation:** render preview, ensure XCF is readable and retains expected editable layers; where fresh GIMP reopening is not available at publish time, checkpoint remains `pending-validation` and cannot become canonical `HEAD`.
- **Commit:** only one publication writer at a time; verify `parent_checkpoint_id` matches current HEAD; atomic directory rename and atomic metadata/HEAD replacement where supported. Crash during two-step publish must be reconciled on startup—never assume HEAD write happened.
- **Resume:** latest **verified committed** checkpoint is authoritative, not a screenshot, current GUI buffer, stale node file, or staging directory.
- **Unknown outcome:** a timed-out MCP edit or network interruption may already have modified the live image. On reconnect, inspect and compare before any retry; do not implement automatic at-least-once replay for non-idempotent edits.
- **Audit:** log tool version, worker, parent ID, asset provenance, edit summary, validation evidence, failures and approvals. Do not store passwords, bridge tokens or authentication headers in manifests/logs.
- **Retention:** never delete committed XCFs during V1; backup strategy for the persistent Overmind volume is separate and must be confirmed.

A tiny script or CLI adapter for `checkout`, `stage`, `validate`, `commit`, `status`, and `recover` is appropriate **only after** the manual end-to-end path works. Keep it narrow, testable, and independent from GIMP MCP. Prefer `rsync` + `shasum -a 256` (Mac) / `sha256sum` (Linux) initially.

## 5. Security, authority, and practical guardrails

1. **Trusted tool only.** GIMP Agent MCP has an authenticated loopback bridge, but PDB and Python operations can execute code with the local user's permissions. The token is not an OS sandbox. Start with a trusted Design Agent, ideally a separate test macOS account for experiments that need broad procedure access.
2. **Network boundary.** GIMP bridge stays on `127.0.0.1` on the Mac. No internet-accessible GIMP TCP port. Route MCP through paired OpenClaw node tools; route artifacts over authorized SSH/Tailscale.
3. **Least authority compatible with exploration.** The Design Agent receives GIMP tools; unrelated agents do not. Raw Python and generic PDB execution are powerful; review explicit agent policy and Mac user permissions. A `toolFilter` only limits exposed descriptors and is not a sandbox against all possible execution paths.
4. **No unrestricted home-folder access.** Use a dedicated design working directory, dedicated transfers, and separate SSH keys for artifact publication if feasible. Never give the publishing account access to overwrite already committed checkpoints.
5. **Manual changes can occur.** Before edits, capture document/image ID and relevant layers; operate serially; refresh context after any human intervention. If multiple GIMP bridges exist, deliberately target the intended instance; don't trust an arbitrary most-recent bridge.
6. **Human checkpoints.** Require operator approval before modifying existing important images, changing machine-level config beyond this plan, or deleting sources/workers. Avoid hardcoded credentials and broad system changes.

## 6. Handoff sequence / task tickets

| Ticket | Assignee | Output | Must pass before |
| --- | --- | --- | --- |
| `DESIGN-001` Inventory + version lock | Kerrigan / operator | `environment.md`, effective paths and node plan | A |
| `DESIGN-002` Mac local GIMP bridge | Mac worker | Local MCP test log, re-opened layered XCF | B |
| `DESIGN-003` Mac node pairing | Kerrigan / operator | Stable node ID, approved command list | C |
| `DESIGN-004` MCP publication + remote edit | Design Agent | Overmind-to-Mac tool trace, GUI result | D |
| `DESIGN-005` Checkpoint protocol | Storage/implementation worker | Layout, schema, staging verification, atomic commit tests | E |
| `DESIGN-006` Disconnect/resume acceptance | Design Agent + operator | Two committed checkpoints and evidence of safe recovery | Done |

**Each ticket must return:** (a) what changed; (b) commands/configuration touched; (c) exact verification performed with output/artifact paths; (d) blockers, failure modes, and rollback; (e) recommendation for next ticket. Avoid speculative refactors and framework work. If a step is blocked, document the smallest reproducible failure and stop at that gate.

**Suggested opening assignment to Kerrigan:**

> Implement `DESIGN-001` only. Read this plan and the parent `agentic-design-shopping-workbench.md`. Inventory existing Overmind/OpenClaw configuration and persistent storage; validate a Mac node connection path and identify local GIMP prerequisites. Propose exact changes but do not replace existing gateway config or install new agent runtimes. Return a short environment report, risks, and the precise next command sequence for `DESIGN-002`.

## 7. Decision log and open questions

**Agreed:** GIMP Agent MCP is the first adapter; Mac is the first interactive worker; Overmind is authoritative for committed project artifacts; OpenClaw node-hosted MCP is the preferred transport; we prove checkpoint/resume before layering on Comfy Cloud.

**To resolve during inventory, not by assumption:**

- Exact Overmind storage mount and backup target; authorized transfer account/path.
- OpenClaw Gateway and Mac app versions and whether current node-hosted MCP publishing works as documented.
- How the Mac companion's active OpenClaw config is located/reloaded under the installed release.
- Which exact GIMP Agent MCP procedure reliably saves the native XCF (validate on v0.5.0, including native reopen).
- Whether published XCF references any external dependencies; if so, package/relativize them or record them as required immutable assets.
- Selection of a small, non-sensitive test room photograph and overlay.

**After this milestone:** consider Comfy Cloud, better art-directed compositing, a dedicated always-on worker, and a generic worker/artifact service only if the existing pattern needs them. Preserve model/runtime interchangeability.

## 8. Primary references (verified 2026-10-23)

- [Parent architecture: Agentic Design & Shopping Workbench](agentic-design-shopping-workbench.md) (internal design note; not a software dependency)
- [GIMP Agent MCP — GitHub](https://github.com/SarutobiSasuke8/gimp-agent-mcp)
- [GIMP Agent MCP — PyPI v0.5.0](https://pypi.org/project/gimp-agent-mcp/0.5.0/)
- [GIMP Agent MCP security notes](https://github.com/SarutobiSasuke8/gimp-agent-mcp/blob/main/SECURITY.md)
- [OpenClaw: Node-hosted MCP servers and skills](https://docs.openclaw.ai/nodes/mcp-and-skills)
- [OpenClaw: macOS remote control](https://docs.openclaw.ai/platforms/mac/remote)
- [OpenClaw: Nodes CLI and pairing](https://docs.openclaw.ai/cli/nodes)
- [OpenClaw: Node troubleshooting](https://docs.openclaw.ai/nodes/troubleshooting)

**Important:** Published documentation is not proof of deployment success. The worker must confirm actual installed release versions, permissions, Mac GUI behavior, output XCF integrity, and recovery outcomes. The milestone remains **not yet implemented** until all gates pass.
