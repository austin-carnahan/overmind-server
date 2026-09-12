# Prowlarr

**Status:** PARTIAL — see [status legend](../../design-notes/README.md#status-legend);
deployed and verified: connected to Radarr/Sonarr, indexer sync confirmed
working end to end (search results reach both apps).

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

## Tags do double duty — a real gotcha, not a hypothetical one

Prowlarr's own UI warns: "an indexer with a tag will only sync to apps with
the same tag." Tags aren't just for binding an indexer to a proxy (see
[cloudflare-solver](../cloudflare-solver/README.md)) — tagging an indexer for
that reason silently stops it syncing to Radarr/Sonarr unless those
Application entries carry the same tag too. Hit this directly: tagged an
indexer for its proxy, and it stopped appearing in Radarr/Sonarr until the
same tag was added to both Application entries under Settings → Apps.

## Not this repo's decision

Which specific indexer(s)/tracker(s) to add is an account/access choice —
that's yours to make and configure directly in Prowlarr's UI, not something
committed here.
