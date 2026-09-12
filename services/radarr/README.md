# Radarr

**Status:** PARTIAL — see [status legend](../../design-notes/README.md#status-legend);
deployed and verified end to end: search via [Prowlarr](../prowlarr/README.md),
download via Transmission, import into `/movies`, playback in Jellyfin — all
confirmed working. Set the Quality Profile deliberately (uncheck Remux/2160p
unless you actually want 40-80GB+ files) rather than trusting the default.

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
