# Romset validation and promotion

**Status:** PROPOSED — see [status legend](../../../design-notes/README.md#status-legend).
One validated tier, not masters/curated — see below. See the
[ROM & emulator design brief](../../../design-notes/overmind_rom_emulator_design_brief.md)
and [Fire TV client doc](../../../runbooks/clients/fire-tv.md) for the full
pipeline this fits into. Historical curation lessons are retained below.

1. Acquisition: [ROMarr](https://github.com/BlizzHacker/romarr) (Prowlarr-backed
   search/scoring/grab) writes to staging — `/var/spool/overmind/media/romsets/<system>` —
   not directly to the canonical library. Manual arrivals land in the same
   staging path.
2. Keep unverified material quarantined; scan and inspect archive contents/types.
3. Validate against authoritative DATs, then curate with Igir. Be aggressive
   about ingestion-time cleanup — discard anything that isn't a DAT-matched
   ROM (NFOs, scans, samples, non-matching alt dumps) rather than archiving it.
4. Track filename changes affecting saves.
5. Promote reviewed output to `/mnt/library/romsets/<system>`.
6. Refresh clients/artwork after naming stabilizes — RetroArch's built-in
   thumbnail downloader, not a separate scraper, per the standard naming Igir
   already produces (see [scraper notes](../../../runbooks/romsets/scraper.md)).

One tier: no separate preserved-original archive. DAT-checksum validation at
ingestion is the only safety net — a destructive Igir `move`/`clean` run has
no fallback copy to recover from (AGENTS.md rule 3), which is why backup
coverage for this library matters once it holds anything you'd mind losing.
Provisionally keep live saves at emulator defaults, with Library exports as
needed; the user's save placement preference is pending. Unknown hashes and
suspicious content need review. See [Igir lessons](../../../runbooks/romsets/igir.md).
