# Add a ROM

Status: manual workflow; apply domain validation even for individual imports.
Two romset tiers now (revised 2026-09-20, supersedes the original one-tier
version of this runbook) — see AGENTS.md rule 3.

1. Put arrivals in `/var/spool/overmind/media/romsets/<system>` and keep unverified content
   quarantined while inspecting archives, types, malware, and DAT matches.
2. Curate verified ROMs with the [Igir workflow](romsets/igir.md): a first,
   broad pass (DAT-checksum match, 1G1R, language/region filter). Discard
   anything that isn't a DAT-matched ROM (NFOs, scans, samples, non-matching
   alt dumps) rather than keeping it in this pass.
3. Promote that broad-but-curated output into the **archive tier**:
   `/mnt/library/romsets-archive/<system>`. Kept indefinitely — this is what
   avoids repeating acquisition and first-pass validation later. Not exposed
   to any client.
4. Apply a second, stricter curation pass to narrow the archive down to a
   small browsable/playable set (see the "Curation strategies" section of
   [Igir lessons](romsets/igir.md) — still an open problem).
5. Never run destructive move/clean operations against either
   `/mnt/library/romsets-archive` or `/mnt/library/romsets` without a tested
   dry-run first — the archive tier makes the library tier recoverable
   without repeating acquisition, but the archive itself has no further
   backup; re-acquisition is the only fallback if it's damaged.
6. Preserve and map saves separately before changing canonical filenames.
7. Promote the strictly-curated output into the **library tier**:
   `/mnt/library/romsets/<system>` — the only tier exposed to
   SMB/R-Shop/clients.
8. Refresh playlists and scrape metadata only after canonical names stabilize.

Unknown or ambiguous matches require review. Provisionally keep live saves at the
emulator's default location and export copies to Library when needed; the user's
preference is pending. Document the actual paths and conflict handling before sync.
