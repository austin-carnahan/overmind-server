# FlareSolverr

**Status:** PROPOSED — see [status legend](../../design-notes/README.md#status-legend);
[compose.yaml](compose.yaml) below, not yet deployed.

## Selected implementation

`flaresolverr/flaresolverr` — confirmed `linux/arm64` directly against the
Docker Hub manifest before adding this (it bundles a real headless Chromium,
which has had inconsistent ARM support historically). No config volume: it's
a stateless HTTP proxy that solves Cloudflare's JS-challenge pages on behalf
of [Prowlarr](../prowlarr/README.md) for indexers that require it.

Configure it in Prowlarr as an indexer proxy (Settings → Indexers → add a
FlareSolverr proxy) pointed at `http://flaresolverr:8191`, then assign it to
whichever specific indexer(s) report needing Cloudflare bypass — not a
global default, only where actually required.

Reachable on `8191` over Tailscale like everything else, and by container
name on the shared network for Prowlarr itself.

## Worth watching on a Pi

Solving a challenge spins up a real Chromium instance briefly — heavier than
this stack's other services momentarily during an active solve, though idle
footprint is small. Keep an eye on this if it's ever invoked frequently; no
guard needed preemptively, just something to notice if the Pi feels strained
during indexer searches.
