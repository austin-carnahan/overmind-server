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
