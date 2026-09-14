# Maintainerr

**Status:** PROPOSED — see [status legend](../../design-notes/README.md#status-legend);
[compose.yaml](compose.yaml) below, not yet deployed. Part of the
[Seerr + Maintainerr design brief](../../design-notes/overmind_seerr_maintainerr_setup_brief.md).

## Selected implementation

[Maintainerr/Maintainerr](https://github.com/Maintainerr/Maintainerr) —
verified real before adopting it: 2,200+ stars, described by its own README
as "looks and smells like Seerr, does the opposite" (a companion project, not
affiliated infrastructure), confirmed `linux/amd64` + `arm64`.

Pinned `3.13.0` + digest — resolve a fresh digest before actually deploying.
Data lives at `/var/lib/overmind/maintainerr/data`, SSD-backed. Runs as
`user: 1000:1000` directly (this image's own convention, not PUID/PGID env
vars) — matches `austin`'s UID.

Automated retention/cleanup — evaluates rules using Jellyfin viewing state,
Seerr request state, and Radarr/Sonarr metadata; matches enter a visible
"Leaving Soon" collection for a grace period before Maintainerr tells
Radarr/Sonarr to remove or unmonitor them. Never in the playback or download
path — if it's offline, everything else keeps working normally.

## No built-in login — a real, accepted gap, not an oversight

Maintainerr has no application-level authentication at all. Per the design
brief, the accepted boundary for now is Tailscale-only reachability (no
router port-forward) — the same network posture as everything else here, but
without the extra app-auth layer every *other* service in this project has.
Revisit with an authenticated reverse proxy only if that stops being
sufficient — don't add one preemptively.

## Setup (in Maintainerr's own WebUI, not stored in compose)

- **Connect** Jellyfin, [Seerr](../seerr/README.md), Radarr, and Sonarr, each
  with their own API key. Use a **separate Jellyfin API key** from Seerr's,
  not a shared one.
- **Start with a non-destructive test rule** and inspect its matches before
  enabling any actual deletion — per the design brief's own integration
  order, don't skip straight to automated removal.

### Initial retention policy (starting defaults, tune after observing real usage)

```text
Watched requested media    → eligible after ~45-60 days without use
Requested but never watched → eligible after ~90 days
Recently watched / active   → protected
Cleanup candidate → "Leaving Soon" → 14-day grace period → delete via Radarr/Sonarr
```

A direct media-library mount (commented out in [compose.yaml](compose.yaml))
is not required for normal Radarr/Sonarr-managed cleanup — only add it if
later using Maintainerr's leftover-folder cleanup feature specifically.
