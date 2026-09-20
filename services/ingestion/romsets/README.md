# Romset validation and promotion

**Status:** PROPOSED — see [status legend](../../../design-notes/README.md#status-legend).
Two tiers, not one — see below (revised 2026-09-20; the original one-tier
decision is superseded). See the
[ROM & emulator design brief](../../../design-notes/overmind_rom_emulator_design_brief.md)
and [Fire TV client doc](../../../runbooks/clients/fire-tv.md) for the full
pipeline this fits into. Historical curation lessons are retained below.

1. Acquisition: [ROMarr](https://github.com/BlizzHacker/romarr) (Prowlarr-backed
   search/scoring/grab) writes to staging — `/var/spool/overmind/media/romsets/<system>` —
   not directly to either library tier. Manual arrivals land in the same
   staging path.
2. Keep unverified material quarantined; scan and inspect archive contents/types.
3. Validate against authoritative DATs with Igir (checksum match, discard
   anything that isn't a DAT-matched ROM — NFOs, scans, samples, non-matching
   alt dumps), then apply a first, broad curation pass (1G1R, language/region
   filter) and promote to the **archive tier**:
   `/mnt/library/romsets-archive/<system>`. This tier is kept indefinitely —
   it's what lets acquisition + first-pass Igir validation not need repeating
   — but it is not exposed to any client.
4. Apply a second, much stricter curation pass (see
   [curation strategies](#curation-strategies-archive--library), still being
   worked out) to narrow the archive down to a small browsable/playable set,
   and promote that to the **library tier**: `/mnt/library/romsets/<system>`.
   This is the only tier exposed to SMB/R-Shop/clients.
5. Track filename changes affecting saves.
6. Refresh clients/artwork after naming stabilizes — RetroArch's built-in
   thumbnail downloader, not a separate scraper, per the standard naming Igir
   already produces (see [scraper notes](../../../runbooks/romsets/scraper.md)).

## Curation strategies (archive → library)

Decided — see [romset-curation-pipeline.md](../../../design-notes/romset-curation-pipeline.md)
for the full design, and the "Curation strategies" section of
[Igir lessons](../../../runbooks/romsets/igir.md#curation-strategies-archive--library)
for the short version. Summary: ScreenScraper identifies and rates the full
archive tier; the top ~150-200 by that rating become candidates; only
candidates get a second IGDB rating; a Bayesian blend of the two picks the
final ~100-title library tier.

Two romset tiers now exist (see AGENTS.md rule 3): the archive tier is what
makes destructive Igir runs against the library tier recoverable without
repeating acquisition, but the archive tier itself has no further backup —
re-acquisition, not a preserved-original copy, is the fallback if it's
damaged. DAT-checksum validation at promotion into the archive is still the
primary safety net; dry-run before any destructive Igir run against either
tier. Provisionally keep live saves at emulator defaults, with Library
exports as needed; the user's save placement preference is pending. Unknown
hashes and suspicious content need review.
