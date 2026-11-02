# Agents and Model Routing

**Status:** PARTIAL — current real config and resolution order are verified;
this will keep changing as model lineups change.

## Agents and workspace files

Three resident agents on `overmind-01` today:

### Kerrigan (`main`)

**Role:** resident Overmind systems operator — host administration,
troubleshooting, infrastructure change.

Workspace: `/home/openclaw/.openclaw/workspace`
(`AGENTS.md`, `SOUL.md`, `USER.md`, `IDENTITY.md`, plus `memory/`).

Skills, in [`agents/main/skills/`](../../agents/main/skills/) and linked into
the workspace: `overmind-media-policy-audit`, `openclaw-browser-dictation`,
`openclaw-talk-tool-confirmations`. Its Skill Workshop wrote them; they moved
to the repo on 2026-11-02 (see [agents/README.md](../../agents/README.md)).

Primary architectural source of truth: `/opt/overmind` (the canonical
deployed repo checkout). Kerrigan is expected to inspect both canonical repo
state and live host state before durable infrastructure changes — not trust
either alone.

Since 2026-10-28 she can make those changes durable herself:

- **Containers:** she stops, starts and restarts any deployed container with
  `sudo /usr/local/sbin/overmind-svc`.
- **The repo:** she edits and commits in `/opt/overmind` under her own git
  identity, and `austin` pushes.
- **Service settings:** through the service's API where it has one; for
  Transmission that now persists.

See [Permissions and host administration](deployment-and-gateway.md#permissions-and-host-administration).

### Soma (`soma`)

**Role:** fitness, nutrition, and health-data coach.

Workspace: `/home/openclaw/.openclaw/agents/soma/workspace`
(`AGENTS.md`, `SOUL.md`, `USER.md`, `IDENTITY.md`, `BOOTSTRAP.md`,
`DREAMS.md`, plus `memory/`).

Primary external capability: Garmin MCP (`mcp.servers.garmin`, 57 curated
tools as of 2026-11-02 — health metrics, activities, training, nutrition
read/write, workout create/schedule; no blood pressure). See
[MCP Servers and Tool Access](sandboxing-and-trust.md#mcp-servers-and-tool-access)
for the real sandboxing interaction.

Skills, all in [`agents/soma/skills/`](../../agents/soma/skills/) and linked
into its workspace, in two layers (since 2026-11-02):

- **Coaching, one skill per area:** `training`, `nutrition`, `health`. These
  hold the domain judgment that used to be in its `AGENTS.md`, and are where
  new coaching lessons go. `health` is deliberately thin and grows with use.
- **Garmin, how to do it in Garmin:** `garmin-workouts` (the raw workout model,
  read-back validation, and what the Forerunner 265S accepts), plus four its
  Skill Workshop created: food logging, recipes, run/walk and strength
  workouts. Tool names in them are the MCP's snake_case names.

`AGENTS.md` keeps what applies to all of Soma's coaching (role, coaching
principles, general Garmin data rules, memory, safety) and lists the three
coaching skills. See [agents/README.md](../../agents/README.md).

### Buckminster (`buckminster`)

**Role:** general-purpose design agent (image editing, layout, and design
exploration). Added 2026-10-23 for the
[Agentic Design Studio](../../design-notes/agentic-design-studio-mac-worker-milestone-v0.1.md).

Workspace: `/home/openclaw/.openclaw/agents/buckminster/workspace`
(`AGENTS.md`, `SOUL.md` loosely after Buckminster Fuller, `IDENTITY.md`,
`USER.md`, `MEMORY.md`, and `skills/`).

**Skills, not runbooks (since 2026-11-02).** Its procedures and verified tool
knowledge are skills in [`agents/buckminster/skills/`](../../agents/buckminster/skills/),
symlinked into its workspace `skills/` by `agents/install-agent-skills
buckminster`, so they're always the version `/opt/overmind` has pulled:
`gimp`, `interior-scene-editing`, `gimp-worker`, `cerebrate-gimp`,
`sweethome3d`, `design-python`, and `reference-research` (with the Composio
notes as a reference file). Third-party skills (`interior-design-expert`,
`composio-cli`) are in `.agents/skills/`. Buckminster reads its skills but
doesn't edit them: lessons go to the user (or its Skill Workshop), and the
operator updates the repo. See [agents/README.md](../../agents/README.md).

**This is the first agent scoped to only its own tools.** It uses
`tools.profile: "minimal"` plus `alsoAllow: ["group:fs", "group:memory",
"view_image", "gimp_gimp_*", "file_fetch", "exec", "cerebrate__*",
"sweethome3d_*", "web_search", "web_fetch"]`. It has no messaging tools.

- **Shell (since 2026-10-23):** `exec` is `{host: "gateway", mode: "full"}`
  with no sudo (`elevated` unset), the same as Kerrigan and Soma. It is used
  for design notes, reading files, and local git. It briefly ran with an
  allowlist that only permitted `design-checkpoint`; that was dropped once a
  general-purpose design role needed git.
- **Python (since 2026-10-27):** it writes and runs its own Python through
  `exec`, with `/mnt/substrate/design-studio/python/.venv/bin/python`. That's
  a uv-managed CPython 3.12 with numpy, scipy, OpenCV, Pillow, scikit-image
  and shapely, maintained by the operator.
  - It computes on Overmind and applies the results in GIMP through named
    procedures; GIMP's code evaluators stay blocked.
  - Its scripts live in its workspace.
  - Skill: `design-python`.
  - Validated by an E08 rerun:
    `experiments/room-v1-capstone/runs/2026-10-27_E08_buckminster_python-validation/`.
- **Sweet Home 3D (since 2026-10-27):** `sweethome3d_*`, published by the
  `macbook-m1` node from the Sweet Home 3D MCP plug-in, edits the open
  project live. Allowed for Buckminster only, and every other agent denies it.
  - Skill: `sweethome3d`.
  - Setup and limits: `services/design-studio/README.md`, "Sweet Home 3D on
    the worker".
- **Composio (since 2026-11-01):** the `composio` CLI (0.6.0), installed for
  `openclaw` and logged in as the user's own Composio account, reaches
  Pinterest and Bright Data (and Gmail and Calendar). It's a CLI plus the
  `composio-cli` skill in Buckminster's workspace `skills/`, not an MCP
  server, so no tool rules are involved.
  - The skill loads for Buckminster only, but the login belongs to the
    `openclaw` user, so any agent's shell could use it. Buckminster's
    `AGENTS.md` sets the policy: read and search freely, ask before Pinterest
    writes, Gmail and Calendar only for an authorized task, approval for
    sends, money and deletions. Behavioral, not enforced.
  - Notes: `references/composio.md` in the `reference-research` skill.
  - Composio's own search toolkit stays switched off: web search goes
    through Brave instead (next item). Bright Data is paid, so it's used only
    with the user's approval.
- **Web research (since 2026-11-01):** `web_search` (Brave, the free plan
  configured globally) and `web_fetch`, for reference images and ideas from a
  wide range of sources, Pinterest among them. Pinterest Pin pages read as
  plain HTML, so no browser or Bright Data is needed. Overmind has no
  Chromium, so OpenClaw's browser tool doesn't run.
  - Skill: `reference-research`: sources, provenance, and a handful of
    lookups per brief rather than crawling (Pinterest's robots.txt
    disallows unlisted bots).
- **Interior design skill (since 2026-11-01):** `interior-design-expert` from
  `curiositech/some_claude_skills` (commit `88a60e3`), in Buckminster's
  workspace `skills/`, so no other agent sees it. Markdown only: color
  (Munsell, palettes), lighting, space planning and proportions, and style
  guides that include materials. Its `AGENTS.md` notes that the skill's
  Stability AI, Ideogram and SketchUp sections don't apply (Sweet Home 3D
  and GIMP instead) and that its `/references/…` paths are relative to the
  skill folder.
- **Design self-review (since 2026-11-01):** its `AGENTS.md` requires one
  review-and-revision pass before presenting: generate, inspect the rendered
  result, evaluate against the brief, fix the 2–3 biggest weaknesses in one
  revision, then present the rationale and remaining tradeoffs. No scoring or
  extra reviewer. The Evaluate step also checks every dimension label against
  the actual geometry, and lighting explicitly.
  - **First test (2026-11-01, a 3.4 × 4.0 m Japandi bedroom):** it read the
    skill and three references, drew a to-scale plan and a palette with
    Python, and made one sensible revision. Two misses led to those two
    checks:
    - a "0.60 m" chair clearance measured to empty space, not to the bed;
    - lighting wasn't considered, and the lighting reference wasn't read.
- **Limits enforced by the system:** the Gateway denies `system.run` on
  every node, so it has no shell on the Mac. (`/opt/overmind` was read-only
  for `openclaw` until 2026-10-28; it's now a shared work area, see
  [Permissions](deployment-and-gateway.md#permissions-and-host-administration).)
- **Limits that are policy only (its `AGENTS.md`):**
  - no changes to `/opt/overmind` or to services: that's Kerrigan's job;
  - checkpoints only through `design-checkpoint`, never by hand;
  - git is local only, with no push and no borrowed credentials;
  - stay out of other agents' workspaces and OpenClaw state.

  Like Kerrigan and Soma, it runs as the shared `openclaw` user, so these are
  not OS-enforced.
- **Mode settings:** Code Mode and Tool Search are at their defaults.
  `gimp_run_python` is off on the Mac side. Its
design tools run on a paired worker node, not on Overmind. GIMP comes from
the `macbook-m1` node, and Kerrigan and Soma deny `gimp_gimp_*`. It uses
`sandbox.mode: "off"` to match the other agents. See
[Sandboxing and Trust](sandboxing-and-trust.md#mcp-servers-and-tool-access)
and the
[environment report](../../design-notes/agentic-design-studio-environment.md).

### Workspace file responsibilities (all agents)

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

### Skills catalog (skills.sh)

Since 2026-11-01, [skills.sh](https://skills.sh/) is the catalog agents use
to discover skills, through the standard `skills` CLI. There's no custom
registry or wrapper.

- **`skill-discovery`** is an Overmind-owned skill in this repository,
  [`agents/skills/skill-discovery/SKILL.md`](../../agents/skills/skill-discovery/SKILL.md),
  loaded by every agent through `skills.load.extraDirs:
  ["/opt/overmind/agents/skills"]`. It's based on Vercel's `find-skills`
  (commit `92a9a34`), with Overmind's install rules built in. It replaced an
  installed, locally patched `find-skills` on 2026-11-01, so `npx skills
  update` has nothing of ours to overwrite.
  - Extra directories have OpenClaw's lowest precedence: a same-named skill
    anywhere else would override it. Don't reinstall Vercel's `find-skills`
    alongside it (different name, but duplicate purpose).
- **CLI:** `npx -y skills@1.7.4`, pinned to the reviewed version; bump it on
  purpose. A search takes about 6 seconds on the Pi.
- **Where skills go:**
  - shared: `npx -y skills@1.7.4 add <repo> --skill <name> --agent openclaw
    -g --copy -y` installs to `~/.openclaw/skills/`, recorded in
    `~/.agents/.skill-lock.json`;
  - one agent: the same command without `-g`, run from that agent's
    workspace, installs to `<workspace>/skills/`, recorded in
    `<workspace>/skills-lock.json`.

  `--copy` avoids symlinks into a `.agents/` folder.
- **One shared rule, in `skill-discovery`,** so no agent's own `AGENTS.md`
  repeats it:
  - discovery and inspection (search, list, reading a skill's files) are
    autonomous;
  - installing needs the user's approval, after reading `SKILL.md`, the
    references and any bundled scripts; unreviewed scripts are never run;
  - installs go only into the requesting agent's workspace, never global
    (`-g`, `--agent '*'`, `--all`); no overlapping skills.

  Behavioral, not enforced: agents have a shell. Agents in the `overmind`
  group can also edit `/opt/overmind`, so a change to the rule would show up
  in git.
- **Preferred catalog:** skills.sh. OpenClaw's bundled `clawhub` skill
  searches ClawHub, a different catalog, and is left enabled for every agent.

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
