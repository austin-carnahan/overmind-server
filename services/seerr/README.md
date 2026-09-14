# Seerr

**Status:** PROPOSED — see [status legend](../../design-notes/README.md#status-legend);
[compose.yaml](compose.yaml) below, not yet deployed. Part of the
[Seerr + Maintainerr design brief](../../design-notes/overmind_seerr_maintainerr_setup_brief.md).

## Selected implementation

[seerr-team/seerr](https://github.com/seerr-team/seerr) — verified real
before adopting it: 12,500+ stars, a genuine merger of Overseerr and
Jellyseerr ("created to deliver an excellent request management solution for
Plex, Jellyfin and Emby users," per its own docs), confirmed `linux/amd64`
+ `arm64`, signed images with an SBOM.

Pinned `v3.0.1` + digest — resolve a fresh digest before actually
deploying. Config lives at `/var/lib/overmind/seerr/config`, SSD-backed. Runs
as the image's built-in `node` user (UID 1000) — no PUID/PGID env vars, just
matches `austin`'s UID directly. `security_opt`/`cap_drop` match the
project's own documented compose example, not something added here.

Human-facing discovery/request UI — never in the playback or download path.
If it's offline, Jellyfin/Radarr/Sonarr/Transmission keep working normally.

## Setup (in Seerr's own WebUI, not stored in compose)

- **Media server**: connect Jellyfin (`http://jellyfin:8096`), import/allow
  Jellyfin users.
- **Services**: connect Radarr (`http://radarr:7878`) and Sonarr
  (`http://sonarr:8989`), mark the appropriate instances as defaults for
  movie/TV requests respectively.
- **Permissions**: configure request limits per user; trusted users can be
  auto-approved.
- Use a **separate Jellyfin API key** from Maintainerr's, not a shared one —
  least-privilege, same reasoning as every other API-key integration in this
  project.
