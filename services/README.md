# Service plans

No service in this repository has a verified deployment definition yet. These
notes identify roles and boundaries so implementation can proceed one service at
a time. Existing helper scripts are manual components, not an ingestion daemon.

| Plan | Purpose |
| --- | --- |
| [Tailscale](tailscale/README.md) | Private remote access |
| [File sharing](file-sharing/README.md) | Selected Substrate collections for clients |
| [Jellyfin](jellyfin/README.md) | Media browsing/playback |
| [Transmission](transmission/README.md) | Downloads, routed through PIA |
| [PIA](pia/README.md) | Selected traffic's private outbound egress |
| [Ingestion](ingestion/README.md) | Manual scan/validation and promotion contract |
| [Radarr](radarr/README.md), [Sonarr](sonarr/README.md), [Bazarr](bazarr/README.md) | Library organization and subtitles |
| [Prowlarr](prowlarr/README.md) | Centralized indexer management for Radarr/Sonarr |
| [Cloudflare solver](cloudflare-solver/README.md) | Cloudflare bypass proxy for indexers that require it (not FlareSolverr — see its README) |
| [Paperclip](paperclip/README.md) | Bounded agent coordination |
| [Research](research/README.md) | Capture, notes, papers, and future search |
| [Inference](inference/README.md) | Deferred model-serving capability |
| [Pi-hole](pihole/README.md) | Optional independent DNS host |

## Before marking a service deployable

Record the selected upstream method/version, ARM/host compatibility, dependencies,
exposed interfaces, credentials, content permissions, the service's own default state/cache locations (document exact paths),
and SSD backing where needed. Provide a nonsecret example that is valid for that
version, verification commands, backup/restore, and rollback. Identify required
mounts before enabling startup. Use the application's supported data layout.

Follow [storage](../design-notes/storage-layout.md) and
[security](../design-notes/security-model.md). Do not deploy every plan together.

## Containerized services

A containerized service keeps a `compose.yaml` next to its README. The root
[compose.yaml](compose.yaml) brings in whichever fragments are currently
selected via Compose's `include:`, so `docker compose -f services/compose.yaml
up -d` runs the whole enabled stack without a custom orchestrator — comment a
line out to disable a service, add one when a new service gets a
`compose.yaml`.

Adopted convention so far, not an imposed hierarchy (see
[storage](../design-notes/storage-layout.md)): small, low-write app state/config
lives at `/var/lib/overmind/<service>/...` and is usable without the SSD; a
service that reads/writes Library content stays disabled (commented out of the
root `compose.yaml`) until the SSD is actually attached and mounted there.

**Always run `docker compose -f compose.yaml ...` from this directory
(`services/`), never bare `docker compose up -d` from inside an individual
service's own subdirectory.** Every fragment is also independently valid as
its own standalone compose file — bare `docker compose up -d` run from e.g.
`services/prowlarr/` auto-discovers that directory's `compose.yaml` alone and
creates an isolated project/network (`prowlarr_default`) instead of joining
the shared one, so that service silently can't reach any other by container
name even though everything looks fine in `docker ps`. Hit this repeatedly
while bringing services up one at a time; if it recurs, `docker network ls`
showing more than one `*_default` network is the tell, and the fix is
`docker compose -f compose.yaml down`, remove the stray containers/networks,
then `up -d` again in one pass so everything lands on the same network.
