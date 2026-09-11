# Sonarr

**Status:** PROPOSED — see [status legend](../../design-notes/README.md#status-legend);
[compose.yaml](compose.yaml) below and enabled in [services/compose.yaml](../compose.yaml)
now that the SSD is attached and `/mnt/library` is mounted, but not yet run.

## Selected implementation

`linuxserver/sonarr` (see [compose.yaml](compose.yaml)), the same pattern as
[Radarr](../radarr/README.md): config at `/var/lib/overmind/sonarr/config`
(works today), `/tv` blocked on the SSD, `/downloads` mounted read-only from
the same host path Transmission uses so no remote-path-mapping is needed and
Sonarr can only copy promoted files out, never touch Transmission's seeding
data.

**Download client setup** (in Sonarr's WebUI, not stored in compose): Host
`gluetun`, Port `9091` — Transmission has no network/hostname of its own (see
[pia](../pia/README.md)). Credentials are whatever was set in Transmission's
`settings.json`.

Automatic imports must not bypass the [ingestion gate](../ingestion/README.md).
Begin with copy-and-verify imports; enable hardlinks only after testing that
Sonarr, Transmission, and the filesystem actually share a compatible mount
view — separate bind mounts can silently prevent linking even on one SSD.
