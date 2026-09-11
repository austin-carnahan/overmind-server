# Bazarr

**Status:** PROPOSED — see [status legend](../../design-notes/README.md#status-legend);
[compose.yaml](compose.yaml) below and enabled in [services/compose.yaml](../compose.yaml)
now that the SSD is attached and `/mnt/library` is mounted, but not yet run.

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
