# Jellyfin

**Status:** PARTIAL — see [status legend](../../design-notes/README.md#status-legend);
deployed and verified: a movie imported by Radarr showed up and played back
successfully. Backup/restore of `/config` not yet tested.

## Selected implementation

Official `jellyfin/jellyfin` image (see [compose.yaml](compose.yaml)). Config
and cache land at `/var/lib/overmind/jellyfin/{config,cache}` — small and
low-write, so that part works today without the SSD. Movies/TV mount
**read-only**: Jellyfin serves the canonical Library, it doesn't own it, and a
read-only mount enforces that at the permission layer instead of just by
convention. No `/dev/dri` passthrough — direct-play only until Pi hardware
transcoding is deliberately tested (AGENTS.md keeps heavy transcoding off the
Pi by default).

WebUI on `8096`, reachable only over Tailscale like everything else on this
host — never port-forwarded.

## Still to verify before real use

Confirm accounts/watch-history database survives a container restart at its
`/config` path, back it up per its supported procedure, and decide whether
Kodi remains a client alongside or instead of Jellyfin's own apps.
