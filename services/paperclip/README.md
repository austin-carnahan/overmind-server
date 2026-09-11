# Paperclip

**Status:** PROPOSED — see [status legend](../../design-notes/README.md#status-legend);
[compose.yaml](compose.yaml) below, unblocked by the SSD (unlike the media
services) but not yet deployed.

Per the [orchestration research](../../design-notes/overmind_agent_orchestration_research.md):
pilot Paperclip on one small, generic, reversible task in this repo — a
documentation or config change, with a forced human decision before
implementation and independent review after — **before** any media-specific
integration. The phased media-automation plan in
[Agentic Media & ROM Automation Design](../../design-notes/Overmind — Agentic Media & ROM Automation Design.md)
puts Paperclip after Sonarr/Bazarr/RomM/an agent API, which are themselves
still blocked on the SSD; don't confuse "Paperclip can run today" with "the
media-automation vision is ready."

## Selected implementation

Two containers (see [compose.yaml](compose.yaml)), not Paperclip's own
single-container quickstart shape:

- `paperclip-db`: `postgres:17-alpine`, independently versioned and backed up
  with standard Postgres tooling.
- `paperclip`: `ghcr.io/paperclipai/paperclip`, pinned by **stable version tag
  and immutable digest** together (`2026.831.1@sha256:f58ff8e2...`) — resolve
  a fresh digest before actually deploying, this project publishes frequently
  and any digest recorded here should be treated as stale until re-checked.
  Confirmed multi-arch (`linux/amd64` + `linux/arm64`) directly against the
  GHCR manifest, so no from-source build on the Pi.

Chosen over the quickstart's embedded-Postgres shape (a real `embedded-postgres`
v18 binary managed by the Node process, not SQLite) because this is meant to
become durable control-plane infrastructure — independent Postgres version
control, standard backup/restore tooling, and decoupled restart lifecycle are
worth one extra trivial container. Paperclip's own docs draw the same
boundary: embedded Postgres for easy local operation, your own Postgres for
production.

State lives at `/var/lib/overmind/paperclip/{app,postgres}` — real, persistent,
not disposable.

## Network exposure: private mode is an app policy, not a network boundary

`PAPERCLIP_DEPLOYMENT_EXPOSURE=private` and `PAPERCLIP_DEPLOYMENT_MODE=authenticated`
are Paperclip's own application-level policy — they don't restrict which
network interfaces Docker actually publishes the port on. `compose.yaml` binds
the published port to `127.0.0.1` only, and the intended front door is
**Tailscale Serve**, not a broadly-published Docker port:

```sh
# Confirm HTTPS certs are enabled tailnet-wide in the admin console first.
# Exact flags vary by installed Tailscale version — check `tailscale serve --help`.
sudo tailscale serve --bg --https=443 http://127.0.0.1:3100
```

This gives a tailnet-only HTTPS endpoint at `https://overmind-01.<tailnet>.ts.net`
with MagicDNS, while Paperclip itself never binds anything but loopback. Set
`PAPERCLIP_PUBLIC_URL` in `.env` to that address once Serve is configured.

## Secrets

Both required, no fallback, generate independently with `openssl rand -hex 32`:
`BETTER_AUTH_SECRET` (session signing) and `PAPERCLIP_TOOL_ACTION_SIGNING_SECRET`
(signs tool-action approvals — a different secret, easy to miss). At least one
LLM provider needs auth for a runner to do anything, but that doesn't have to
be an API key in `.env` — a runner can also inherit a supported CLI/subscription
login instead.

## Backup: a DB dump alone is not a complete recovery

Paperclip also needs its non-database state (`/var/lib/overmind/paperclip/app`)
and, critically, its **local secrets/`master.key`** — restored encrypted
secrets are unusable without the matching key that encrypted them. Back up
all three together, not just the database. Paperclip has built-in scheduled
and manual logical backup support (`db:backup`) for both deployment shapes;
prefer that over an ad hoc `pg_dump` where available.

## Still to verify before real use

That `PAPERCLIP_ALLOWED_HOSTNAMES` plus the Tailscale Serve endpoint actually
resolve together correctly, that a restore from a `db:backup` + app-state +
`master.key` bundle actually works end to end, and — per the pilot plan above
— that one small reversible task can go through create → plan → review →
human decision → implement → review → merge before trusting it with anything
larger.
