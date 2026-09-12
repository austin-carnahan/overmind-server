# Syncthing (server side)

**Status:** PROPOSED — see [status legend](../../design-notes/README.md#status-legend);
[compose.yaml](compose.yaml) below, built but deliberately commented out of
[services/compose.yaml](../compose.yaml)'s active stack — nothing to sync to
until a Fire TV exists to pair with. This is the server-side
hub; the Fire TV runs
[Syncthing-Fork](https://github.com/Catfriend1/syncthing-android) (a
different, Android-specific client build of the same protocol) — see
[Fire TV client doc](../../runbooks/clients/fire-tv.md).

## Selected implementation

Official `syncthing/syncthing` image, confirmed `linux/amd64`/`arm64`/`arm`.

**`network_mode: host`, deliberately** — verified against Syncthing's own
Docker documentation: it explicitly recommends host networking because
Docker's bridge network hides real LAN addresses from Syncthing's own
discovery/NAT traversal, breaking local discovery and degrading transfer
rates otherwise. Same category of exception as Transmission's
`network_mode: service:gluetun` — a deliberate, documented departure from
the shared-network pattern, not an oversight.

Config lives at `/var/lib/overmind/syncthing/config` (SSD-backed); the
actual synced data is `/mnt/library/saves`, the per-user save namespace
(`/mnt/library/saves/<user>/`) decided in
[storage-layout.md](../../design-notes/storage-layout.md).

## Setup (in Syncthing's own WebUI, not stored in compose)

- Pair each user's Fire TV (running Syncthing-Fork) as a device.
- Share the `saves/<user>/` folder with only that user's own device(s) — a
  user's saves shouldn't be shared to a different user's device.
- Syncthing's GUI listens on `0.0.0.0:8384` by default with no
  authentication set up out of the box — set a GUI password on first login;
  reachability is Tailscale/LAN-only (no port-forward) but that's not a
  substitute for the app's own auth, same reasoning as everywhere else in
  this repo.
