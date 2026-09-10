# Add a ROM

Status: manual workflow; apply domain validation even for individual imports.

1. Put arrivals in `/var/spool/overmind/media/romsets/<system>` and keep unverified content
   quarantined while inspecting archives, types, malware, and DAT matches.
2. Curate verified ROMs with the [Igir workflow](romsets/igir.md).
3. Preserve original sources under `/mnt/library/romsets/masters`; never run
   destructive move/clean operations against that collection.
4. Preserve and map saves separately before changing canonical filenames.
5. Promote reviewed output into `/mnt/library/romsets/curated/<system>`.
6. Refresh playlists and scrape metadata only after canonical names stabilize.

Unknown or ambiguous matches require review. Provisionally keep live saves at the
emulator's default location and export copies to Library when needed; the user's
preference is pending. Document the actual paths and conflict handling before sync.
