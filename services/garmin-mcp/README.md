# Garmin MCP

**Status:** PROPOSED — see [status legend](../../design-notes/README.md#status-legend);
[compose.yaml](compose.yaml) below, not yet deployed. Phase 1 of
[overmind-health-fitness-system-v1.md](../../design-notes/overmind-health-fitness-system-v1.md).

## Selected implementation

[Taxuspt/garmin_mcp](https://github.com/Taxuspt/garmin_mcp) — verified
2026-09-29 before adopting it: 1,260 stars, actively maintained (push within
days of verification), MIT, not archived. The only one of several candidate
Garmin MCP servers evaluated with genuine community traction; see the design
note's Garmin Integration section for the full comparison.

**No published image exists**, so this is a deliberate exception to this
repo's usual pinned-image convention: built directly from a pinned upstream
commit (`build.context` as a git URL + commit SHA) rather than a floating
branch, and rather than vendoring the source into this repo. Re-pin the
commit deliberately when there's a reason to (a real fix/feature, or to keep
up with upstream's response to the next Garmin-side API change — see below),
not routinely.

## Garmin auth is the real risk here, not this container

Verified 2026-09-29 (see the design note): Garmin broke this entire
unofficial ecosystem once already, in March 2026, via strengthened
Cloudflare bot-detection on its SSO/login endpoints — not a hypothetical.
Separately, login rate-limiting is per-account, not per-IP, and recovery is
time-based only. Token persistence below prevents *routine* re-auth on
restart; it does nothing if Garmin breaks the API again. If this container
stops authenticating, check upstream's issues before assuming a local
misconfiguration.

## First-time setup

1. Create the file-based secrets (never as plain compose environment
   values — these are your real Garmin credentials):
   ```sh
   mkdir -p secrets
   echo -n 'your@email.com' > secrets/garmin_email.txt
   echo -n 'your-password' > secrets/garmin_password.txt
   chmod 600 secrets/*.txt
   ```
2. `cp .env.example .env` (no secrets in it, just non-secret settings).
3. Build and run once **interactively** to complete the first login,
   including MFA if enabled — do this before enabling the normal detached
   service:
   ```sh
   docker compose build
   docker compose run --rm garmin-mcp
   ```
   If MFA is enabled, it'll prompt for the code from your email/phone right
   in that terminal. Once it succeeds, tokens are written to the
   `/var/lib/overmind/garmin-mcp/garminconnect` volume and this interactive
   step doesn't need repeating (barring token expiry, ~6 months, or another
   Garmin-side break).
4. Bring it up normally: `docker compose up -d`.

## State

- `/var/lib/overmind/garmin-mcp/garminconnect` — OAuth tokens. Real,
  persistent, not disposable — losing this means redoing the interactive
  login (and, if MFA is enabled, needing a fresh code).
- `/var/lib/overmind/garmin-mcp/fit` — downloaded FIT activity files.

## Network exposure

Bound to `127.0.0.1:8000` only — same pattern as `paperclip`/`doclet`. Only a
same-host process is meant to reach this (the native OpenClaw Gateway, once
the fitness agent is wired up to it as an MCP tool source) — not published
more broadly.

## Verification

Once running:
```sh
curl -s http://127.0.0.1:8000/healthz
```
Real Phase 1 verification (per the design note) is retrieving body
weight/composition, recent activities, daily calories/expenditure, sleep,
and training metrics through an actual MCP client call — a bare health check
confirms the process is up, not that Garmin auth or data retrieval works.
