# Overmind Media Additions: Seerr + Maintainerr

**Purpose:** Add a lightweight request/discovery layer and an automated retention/cleanup layer to the existing Jellyfin + Radarr + Sonarr + Transmission media stack.

## Target Architecture

```text
Users
  ├── Seerr      → discover/request movies & TV
  └── Jellyfin   → watch media

Seerr
  ├── Radarr     → movie requests
  └── Sonarr     → TV requests

Radarr / Sonarr
  └── Transmission → acquisition

Jellyfin
  └── shared media library on SSD

Maintainerr
  ├── Jellyfin   → viewing/library state
  ├── Seerr      → requester/request state
  ├── Radarr     → movie retention/deletion
  └── Sonarr     → TV retention/deletion
```

Neither new service should sit in the playback or download data path. If either is offline, Jellyfin, Radarr, Sonarr, Transmission, and the media library should continue working normally.

## 1. Seerr

**Role:** Human-facing discovery and request UI.

Seerr lets users browse/search movies and TV, see what is already available in Jellyfin, and request missing content. Movie requests go to Radarr; TV requests go to Sonarr.

### Setup

1. Deploy Seerr with Docker/Compose and persist `/app/config`.
2. Put it on the same Docker network as Jellyfin, Radarr, and Sonarr where practical.
3. Open the web UI on port `5055`.
4. Connect Jellyfin and import/allow Jellyfin users.
5. Connect Radarr and Sonarr and mark the appropriate instances as defaults.
6. Configure user request permissions/limits; trusted users can be auto-approved.

Typical internal service URLs:

```text
http://jellyfin:8096
http://radarr:7878
http://sonarr:8989
```

### Official docs

- https://docs.seerr.dev/
- https://docs.seerr.dev/getting-started/docker/
- https://docs.seerr.dev/using-seerr/settings/mediaserver/
- https://docs.seerr.dev/using-seerr/settings/services/
- https://docs.seerr.dev/using-seerr/users/adding-users/

## 2. Maintainerr

**Role:** Automated retention and cleanup.

Maintainerr evaluates rules using Jellyfin viewing state, Seerr request information, and Radarr/Sonarr metadata. Matching items can enter a visible **Leaving Soon** collection for a grace period before Maintainerr tells Radarr or Sonarr to remove/unmonitor them.

### Setup

1. Deploy Maintainerr with Docker/Compose and persist `/opt/data`.
2. Open the web UI on port `6246`.
3. Connect Jellyfin using a Jellyfin API key.
4. Connect Seerr using its API key.
5. Connect Radarr and Sonarr using their API keys.
6. Create conservative retention rules and a grace period before deletion.

A direct media-library mount is not required for normal Radarr/Sonarr-managed cleanup; add one only if later using Maintainerr's leftover-folder cleanup features.

### Initial retention policy

```text
Watched requested media
→ eligible after ~45–60 days without use

Requested but never watched
→ eligible after ~90 days

Recently watched / actively used
→ protected

Cleanup candidate
→ "Leaving Soon"
→ 14-day grace period
→ delete through Radarr/Sonarr
```

Tune the values after observing actual SSD usage.

### Access / security

Maintainerr currently has no built-in login. Keep its management UI reachable only on the LAN/Tailscale network unless an authenticated reverse proxy is deliberately added later.

### Official docs

- https://docs.maintainerr.info/installation/
- https://docs.maintainerr.info/configuration/
- https://docs.maintainerr.info/rules/

## 3. Integration Order

1. **Deploy Seerr** and verify Jellyfin user integration plus movie/TV requests into Radarr/Sonarr.
2. **Deploy Maintainerr** and verify Jellyfin, Seerr, Radarr, and Sonarr connections.
3. **Create a non-destructive test retention rule** and inspect its matches.
4. **Enable a Leaving Soon collection** with a generous grace period.
5. **Enable deletion only after validating the rule output** and confirming removal flows through Radarr/Sonarr correctly.

## Desired Result

```text
Seerr
= what users want

Radarr / Sonarr
= acquisition and authoritative media management

Transmission
= downloading

Jellyfin
= playback and per-user viewing state

Maintainerr
= retention and cleanup policy
```

The goal is a complete media lifecycle with minimal manual SSD management and no custom scripts unless a real gap appears.
