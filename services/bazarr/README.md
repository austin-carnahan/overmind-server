# Bazarr

**Status:** PARTIAL — see [status legend](../../design-notes/README.md#status-legend);
deployed and connected to Radarr/Sonarr; a subtitle provider, Languages
Profile, and per-item assignment are configuration choices made directly in
its UI (see below), not committed here.

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

## Embedded subtitles

Settings → Subtitles → "Use Embedded Subtitles" (Performance/Optimization
section) — verified against Bazarr's own docs, not assumed. It doesn't
literally extract embedded tracks into standalone files; it lets Bazarr
recognize a subtitle already embedded in the file so it doesn't redundantly
download a duplicate external one. The related "Ignore Embedded PGS
Subtitles" option treats image-based PGS tracks as not counting, so Bazarr
fetches a real text-based SRT instead — worth enabling if you want
syncable/editable subtitles rather than just any subtitles.
