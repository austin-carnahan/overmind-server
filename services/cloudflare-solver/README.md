# Cloudflare bypass proxy

**Status:** PROPOSED — see [status legend](../../design-notes/README.md#status-legend);
[compose.yaml](compose.yaml) below, deployed but unresolved — see below.

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

## Still unresolved

Whether this one actually succeeds where FlareSolverr didn't, against the
same real Cloudflare-protected tracker. If it also fails, that's a stronger
signal this specific site is simply not solvable by either tool on this
hardware right now, and the answer is a different indexer, not a third
bypass tool.
