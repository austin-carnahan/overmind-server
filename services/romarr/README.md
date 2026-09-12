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

## Configuration: env-seeded vs. WebUI-only

Verified against ROMarr's actual configuration reference — not every setting
works the way the other `*arr` apps do:

- **`LIBRARY_KIND`/`LIBRARY_PATH`** — set in `.env`, not the UI. **Required**:
  `LIBRARY_KIND` defaults to `romm`, not `folder` — left unset, ROMarr expects
  a RomM connection that doesn't exist. Set to `folder` + `/roms` (this
  container's staging mount) — no RomM/Gaseous/Retrom needed, matching the
  earlier decision.
- **`PROWLARR_URL`/`PROWLARR_API_KEY`** — also set in `.env` (get the key from
  Prowlarr's Settings → General). ROMarr queries Prowlarr directly as its own
  indexer source; Prowlarr's "Applications" sync (how Radarr/Sonarr connect)
  doesn't apply here — ROMarr isn't one of Prowlarr's built-in app types.
- **`DAT_PATH`** — set in `.env`, pointed at a directory holding *only*
  No-Intro/Redump DATs (pointing it at a ROM library instead hung the
  maintainer's own install for ten minutes on startup). DAT sourcing itself
  — where they come from, how they stay current — is still an open decision;
  the directory can stay empty until that's resolved.
- **Download client (Transmission)** — this one genuinely is WebUI-only:
  Settings → Download Clients → host `gluetun`, port `9091` — same reasoning
  as [Radarr](../radarr/README.md)/[Sonarr](../sonarr/README.md): Transmission
  has no network identity of its own. Transmission isn't one of ROMarr's three
  env-seeded clients (only qBittorrent/SABnzbd/NZBGet are).

Test against one small, static-console collection first (e.g. a SNES set)
before pointing it at a whole library, per the design brief's own suggested
build order.
