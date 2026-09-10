# Bazarr

**Status:** PROPOSED — see [status legend](../../design-notes/README.md#status-legend);
[compose.yaml](compose.yaml) below, blocked from running by the missing SSD.

## Selected implementation

`linuxserver/bazarr` (see [compose.yaml](compose.yaml)). Config lives at
`/var/lib/overmind/bazarr/config` and works today without the SSD; `/movies`
and `/tv` do not (mounted read-write here, unlike Radarr/Sonarr's `/downloads`
mount — Bazarr writes subtitle files directly alongside the media it manages).

Connect it to Radarr/Sonarr via API key through Bazarr's own WebUI after first
start — provider credentials and those API keys are not stored in compose or
committed; keep them in whatever secret mechanism the eventual deployment uses.

Keep subtitle **downloading/matching** on, but leave any CPU-heavy automatic
**re-sync** (audio-based timing correction) off — `AGENTS.md` keeps expensive
subtitle synchronization off the Pi until deliberately tested; that's a future
mini-PC workload, not a default here.

## Blocked until the SSD arrives

`MOVIES_ROOT`/`TV_ROOT` in [.env.example](.env.example) point at
`/mnt/library/...`, which doesn't exist yet — don't bring this container up
until Library is actually mounted there. See
[storage](../../design-notes/storage-layout.md).
