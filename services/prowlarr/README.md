# Prowlarr

**Status:** PROPOSED — see [status legend](../../design-notes/README.md#status-legend);
[compose.yaml](compose.yaml) below, not yet deployed.

## Selected implementation

`linuxserver/prowlarr` (see [compose.yaml](compose.yaml)). Config lives at
`/var/lib/overmind/prowlarr/config`, SSD-backed, same pattern as the other
`*arr` services.

Centralizes indexer configuration so it's added once here instead of
separately in [Radarr](../radarr/README.md) and [Sonarr](../sonarr/README.md) —
Prowlarr syncs indexers to both via their APIs (add each as an "Application"
in Prowlarr's Settings, pointed at `radarr:7878` / `sonarr:8989` with their
API keys from Settings → General in each app). Prowlarr does not touch
downloads itself; Radarr/Sonarr still hand off to
[Transmission](../transmission/README.md) as already configured.

WebUI on `9696`, reachable only over Tailscale like everything else on this
host — never port-forwarded.

## Not this repo's decision

Which specific indexer(s)/tracker(s) to add is an account/access choice —
that's yours to make and configure directly in Prowlarr's UI, not something
committed here.
