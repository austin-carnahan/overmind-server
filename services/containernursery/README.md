# ContainerNursery

**Status:** PROPOSED — see [status legend](../../design-notes/README.md#status-legend);
[compose.yaml](compose.yaml) and [config/config.yml](config/config.yml) below,
not yet deployed (`docker compose -f services/compose.yaml up -d` not yet run
with this fragment included).

## What this is for

Some services are heavy while idle but rarely actually used — `doclet`
(docling-serve) is the motivating case: a persistent several-hundred-MB-to-3GB
resident footprint and occasional CPU bursts, for a document-conversion
workload used only occasionally. ContainerNursery sits between Caddy and a
managed container: it wakes the container on the first proxied request after
it's stopped, and stops it again after a configured idle period. The
container spends most of its life not running at all.

## Selected implementation

[ItsEcholot/ContainerNursery](https://github.com/ItsEcholot/ContainerNursery) —
verified directly against the real GHCR manifest before adopting it: `1.9.0`
publishes a genuine multi-arch manifest list (confirmed both `amd64` and
`arm64` platform entries present), not just an amd64 image with an ARM tag
slapped on. Pinned by tag **and** the manifest-list digest together, same
convention as every other service here — resolve a fresh digest before
actually redeploying to a newer tag.

Ruled out during research: [Conslee](https://github.com/tulupovden/Conslee)
(similar pitch, but multiple near-identical forks under unrelated generic
GitHub usernames alongside the original, and no confirmed ARM64 support —
not enough trust signal to adopt without a lot more digging) and
[Sablier](https://sablierapp.dev/) (the more mature, more widely-adopted
option generally, but its Caddy integration requires building a custom Caddy
image with the Sablier module compiled in — Caddy doesn't support runtime
plugin loading — which is real ongoing build/maintenance surface this repo
doesn't currently carry for Caddy. Worth revisiting if this pattern expands
to many services and that extra cost becomes worth it; not for a
single-service pilot).

## A real, deliberate privilege grant — not a formality

This is the **first service in this repo with access to the host's Docker
socket** (`/var/run/docker.sock`). That's effectively root-equivalent control
over every container on this host — start/stop, arbitrary bind mounts, image
pulls — not scoped to just the containers ContainerNursery is configured to
manage. Accepted here because the feature fundamentally requires it and the
*configured* scope (start/stop two named services so far) is narrow even
though the underlying grant is broad. No host port is published — only Caddy
reaches this, over the shared `services_default` network by container name,
same as every other proxied service.

## Extending to more services

The whole extension mechanism is two small, mechanical edits — see the
comment at the top of [config/config.yml](config/config.yml):

1. Add a `proxyHosts` entry to `config/config.yml` for the new service
   (domain/containerName/proxyHost/proxyPort matching its existing Caddy
   vhost and compose service name).
2. Change that service's own Caddyfile block from
   `reverse_proxy <service>:<port>` to `reverse_proxy containernursery:80`.

Nothing else changes — one ContainerNursery instance manages every
sleep-enabled service via one config file, matched by the incoming Host
header.

## Open question to verify once actually deployed

ContainerNursery has no config field for a specific health-check path — it
polls `proxyHost:proxyPort`'s root with a configurable HTTP method
(`proxyUseCustomMethod`), not a chosen path. Confirmed directly against the
live `doclet` container: root `/` returns `404`, while its real health
endpoint `/health` returns `200`. Upstream's docs don't say whether it treats
any HTTP response (including 404) as "the port answered, container is up," or
specifically requires a 2xx. If wake-up gets stuck treating doclet as
perpetually "not ready," that's the first thing to check — there's no config
knob to point the check at `/health` instead, so a fix would mean either
confirming 404-is-fine empirically, or an upstream feature request.

## Rollback

Revert the Caddyfile's `doclet.home.arpa` block to `reverse_proxy
doclet:5001` directly, remove this fragment from `services/compose.yaml`'s
`include:` list, and `docker compose -f services/compose.yaml up -d` to apply
— `doclet` itself is untouched by any of this and keeps running as it always
has (`restart: unless-stopped`) once nothing is stopping it on a timer.
