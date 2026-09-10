# Radarr

**Status:** PROPOSED — see [status legend](../../design-notes/README.md#status-legend);
[compose.yaml](compose.yaml) below, blocked from running by the missing SSD.

## Selected implementation

`linuxserver/radarr` (see [compose.yaml](compose.yaml)). Config lives at
`/var/lib/overmind/radarr/config` and works today without the SSD; `/movies`
does not, see below.

`/downloads` is mounted **read-only**, pointed at the same host directory as
[Transmission's](../transmission/README.md) `TRANSMISSION_DOWNLOAD_ROOT`, at
the same container path Transmission itself uses. Both containers agreeing on
the literal path means no remote-path-mapping configuration is needed, and the
read-only mount means Radarr can only copy a promoted file out to `/movies`,
never mutate or remove Transmission's seeding data directly — begin with
copy-and-verify imports; enable hardlinks only after testing that Radarr,
Transmission, and the underlying filesystem actually share a compatible mount
view, since separate bind mounts can silently prevent linking even when both
are backed by the same SSD.

**Download client setup** (in Radarr's WebUI, not stored in compose): Host
`gluetun`, Port `9091` — Transmission has no network/hostname of its own (see
[pia](../pia/README.md)), so the container to reach is gluetun's, using its
published port. Credentials are whatever was set in Transmission's
`settings.json`.

Automatic imports must not bypass the [ingestion gate](../ingestion/README.md).

## Blocked until the SSD arrives

`MOVIES_ROOT` in [.env.example](.env.example) points at
`/mnt/library/movies`, which doesn't exist yet — don't bring this container up
until Library is actually mounted there. See
[storage](../../design-notes/storage-layout.md).
