# Cloudflare bypass proxy

**Status:** PARTIAL — see [status legend](../../design-notes/README.md#status-legend);
deployed and confirmed working against a real Cloudflare-protected tracker
(every test request returned 200, ~17-18s each, where FlareSolverr had failed
100% of the time). Ultimately not needed for the indexer actually in use —
switched to one that doesn't require Cloudflare bypass — but proven
functional and left in place for whichever indexer needs it next.

## Selected implementation: `simple-cloudflare-solver`, not FlareSolverr

Originally `flaresolverr/flaresolverr`. Swapped after FlareSolverr consistently
failed to solve a real tracker's Cloudflare challenge on this host — every
attempt detected the challenge, then hung for the full timeout with zero
variance (not a resource/config issue; `shm_size: 2gb` made no difference).
That pattern reads as Cloudflare's bot-detection successfully identifying the
automated browser, not a fixable local misconfiguration.

Verified before switching (don't trust a blog post's tool recommendation
without checking): confirmed neither Prowlarr nor this proxy was ever routed
through PIA (both showed the same non-VPN egress IP as each other, distinct
from gluetun's), ruling out VPN-IP-reputation as the cause; confirmed
`nlevee/simple-cloudflare-solver` is a real, active (89 stars, MIT, not
archived), `arm64`-published image using a genuinely different bypass library
(`CloudflareBypassForScraping`) rather than the same Chromium approach under
a different name.

Configure identically to how FlareSolverr would have been configured in
Prowlarr (Settings → Indexer Proxies → FlareSolverr type, since this project
implements the same API contract) — just pointed at this container's port
instead. Default port is `8000`, not FlareSolverr's `8191`; update
[compose.yaml](compose.yaml)'s port mapping and Prowlarr's proxy URL together
if you change it.

## Resolved

Confirmed working (see Status above). Not currently wired to any indexer in
active use, since the indexer that needed it was swapped for one that
doesn't — reconnect it the same way described above (Settings → Indexer
Proxies) whenever an indexer actually needs Cloudflare bypass again.
