# Romset validation and promotion

**Status:** PROPOSED — see [status legend](../../../design-notes/README.md#status-legend).
Historical curation lessons are retained below.

1. Place arrivals under `/var/spool/overmind/media/romsets/<system>`.
2. Keep unverified material quarantined; scan and inspect archive contents/types.
3. Validate against authoritative DATs where available, then curate with Igir.
4. Preserve original masters and track filename changes affecting saves.
5. Promote reviewed output to `/mnt/library/romsets/curated/<system>`.
6. Refresh clients/artwork after naming stabilizes.

Use `/mnt/library/romsets/masters` for preserved sources. Provisionally keep live
saves at emulator defaults, with Library exports as needed; the user's save
placement preference is pending. Unknown hashes and suspicious content need review; do not delete
or rewrite the master collection. See [Igir lessons](../../../runbooks/romsets/igir.md).
