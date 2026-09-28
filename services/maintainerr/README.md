# Maintainerr

**Status:** PARTIAL — Maintainerr 3.13.0 is deployed on `overmind-01` with
its private state at `/var/lib/overmind/maintainerr/data`. The retention policy
is defined in [retention-policy-v1.json](retention-policy-v1.json) and applied
from the deployed checkout. See [status legend](../../design-notes/README.md#status-legend)
and the [Seerr + Maintainerr design brief](../../design-notes/overmind_seerr_maintainerr_setup_brief.md).

## Selected implementation

[Maintainerr/Maintainerr](https://github.com/Maintainerr/Maintainerr) —
verified real before adopting it: 2,200+ stars, described by its own README
as "looks and smells like Seerr, does the opposite" (a companion project, not
affiliated infrastructure), confirmed `linux/amd64` + `arm64`.

Pinned `3.13.0` + digest. Before upgrading, test the image and resolve a fresh
digest deliberately.
Data lives at `/var/lib/overmind/maintainerr/data`, SSD-backed. Runs as
`user: 1000:1000` directly (this image's own convention, not PUID/PGID env
vars) — matches `austin`'s UID.

Automated retention/cleanup — evaluates rules using Jellyfin viewing state,
Seerr request state, and Radarr/Sonarr metadata; matches enter a visible
"Leaving Soon" collection for a grace period before Maintainerr tells
Radarr/Sonarr to remove or unmonitor them. Never in the playback or download
path — if it's offline, everything else keeps working normally.

## No built-in login — a real, accepted gap, not an oversight

Maintainerr has no application-level authentication at all. Per the design
brief, the accepted boundary for now is Tailscale-only reachability (no
router port-forward) — the same network posture as everything else here, but
without the extra app-auth layer every *other* service in this project has.
Revisit with an authenticated reverse proxy only if that stops being
sufficient — don't add one preemptively.

## Setup and policy application

- **Connect** Jellyfin, [Seerr](../seerr/README.md), Radarr, and Sonarr, each
  with their own API key. Use a **separate Jellyfin API key** from Seerr's,
  not a shared one.
- Create service connections using separate scoped API keys. They remain only
  in Maintainerr's private state, never this repository.
- Apply the committed policy from the host checkout:

  ```sh
  /opt/overmind/scripts/apply-maintainerr-retention
  /opt/overmind/scripts/apply-maintainerr-retention --apply
  ```

  The first command resolves the policy without changing the service. The
  second upserts its two rule groups. It talks only to Maintainerr's loopback
  API by default and does not print service credentials.

### Retention policy v1

```text
Movie: watched at least once + inactive for 30 days + no Jellyfin favorites
  → Leaving Soon — Movies for 14 days → whole-movie delete through Radarr

Show: ended + unmonitored + fully watched by at least one Jellyfin user
      + inactive for 30 days + no Jellyfin favorites
  → Leaving Soon — TV for 14 days → whole-show delete through Sonarr
```

The Jellyfin heart is the normal keep-forever control: a favorite from any
Jellyfin profile prevents the title from entering either collection or being
deleted. Removing the favorite makes it eligible again only when every other
condition also matches. Manual Maintainerr exclusions remain available for
exceptions.

Both actions use Maintainerr's whole-title `Delete` action, so Radarr/Sonarr
remove the media, their record, and the title directory. A direct library mount
(commented out in [compose.yaml](compose.yaml)) is not required and must not be
added for this policy. Manually imported media is outside the policy because it
is not Arr-managed.
