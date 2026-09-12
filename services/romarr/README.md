# ROMarr

**Status:** PROPOSED — see [status legend](../../design-notes/README.md#status-legend);
[compose.yaml](compose.yaml) below, not yet deployed. Part of the
[ROM & emulator design brief](../../design-notes/overmind_rom_emulator_design_brief.md).

## Selected implementation

[BlizzHacker/romarr](https://github.com/BlizzHacker/romarr) — verified real
and active before adopting it: 160 commits, recent activity, used in
production against a 166,578-game library per its own README. Transmission
support specifically is documented as "high confidence — proven against live
daemons" (9/9 live tests against real Transmission 4.1).

Pinned `0.8.0` + digest — resolve a fresh digest before actually deploying,
this project publishes frequently. Port `6868` deliberately (not `7878`,
which is Radarr's — the project explicitly avoids that collision).

## Staging, not the canonical library

`ROMARR_STAGING_ROOT` in [.env.example](.env.example) points at
`/var/spool/overmind/media/romsets` — the Inbox staging path, **not**
`/mnt/library/romsets`. ROMarr's own docs call this its "library root" and
will happily write finished imports directly there in "folder" mode, but per
the design brief this repo deliberately keeps Igir as the actual gate:
ROMarr acquires and does its own DAT verification at import time (verified /
bad-dump / unknown), Igir handles 1G1R selection, canonical renaming, and
aggressive cleanup across what's in staging before anything is promoted to
the one-tier library (AGENTS.md rule 3 — no separate master archive to fall
back on if that gate is skipped).

## Setup (in ROMarr's own WebUI, not stored in compose)

- **Download client**: Transmission, host `gluetun`, port `9091` — same
  reasoning as [Radarr](../radarr/README.md)/[Sonarr](../sonarr/README.md):
  Transmission has no network identity of its own.
- **Indexer**: Prowlarr (already running) — ROMarr can query it directly as
  a Torznab-compatible source; confirm in ROMarr's Settings whether that
  needs registering there as well as (or instead of) a Prowlarr Application
  entry.
- **Library**: "folder" mode, pointed at `/roms` (this container's staging
  mount) — no RomM/Gaseous/Retrom needed, matching the earlier decision.

Test against one small, static-console collection first (e.g. a SNES set)
before pointing it at a whole library, per the design brief's own suggested
build order.
