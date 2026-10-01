# Overmind Health & Fitness System — V1 Design

## Status

PARTIAL — Phase 1 (Garmin read access) is live and verified. See
[Phase 1 Implementation Log](#phase-1-implementation-log) below for what's
actually running, what broke, and what we learned. The rest of this doc
(Phases 2-6) remains an initial design/exploration note.

This project should remain **composition-first**: use existing Garmin, nutrition, MCP, database, and dashboard tools wherever possible, and add custom code only where an actual gap appears.

The initial goal is not to build a complete health platform. It is to establish a small working loop that can:

1. read useful Garmin health and fitness data;
2. create and schedule workouts through Garmin;
3. record nutrition conversationally with minimal friction;
4. combine intake, expenditure, and weight trends in one useful view;
5. expose the system to a persistent fitness/nutrition agent on Overmind.

---

## Phase 1 Implementation Log

Real state as of 2026-09-30, not a plan — what's actually deployed, verified,
and the debugging trail worth not repeating.

### What's running

- **Garmin MCP** (`services/garmin-mcp/`) — Taxuspt/garmin_mcp, built from a
  pinned upstream commit, running on `overmind-01`, authenticated (real
  interactive login completed, OAuth tokens persisted at
  `/var/lib/overmind/garmin-mcp/garminconnect`, survived a container
  recreation already), bound to `127.0.0.1:8001`.
- **Soma** — the health/fitness coach agent, a second OpenClaw agent
  (`agentId: soma`) alongside Kerrigan (`main`) on the same native Gateway.
  Model `openai/gpt-6-sol`, identity name "Soma".
- **Garmin MCP tool catalog curated to 46 tools** (of 153 available) via
  `openclaw mcp tools garmin --include ...`: body/health metrics, activity
  and performance trends, workout read/create/schedule, and Garmin's own
  built-in nutrition tools (distinct from the separate nutrition-mcp planned
  for Phase 3 — enabled because we were already editing this server's tool
  list, not a Phase 3 substitute). Full list and rationale in git history of
  this file / session transcript; re-derive from
  `openclaw mcp probe garmin` if this drifts.
- **Verified end-to-end**: a real chat with Soma correctly retrieved actual
  step-count and activity data (September 2026 activity history), confirming
  the full chain — Gateway → MCP → Garmin Connect → back to the model —
  genuinely works.
- **Soma runs sandboxed for non-main sessions** (rootless Podman backend,
  `scope: session`, `workspaceAccess: ro`) — see
  [kerrigan-v1-followups.md](kerrigan-v1-followups.md) for the general
  OpenClaw/sandbox setup details, which aren't specific to this project.
  Verified: a real non-main session successfully created a Podman sandbox
  and *still* retrieved real Garmin data through it (MCP calls are
  Gateway-side, not sandboxed, by design — confirmed empirically, not just
  from docs).

### The "0 MCP tools" debugging trail — what it actually was, and wasn't

Real sequence, since it's easy to draw the wrong conclusion from the
intermediate steps:

1. Registered `garmin` as an MCP server (`openclaw mcp add`, streamable-http,
   all 153 tools). `mcp doctor`/`mcp probe` both confirmed a healthy
   connection with all 153 tools reachable.
2. Every real agent turn — through the CLI test harness *and* the actual
   dashboard — reported **zero** `garmin__*` tools, for both agents,
   regardless of `tools.allow`/`deny`/`alsoAllow` configuration.
3. Found a real, closed-but-unconfirmed-fixed upstream issue
   (`openclaw/openclaw#114154`) describing the identical symptom against an
   earlier version (2026.7.1-2): healthy probe/doctor, zero tools in real
   sessions, no workaround found by the original reporter after ruling out
   the same things we did.
4. **The actual, most likely root cause, found afterward**: `openclaw mcp
   reload` and plain `config set`/`mcp tools` CLI invocations only affect
   *that one-off CLI process's own transient runtime* — they do **not**
   reach the actual persistent Gateway (`openclaw-gateway.service`). Every
   config change made via ad-hoc CLI calls was invisible to the live
   service until we did a real `sudo systemctl restart
   openclaw-gateway.service`. This is documented behavior
   (`docs/tools/mcp.md`: *"A Gateway or agent running elsewhere needs its
   own reload, config publish, or restart"*), not a bug — we just didn't
   internalize it until this cost real debugging time.
5. We narrowed the tool catalog to 3 tools *and* did a real restart in the
   same pass, which worked — but that conflated two variables. **We never
   went back and re-tested the original 153-tool catalog with a proper
   restart.** So: the leading hypothesis is that the Gateway-restart gotcha
   alone fully explains what happened, and catalog size was never actually
   the problem — but this is not proven. Treat "large catalogs might fail"
   as retired-but-not-disproven, not confirmed-safe. If a future large
   catalog addition mysteriously shows zero tools again, restart the
   Gateway properly *before* concluding it's a size problem.

### Concrete operational rule going forward

**Any config change made via `openclaw config set`, `openclaw mcp add`,
`openclaw mcp tools`, `openclaw mcp configure`, etc. needs `sudo systemctl
restart openclaw-gateway.service` before trusting it's live** — regardless
of what the CLI's own "change will apply without restarting the gateway"
message claims. Verify with a fresh PID (`ps aux | grep openclaw-gateway`)
before testing anything downstream of the change.

### Sandboxed sessions cannot use Garmin (or any user-configured MCP server)

Confirmed 2026-09-30/10-01: with Soma on OpenClaw's Codex harness, **any**
sandboxed session — dashboard or mobile, it doesn't matter which — loses
access to Garmin MCP entirely. This isn't a config bug: the Codex app-server
process that owns MCP connections runs on the Gateway host, outside the
sandbox container, so OpenClaw disables user MCP servers for sandboxed Codex
turns unconditionally rather than let a "sandboxed" session reach host-level
MCP access through the back door. No tool-policy allowlist fixes this; the
tools are not offered to the model at all for that turn.

The only way to give a conversation real Garmin access is to take it out of
sandboxing entirely, per-session, via `sessions.patch` with `sandboxMode:
"off"` (`openclaw gateway call sessions.patch --params
'{"key":"<session key>","sandboxMode":"off"}'`). Applied this to Soma's
persistent Android session (`agent:soma:node-27eb2826b877`) so mobile chat
has the same Garmin access as the main session. Any other sandboxed Soma
session — a fresh dashboard chat, a channel session, a subagent — still
correctly loses Garmin access, and that's expected, not a regression.

If sandboxed Soma subagents or channel sessions ever need Garmin access,
the fix isn't disabling sandboxing globally — it's a different agent
runtime/harness, or a future OpenClaw-supported sandbox-to-MCP execution
path. Not solved here; just recorded.

---

# 1. Product Vision

The desired experience is a persistent health and fitness assistant that can work with real personal data rather than relying on manually copied numbers.

Example interactions:

> How has my weight trend changed over the last month?

> Build me two simple strength sessions for this week and put them on my Garmin calendar.

> I had two chicken thighs, about a cup of rice, broccoli, and maybe a tablespoon of olive oil. Log that.

> Roughly how large has my average energy deficit been over the last two weeks?

> My sleep was poor last night. Should today's workout change?

The system should reduce tracking friction rather than create another demanding tracking routine.

---

# 2. Core Principles

## Reuse before building

Prefer existing:

- Garmin APIs and libraries;
- MCP servers;
- health/fitness applications;
- nutrition databases;
- Grafana/PostgreSQL;
- OpenClaw/Hermes tooling.

Do not create a bespoke health backend, dashboard framework, or Garmin integration unless existing components fail a concrete requirement.

## Approximation is acceptable when clearly labeled

Nutrition estimates from meal descriptions or photographs will often be approximate.

The system should preserve distinctions such as:

```text
measured
estimated
user-entered
device-derived
calculated
```

It should not present uncertain calorie or macro estimates as exact measurements.

## Low-friction input matters more than perfect data

A rough meal estimate that is actually logged is often more useful than an exact food diary that is too burdensome to maintain.

## Trends matter more than single-day precision

Energy expenditure from a wearable and calorie intake from estimated meals are both noisy.

Weight trend, multi-day energy balance, training history, sleep, and other longitudinal signals should be used together rather than over-interpreting individual daily values.

## Health recommendations should be conservative and evidence-oriented

The future coaching agent should prefer mainstream exercise and nutrition science over influencer trends, optimization hype, or unsupported claims.

Recommendations should distinguish:

- established evidence;
- plausible but uncertain guidance;
- personal preference;
- experimental ideas.

Medical diagnosis and treatment are outside the intended role.

---

# 3. High-Level Architecture

```text
                 HEALTH / FITNESS AGENT
                 OpenClaw or Hermes
                         |
            +------------+-------------+
            |                          |
        Garmin MCP                 Nutrition MCP
            |                          |
            v                          v
     Garmin Connect              Local nutrition DB
       |       |                 / wger / PostgreSQL
       |       |
 Garmin scale  Forerunner
            |
            +------------+-------------+
                         |
                    Analytics/View
                         |
               +---------+---------+
               |                   |
            Endurain             Grafana
         fitness UI          unified health cockpit
```

The exact dashboard architecture is intentionally unresolved in V1.

---

# 4. Garmin Integration

## Primary candidate: Taxuspt/garmin_mcp — verified, this is the real deal

Repository:

https://github.com/Taxuspt/garmin_mcp

**Verified 2026-09-29** (not just README claims): 1,260 stars, 387 forks, MIT,
not archived, last push 6 days before verification — actively maintained
with genuine community traction, the only one of the four Garmin candidates
below that has this. 110+ tools per README (activities, steps/HR/sleep/
stress/respiration, body composition, CTL/ATL/TSB/VO2max/HRV/power training
analytics, workout creation/scheduling, gear, nutrition, devices, courses,
file downloads). One correction to this doc's original framing: it does
**not** avoid raw Garmin payload construction entirely — high-level workout
builders exist for the common case, but raw JSON upload is also exposed as
an escape hatch, not hidden away. 55 open issues is nontrivial for its size;
worth a look at whether those cluster around Garmin-auth breakage (see below)
before assuming they're ordinary feature requests.

Reasons to evaluate first:

- broad Garmin Connect coverage;
- Docker deployment;
- MCP transport suitable for agent use;
- activity and wellness data;
- weight/body composition;
- sleep and training metrics;
- workout creation and scheduling.

Potential role:

```text
Garmin Connect
    <->
garmin_mcp
    <->
Fitness Agent
```

This should be the first Garmin MCP tested.

## Secondary candidate: NoaMatout/garmin-mcp — real, but essentially untested

Repository:

https://github.com/NoaMatout/garmin-mcp

**Verified 2026-09-29:** real repo, MIT, but 0 stars/0 forks/0 issues and
only ~5 weeks of commit history (created 2026-08-13, last push 2026-08-24,
silent for over a month since). Claimed features check out against the
README (local FIT files, DuckDB, a background sync worker that's explicitly
designed to "degrade into stale history rather than a broken server" on
credential expiry — a genuinely useful resilience property given the Garmin
auth risk below — opt-in writes gated behind an explicit flag with two-step
confirmation), but with zero external users, treat these as author-reported
and unverified in practice, not community-validated.

This may become preferable if local ownership of Garmin history becomes
important — its credential-free degrade path is specifically worth
remembering as a fallback if Taxuspt's tool hits a Garmin-side auth break
(see below).

## Training-oriented candidate: antboj/garmin-mcp — treat as effectively unmaintained

Repository:

https://github.com/antboj/garmin-mcp

**Verified 2026-09-29:** real repo, but 0 stars/0 forks/0 issues, **no
license file at all** (an actual adoption blocker — unclear reuse rights,
not just a maintenance signal), and a single-day commit burst (created and
last pushed the same day, 2026-06-07) with total silence for 3.5+ months
since. This is meaningfully weaker than "more specialized, not the initial
default" — there's no evidence of ongoing maintenance or any external
validation at all. Downgrading this from a real candidate to "worth
revisiting only if it sees renewed activity and gets a license."

Claimed strengths (unverified in practice, README-only):

- local SQLite cache;
- training zones;
- structured workout creation;
- weekly plans;
- running/endurance-oriented analytics.

---

# 5. Garmin Authentication and Cloudflare

Garmin Connect uses undocumented/private consumer APIs and authentication can be affected by rate limiting and Cloudflare/bot protection.

**This is not a theoretical risk — verified 2026-09-29, it already happened
and was worse than a generic caveat.** In March 2026, Garmin deployed
materially strengthened Cloudflare bot-detection/fingerprinting on its
SSO/login endpoints, which broke `garth` (the auth library underlying most
of these tools) and `python-garminconnect` simultaneously, along with
downstream consumers (Home Assistant's Garmin integration, various MCP
servers) — see `cyberjunky/python-garminconnect` issue #332 ("Did Garmin
change authentication API?", 40+ comments from affected users) and
`matin/garth` discussion #222 ("Deprecating Garth"). `garth` has since been
effectively deprecated; `python-garminconnect` 0.3.0 dropped the garth
dependency to work around it. Separately, **rate limiting (429s) on
login/SSO is per-account, not per-IP** — see issues #213 and #337 on the
same repo — so changing IP/User-Agent doesn't help once an account trips it;
recovery is time-based per account. Current workarounds (web-widget SSO with
CSRF tokens, `curl_cffi` Chrome TLS impersonation to pass the fingerprint
check) are community-maintained cat-and-mouse fixes, not stable APIs, and
should be expected to need revisiting again.

**Concrete implication for this plan:** budget for an actual
auth-recovery/backoff strategy, not just token persistence; expect to
monitor for another Garmin-side break; and keep a credential-free fallback
in mind — NoaMatout's garmin-mcp candidate's background-sync design (degrade
to stale local history rather than a broken server on credential expiry) is
worth treating as a real resilience feature to borrow from, not just a
nice-to-have, given this history.

The underlying `python-garminconnect` ecosystem includes multiple login strategies and browser/TLS impersonation mechanisms, but repeated automated login should still be avoided.

Preferred operating pattern:

```text
interactive authentication
        |
        v
persist Garmin tokens/session
        |
        v
reuse session for normal synchronization
        |
        v
human/browser reauthentication only when necessary
```

Persistent Garmin authentication state should live on SSD-backed storage and should not disappear when the MCP container is recreated.

The MCP should remain accessible only inside the trusted Overmind/Tailscale environment.

A browser-assisted authentication fallback may be worth retaining as a contingency if normal authentication becomes blocked.

Candidate implementation demonstrating this pattern:

https://github.com/bmccarn/garmin-mcp-server

**Verified 2026-09-29:** real, MIT, 2 stars, modest but genuine ongoing
activity (~5 months, last push ~3 weeks prior to verification). The
auth-pattern claim checks out specifically: a one-time interactive
`garmin_auth.py` login (handles MFA), tokens saved to `~/.garminconnect/`
and reused automatically, tokens last ~1 year, re-run only on expiry, env
vars available for non-interactive setup. Good as a pattern reference given
its small scale — not a claim of production robustness on its own.

Do not make repeated credential-based logins part of ordinary polling.

---

# 6. Workout Creation

A key V1 capability is **write access back into Garmin**.

Target workflow:

```text
human request
    |
    v
fitness agent
    |
    | designs workout
    v
Garmin MCP
    |
    | create + schedule
    v
Garmin Connect
    |
    v
Forerunner
```

Initial test:

> Create one simple structured workout, schedule it for a specific day, sync the watch, and verify that it appears correctly.

This validates both the Garmin write path and the practical usefulness of the agent.

---

# 7. Nutrition

The intended interaction should be conversational rather than conventional manual calorie tracking.

Examples:

```text
"I had two eggs, toast with butter, and coffee with milk."

"I made chicken thighs with rice and broccoli."

[meal photograph]
```

The agent should estimate:

- calories;
- protein;
- carbohydrates;
- fat;
- optionally fiber and other useful nutrients;
- uncertainty/confidence where appropriate.

For packaged food or known products, exact database/barcode data should be preferred over visual estimation.

## Candidate: nutrition-mcp

Repository:

https://github.com/RootMePLS/nutrition-mcp

**Verified 2026-09-29:** real, MIT, TypeScript — but 0 stars/0 forks/0
issues, and a single ~8-day commit burst (2026-08-04 to 2026-08-12) followed
by ~7 weeks of silence as of verification. Feature claims below are
confirmed against the README, but this is an unproven, low-adoption solo
project — reasonable as a technical fit for the interaction model this doc
wants, but should not be treated as mature or battle-tested going in.

Interesting properties:

- natural-language meal logging;
- photo-based meal input;
- calories/macros;
- body weight;
- recurring meals;
- Open Food Facts/barcode integration;
- local PostgreSQL option.

This is currently the closest match to the desired low-friction nutrition UX.

## Candidate: wger + wger MCP

wger:

https://github.com/wger-project/wger

MCP:

https://github.com/wger-project/mcp-server

Strengths:

- mature self-hosted fitness application;
- nutrition and meal tracking;
- routines/workout logging;
- body weight and measurements;
- REST API;
- official project MCP;
- modular MCP tool groups.

**Verified 2026-09-29:** wger itself is real, official, and genuinely mature
— 6,989 stars, 1,028 forks, AGPL-3.0, created 2013, actively maintained (push
the same day as verification). The MCP server is also real and official
(under the wger-project org, not a third party), actively maintained (~4
stars, push the day before verification), exposing ~88 tools over wger's
REST API. **One real caveat to carry forward: its own README explicitly
self-describes as "WIP, not all things might work correctly yet."** wger the
application is mature; its MCP integration is not — don't cite the MCP
server itself as a finished/battle-tested piece.

wger may be preferable if a broader structured health/fitness application is desired.

For V1, nutrition-mcp should be evaluated first for interaction quality, while wger remains the mature/general alternative.

---

# 8. Calories In vs. Calories Out

This is the primary reason to create a cross-domain analytics view rather than treating Garmin and nutrition as unrelated applications.

Garmin can provide estimated:

```text
resting calories
+
active calories
=
total energy expenditure
```

Nutrition provides estimated:

```text
food calories
=
energy intake
```

Derived daily value:

```text
energy balance = intake - expenditure
```

The system should also calculate rolling values such as:

- 7-day mean intake;
- 7-day mean expenditure;
- 7/14/30-day estimated energy balance;
- weight rolling average;
- observed weight-change rate.

The dashboard should make it possible to compare estimated energy balance against actual weight trend.

The system should **not** assume either wearable expenditure or meal estimation is perfectly accurate.

---

# 9. Dashboard Layer

The dashboard decision is intentionally deferred.

Two strong existing Lego bricks serve somewhat different purposes.

## Endurain

https://endurain.com/

Potential role:

- polished self-hosted fitness UI;
- Garmin activity synchronization;
- activity browsing;
- gear;
- body composition;
- sleep/steps/health views.

Endurain may be the better human interface for detailed fitness and activity exploration.

## Grafana

https://grafana.com/

Potential role:

- unified cross-domain health cockpit;
- query multiple databases;
- combine Garmin, nutrition, and derived metrics;
- calories in vs. calories out;
- rolling weight trend;
- macros;
- training volume;
- sleep;
- HRV/readiness;
- custom longitudinal analysis.

Likely distinction:

```text
Endurain
    = rich fitness/activity application

Grafana
    = unified cross-domain analytics dashboard
```

V1 should evaluate both without prematurely choosing one as the sole interface.

A likely future arrangement is to use Endurain for detailed fitness/activity exploration and Grafana for the overall health summary.

---

# 10. Data Ownership

Do not force all data into one database initially.

V1 can allow domain-specific systems to remain authoritative:

```text
Garmin-generated data
    -> Garmin Connect

nutrition records
    -> nutrition MCP / local database

activity visualization
    -> Endurain

cross-domain analytics
    -> Grafana queries / derived views
```

Later, we may choose to maintain a local historical archive independent of Garmin.

Potential approaches include:

- the local storage provided by a Garmin MCP;
- GarminDB;
- Endurain/PostgreSQL;
- a simple analytics warehouse.

This is not required for the first working system.

---

# 11. Agent Design

Working name:

**Health & Fitness Coach Agent**

The final identity/name can be chosen later.

The agent should combine three roles:

```text
personal trainer
+
nutrition coach
+
health-data analyst
```

Its purpose is not merely to answer questions. It should be able to work with real data and tools.

Initial capabilities:

- read Garmin health/training data;
- inspect weight and activity trends;
- create/schedule workouts;
- record meals from descriptions or photographs;
- estimate calories/macros;
- query nutrition history;
- explain trends;
- help plan exercise and nutrition;
- produce concise progress summaries.

## Evidence standard

The agent should:

- prefer consensus guidelines and peer-reviewed evidence;
- avoid fitness-industry hype and unsupported optimization claims;
- distinguish evidence strength;
- avoid treating correlation in personal tracking data as established causation;
- prefer simple interventions before complicated ones;
- make uncertainty explicit.

Future agent instructions should define preferred authoritative sources and how often current research should be checked.

## Safety boundary

The agent can support:

- exercise planning;
- nutrition planning;
- habit formation;
- trend interpretation;
- general wellness information.

It should not independently diagnose disease, prescribe medication, or present itself as a substitute for professional medical care.

Agent-policy refinement is explicitly a later workstream and should not block the infrastructure MVP.

---

# 12. V1 Implementation Sequence

## Phase 1 — Garmin read access

Deploy the primary Garmin MCP on Overmind.

Verify retrieval of:

- body weight/body composition;
- recent activities;
- daily calories/expenditure;
- sleep;
- useful training metrics.

Persist authentication tokens.

## Phase 2 — Garmin write access

Create and schedule one structured workout.

Verify it arrives correctly on the Forerunner.

## Phase 3 — Conversational nutrition

Deploy the selected nutrition tool.

Verify:

```text
meal description
    ->
agent estimate
    ->
stored calories/macros
    ->
later retrieval
```

Test at least one photograph-based meal if supported.

## Phase 4 — Unified energy view

Combine:

```text
Garmin expenditure
nutrition intake
Garmin weight
```

Create the first cross-domain dashboard showing:

- calories in;
- calories out;
- daily balance;
- rolling balance;
- weight trend;
- protein/macros.

This can use Grafana first if it is the shortest path.

## Phase 5 — Evaluate dashboard experience

Compare:

- Endurain as the primary fitness UI;
- Grafana as the cross-domain summary;
- whether both are useful together.

Do not build a custom frontend unless both prove inadequate.

## Phase 6 — Refine the coach agent

Define:

- system prompt/charter;
- evidence standards;
- preferred sources;
- workout-planning rules;
- nutrition-estimation conventions;
- uncertainty handling;
- escalation boundaries.

---

# 13. V1 Success Criteria

The first useful system exists when:

- the agent can read Garmin health and fitness data;
- Garmin authentication survives service restarts;
- the agent can create and schedule a workout;
- the workout arrives on the watch;
- a meal can be logged conversationally without manual ingredient entry;
- calories and macros persist;
- calories in, calories out, and weight trend can be viewed together;
- all major components are self-hosted or locally controlled where practical;
- no custom application backend or dashboard frontend was required.

---

# 14. Explicit Non-Goals for V1

Do not initially build:

- a custom Garmin API client;
- a custom MCP server unless required;
- a custom nutrition database;
- a custom dashboard application;
- a medical diagnostic agent;
- an elaborate health knowledge graph;
- a unified canonical health database;
- automatic optimization based on noisy single-day metrics;
- a complicated multi-agent organization.

The first objective is to validate the end-to-end loop using existing components.

---

# 15. Open Questions

The following should be answered through experimentation rather than architecture speculation:

1. Which Garmin MCP is most reliable against current Garmin authentication/WAF behavior?
2. Is Endurain sufficient as the primary human dashboard, or is Grafana still valuable for cross-domain analytics?
3. Does nutrition-mcp provide enough structure and reliability, or is wger a better long-term system of record?
4. How accurate/useful are meal photo and natural-language estimates in ordinary use?
5. Should Garmin data eventually be archived locally as canonical history?
6. What should the coach agent be named?
7. What exact evidence and recommendation policy should govern the coach agent?
8. How much proactive behavior is actually useful before it becomes intrusive?

---

# 16. Working Thesis

> **Build the health system from existing Lego bricks: Garmin provides device data, MCPs make it agent-accessible, a low-friction nutrition service records intake, Endurain and/or Grafana provide human-readable views, and a science-oriented coach agent turns those pieces into useful planning and interpretation.**

The system should earn additional complexity only after this simple composition proves useful in daily life.
