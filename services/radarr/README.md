# Radarr

Status: planned library organizer; no deployment verified.

Organize reviewed content into `/mnt/library/movies`. Preserve canonical
naming, subtitles, and seeding requirements. Begin with copy-and-verify imports.
Enable hardlinks only with a tested compatible mount view inside the importer;
separate bind mounts can prevent linking even when backed by the same SSD.

Automatic imports must not bypass the [ingestion gate](../ingestion/README.md).
Keep private database/configuration state at supported service paths outside
Substrate, SSD-backed as useful. Before deployment select method/version,
credentials, permissions, mounts, health checks, backup/restore, and rollback.
