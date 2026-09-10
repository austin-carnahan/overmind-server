# Ingest a movie or TV download

Status: manual proposed procedure; no daemon/automatic gate is implemented.

1. Finish the download in `/var/spool/overmind/torrents` behind verified egress.
2. Hold it in pending/quarantine state; scan and inspect types, archives, sidecars.
3. Probe the candidate with the helper under `services/ingestion/media`.
4. Review results and classify it before importing into `/mnt/library/movies`
   or `/mnt/library/tv` using the selected library manager.
5. Preserve subtitles and seeding requirements, then refresh the client library.

Copy and verify as the initial import method. Hardlinks require a tested common
filesystem/mount view, even when roots share one SSD. Remove intake copies only
after verifying the destination and satisfying seeding retention. A passed scan/probe
is one component of validation. Automatic library imports must not bypass it.
See [ingestion](../services/ingestion/README.md) for limitations and planned checks.
