# Kerrigan V1 — Follow-ups Before "Ready"

## Status

PROPOSED — see [status legend](README.md#status-legend). Tracking note, not a
new design; supersedes nothing in
[overmind-kerrigan-openclaw-mvp.md](overmind-kerrigan-openclaw-mvp.md), which
remains the governing V1 design. Steps 1 and 2 of that doc's implementation
sequence are done (native Gateway running as a system service, read-only
Docker/journal/filesystem visibility, `sandbox.mode: non-main` configured).
This note is the punch list for what's left before calling V1 genuinely ready
for real work.

## Done so far (this session)

- OpenClaw installed natively under a dedicated `openclaw` system account,
  not `austin`'s own login — real, deliberate credential/privilege
  separation, not borrowed personal auth.
- Fixed a real `EACCES` on Gateway startup (Ubuntu's AppArmor
  unprivileged-userns restriction) with a scoped profile grant, not the
  global sysctl fallback.
- Durable systemd system unit (`openclaw-gateway.service`), following
  OpenClaw's own documented restart/timeout semantics, with
  `OPENCLAW_SERVICE_REPAIR_POLICY=external` and a correct `PATH`.
- Read-only Docker (`ps`/`inspect`/`logs`/`compose ps`) via a narrow sudoers
  allowlist — deliberately not `docker` group membership, which is
  root-equivalent.
- `systemd-journal` group membership for log reading (cannot vacuum/rotate).
- `agents.defaults.sandbox.mode: non-main` — Kerrigan's main session
  unsandboxed, any spawned subagent sandboxed by default.
- Dashboard reachable privately over Tailscale Serve (not Funnel — this is a
  live agent control surface, not something to expose publicly like
  Jellyfin/Seerr), with `gateway.trustedProxies` fixed so it actually works
  behind that proxy.
- Model routing: `agents.defaults.model = openai/gpt-6-sol` (Kerrigan's own
  reasoning), `agents.defaults.subagents.model` and
  `agents.defaults.utilityModel = openai/gpt-6-luna` (delegated work,
  titles/recaps). Astra installed and selectable, not default — reserved for
  genuinely consequential/ambiguous work per the escalation criteria worked
  out this session.
- Gateway auth token migrated off plaintext config into the SecretRef store
  (`secrets audit` clean except for the OAuth credential residue, which is
  explicitly out of scope for that migration).
- Renamed the default `main` agent's *identity* to "Kerrigan" with a custom
  avatar (`agents.defaults` still uses the technical id `main` internally —
  that's expected, not a bug; `identityName` is the persona-facing name).

## Follow-ups for next session

1. **Refine model selection further.** We set a reasonable first-pass
   Sol/Luna/Astra split; revisit once there's actual usage to look at
   (reasoning-effort defaults per model, whether the escalation criteria for
   Astra actually holds up in practice).
2. **Pass over OpenClaw's standard agent settings in the dashboard UI** —
   Files (`SOUL.md`/`USER.md`), Tools, Skills, Channels, Automations, Memory
   (sleep-phase "dreaming" — light/REM/deep). Background research on all of
   these is running now (see below); use it to inform a deliberate
   configuration pass, not just default settings left as-is.
3. **Give Kerrigan a non-default emoji** (currently the stock lobster).
4. **Review and update the Substrate working plan** so Kerrigan's granted
   filesystem/project access actually matches her real role, not just
   whatever was convenient to wire up first.
5. **Give Kerrigan real familiarity with the rest of Overmind**, not just the
   server host — specifically the Fire TV Stick (emulation/RetroArch side of
   the project) and the Pi Zero running the Cerebrate node. Decide what
   "access" means concretely for each (read-only docs/context vs. actual
   reach into those hosts).
6. **Git/GitHub access for the Overmind repo**, so Kerrigan can actually push
   changes she makes. This needs a real credential decision — per AGENTS.md
   rule 11, she needs her own scoped, revocable git credential, not
   `austin`'s personal one forwarded through. Worth deciding the actual
   mechanism (deploy key scoped to this repo? a machine user? GitHub App
   installation token?) rather than defaulting to whatever's fastest.
7. Once the above lands: real job assignments (out of scope for this note).

## OpenClaw feature research (findings)

Verified against docs.openclaw.ai and openclaw/openclaw GitHub issues, not
just search summaries. Full per-area detail below; four things worth acting
on before/during the settings pass are called out first.

### Act on these

1. **`commands.ownerAllowFrom: ["*"]` is a known, open bug (openclaw/openclaw
   #30226, #25286)** — the wildcard grants command access but does not set
   the internal `senderIsOwner` flag, so owner-only tools (`gateway`, `cron`,
   `whatsapp_login`) stay silently stripped even though the wildcard appears
   to work. Use explicit `channel:id` entries instead, not `"*"`, once a
   channel is configured for Kerrigan.
2. **Dreaming (memory-core's daily consolidation job) is a real background
   LLM-call job already running by default, not free, and has an open
   Pi-specific risk.** Computationally it's light→REM→deep phases (dedup →
   theme-summarization → scored promotion into `MEMORY.md`), cron default
   `0 3 * * *`, capped at 3 concurrent background completions system-wide.
   GitHub #97692: on resource-constrained hardware, an interrupted run has
   **no crash recovery** — invisible to monitoring, partial writes can
   accumulate silently. Separately, #157791 (filed against our exact build,
   2026.9.6) reports Pi-class Gateway startup ~138s and RSS crossing 1.5GiB
   shortly after boot — worth checking Kerrigan's actual footprint against
   that. Decide deliberately: keep default cadence, retune
   (`plugins.entries.memory-core.config.dreaming.frequency`/`.model`/
   `.maxPromotedSnippetTokens`), or disable
   (`...dreaming.enabled false`) and run `openclaw memory promote --apply`
   manually instead. Inspect via `openclaw memory status --deep`.
3. **SOUL.md is worth a deliberate authoring pass, not left default** — it's
   read every session start and docs call it "the single most impactful file
   you can write." Given Kerrigan's operator role, the Boundaries section
   specifically (e.g. explicit rules against leaking secrets/tokens into
   channel messages) is worth writing on purpose.
4. Automations (`openclaw automations`/`openclaw tasks`) and dreaming's cron
   are **separate, unlisted-together** scheduling surfaces — dreaming is
   plugin-owned, not visible via `openclaw automations list`. If Kerrigan
   ever gets her own scheduled automations, check both surfaces plus
   Heartbeat (system-owned, 30min default) when reasoning about what's
   hitting the Pi on a schedule, matching the existing "don't run heavy jobs
   concurrently" discipline.

### Files

`SOUL.md` (identity/personality, read every session, ~"most impactful file"),
`USER.md` (the human's profile — stable preferences/context, hard ~4,000-char
budget, keep curated not a running log), `MEMORY.md` (curated long-term
facts), `memory/YYYY-MM-DD.md` (disposable daily working notes),
`DREAMS.md` (human-readable diary of what dreaming did — not itself
re-promoted). All literal files under the agent's workspace
(`~/.openclaw/workspace`), not config-schema keys.

### Memory

Three tools: `memory_search` (keyword + optional embedding-hybrid),
`memory_get`, `intent` (event-conditioned reminders). Embedding provider for
semantic search is configurable (`memory.search.provider`) — keyword search
works with none configured, worth checking this isn't defaulting to a live
API call if not needed. `agents.defaults.compaction.memoryFlush.enabled`
toggles auto-flush before compaction.

### Skills

Markdown + YAML frontmatter, follows the same AgentSkills spec as Claude
Code's own skills (not a reinvented format) — `SKILL.md` with `name`/
`description`, optional `user-invocable`, `disable-model-invocation`,
`metadata.openclaw` gating block. Discovery order: workspace `skills/` →
`.agents/skills` → `~/.agents/skills` → state-dir skills → bundled → plugin
skills. `openclaw skills install @owner/slug` (ClawHub), `git:owner/repo@ref`,
or local paths; `openclaw skills verify @owner/slug` checks the trust
envelope before enabling — treat third-party skill installs with the same
scrutiny as running an unfamiliar script, verify before enabling on Kerrigan.

### Channels

Protocol adapters connecting messaging platforms to the Gateway; feature
parity isn't guaranteed across channels (text everywhere, media/reactions
vary). Bundled: A2A, Reef, Telegram ("recommended starting point" per docs),
WebChat. Installable: Discord, Slack, Teams, WhatsApp, Signal, Matrix, IRC,
and others via `openclaw plugins install @openclaw/<id>`. See the
`ownerAllowFrom` bug above before wiring one up for real operator access.

### Automations

General scheduler: one-shot (`--at`), recurring interval, cron, or inbound
webhook triggers. `openclaw automations` to manage, `openclaw tasks list|audit`
for detached/subagent runs specifically. Distinct from Heartbeat
(system-owned monitor, 30min default) and from dreaming's plugin-owned cron
(see above) — three separate scheduling surfaces, not one unified list.

### Tools

Already using sandbox/exec; full catalog spans runtime (`exec`/`process`/
`terminal`/`code_execution`), files, web, browser, communication, agent
coordination (`sessions_*`, `subagents`, goals), automation (`cron`,
`heartbeat_respond`), infra (`gateway`, `nodes`), plugin management, and
media generation. Enforcement order: global `tools.allow`/`deny` → per-agent
override → active profile → model-provider limits → sandbox rules → channel
permissions → plugin availability. Given Kerrigan's operator role, `secrets`,
`gateway`, `cron`, and `exec`/`process` are the ones worth auditing against
`tools.deny` deliberately — most everything else (media gen, browser,
x_search) is low-risk to leave default.
