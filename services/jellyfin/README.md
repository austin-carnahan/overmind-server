# Jellyfin

**Status:** PROPOSED — see [status legend](../../design-notes/README.md#status-legend);
[compose.yaml](compose.yaml) below, blocked from running by the missing SSD.

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

## Blocked until the SSD arrives

`MOVIES_ROOT`/`TV_ROOT` in [.env.example](.env.example) point at
`/mnt/library/...`, which doesn't exist yet. Don't bring this container up
until Library is actually mounted there — Docker will otherwise silently
create empty directories on the microSD at those paths. See
[storage](../../design-notes/storage-layout.md).

## Still to verify before real use

Confirm accounts/watch-history database survives a container restart at its
`/config` path, back it up per its supported procedure, and decide whether
Kodi remains a client alongside or instead of Jellyfin's own apps.
