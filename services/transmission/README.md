# Transmission

**Status:** PROPOSED — see [status legend](../../design-notes/README.md#status-legend);
selected implementation below, no deployment verified yet.

## Selected implementation

`linuxserver/transmission` (see [compose.yaml](compose.yaml)), attached to the
[gluetun](../pia/README.md) container via `network_mode: service:gluetun` — it
has no network of its own, so all traffic is bound to the PIA tunnel by
construction. [settings.example.json](settings.example.json) is a non-deployable
example; copy to `settings.json` (git-ignored) before first run and check it
against the actual image version.

Two settings exist specifically because this runs in a container reachable
only through Tailscale, not the previously-assumed loopback binding:

- `rpc-bind-address: 0.0.0.0` — a process bound to `127.0.0.1` inside a
  container is unreachable through a published port at all.
- `rpc-whitelist-enabled` / `rpc-host-whitelist-enabled: false` — an IP/Host
  whitelist doesn't work meaningfully behind Docker networking, and connecting
  by the Tailscale MagicDNS hostname (`overmind-01`) would otherwise be
  rejected by the default host whitelist. `rpc-authentication-required` plus
  the facts that this box is reachable only over Tailscale and never
  port-forwarded are the actual boundary here.
- `peer-port` is pinned to `51413` explicitly, matching the port
  [gluetun publishes](../pia/compose.yaml) for this container — don't rely on
  it being Transmission's undeclared default.

`rpc-username`/`rpc-password` are the WebUI/RPC login, unrelated to the `austin`
Linux account. Set both to real values in `settings.json` **before** the first
start: Transmission hashes a plaintext `rpc-password` on load and rewrites the
file, so an edit made while the daemon is already running can be overwritten
by its own state write-back.

## Storage

`TRANSMISSION_DOWNLOAD_ROOT` in [.env.example](.env.example) points at
`/mnt/downloads` — bind-mounted from the physical disk the same way
`/mnt/substrate`/`/mnt/library` are (see
[storage](../../design-notes/storage-layout.md)). No service references the
physical disk path directly, including this one.

Once a download completes and is seeding-safe, it becomes an ordinary
`media/<type>` Inbox arrival for the [ingestion](../ingestion/README.md)
workflow to pick up — see [storage](../../design-notes/storage-layout.md) for
why there's no separate `torrents/` Inbox root. Retain download data until
both import verification and seeding policy allow removal.

`TRANSMISSION_ROMSETS_STAGING_ROOT` (added 2026-09-20) mounts the romset
Inbox (`ROMSETS_INBOX` in `paths.env.example`) directly into the container
at `/romsets-staging`, so a romset torrent's **per-torrent destination** can
be set to `/romsets-staging` in the WebUI at add-time, landing it straight
in the real staging path instead of the default `/downloads` plus a manual
copy step. This doesn't change default behavior — the global download
directory is still `/downloads`; this only makes `/romsets-staging` a valid
destination choice when adding a torrent.

## Settings persist only through a config directory

`/config` is the directory `TRANSMISSION_CONFIG_ROOT`
(`/var/lib/overmind/transmission/config`). Until 2026-10-28 compose mounted
`settings.json` as a single file, and the container's state lived in an
unnamed Docker volume. Transmission saves settings by writing
`settings.json.tmp.*` and renaming it over `settings.json`, which Docker
refuses on a file bind mount. Every save failed: 11 abandoned temp files from
2026-09-21 on. So anything changed through the WebUI or RPC, including by the
Arr apps, was lost at the next restart.

- **Change settings through the WebUI or RPC** (`session-set`). They're saved
  when Transmission shuts down, so a restart keeps them.
- **Edit `settings.json` by hand only while Transmission is stopped.** A
  running daemon overwrites the file with its own state on exit.
- **Key names differ between the file and RPC:** the file uses
  `ratio-limit`/`ratio-limit-enabled`, while RPC uses
  `seedRatioLimit`/`seedRatioLimited`. A wrong name in the file is silently
  ignored.

## Seeding policy and Arr cleanup

From 2026-10-28, torrents stop seeding at a **1.25 ratio** or after **24 hours
with no peer activity** (`ratio-limit` and `idle-seeding-limit` in
[settings.example.json](settings.example.json)). Radarr's and Sonarr's
Transmission download clients have **Remove Completed** on, so they delete a
torrent and its download data once it has stopped seeding and been imported.
A release they couldn't import, such as an archive, stays queued in the Arr
app for a person to resolve.

## RPC login

`rpc-authentication-required` is on. Radarr and Sonarr connect to
`gluetun:9091` with the RPC username and password set on their download
client.

To change the password:

1. Change it in the WebUI (or RPC `session-set`), not in the file of a
   running daemon. It's saved on shutdown and hashed when loaded.
2. Update it in Radarr and Sonarr (Settings → Download Clients), and run their
   **Test** there.

## Known issues (open)

- **The RPC port is published on every host address.** gluetun publishes
  `9091` on `0.0.0.0`, so the WebUI and RPC are reachable from the home LAN as
  well as the tailnet, against this README's Tailscale-only intent. The login
  is the only barrier.
  - Fix option: publish it on Overmind's Tailscale address only.
  - The Arr apps are unaffected either way: they reach `gluetun:9091` over
    the Docker network.
- **No inbound peer connections.**
  - gluetun runs PIA with `VPN_PORT_FORWARDING=off`, so nothing can connect
    in. `51413` published on the host doesn't reach the tunnel.
  - Transmission can upload only to peers it reaches itself. Seeding is slow,
    and many torrents will end at the 24-hour idle limit before reaching
    1.25.
  - Its own port mapping (`port-forwarding-enabled`, UPnP/NAT-PMP) looks for
    a router inside the tunnel and can never succeed. That's why the log
    shows a "Not forwarded" ↔ "Starting" line every 8 s.
  - A fix means PIA port forwarding, which reportedly isn't offered on US
    servers (this runs in Chicago; to confirm). That means a non-US region,
    plus gluetun's port-forwarding hook writing the assigned port into
    Transmission's `peer-port`.
  - Undecided (2026-10-28).

## Still to verify before unattended use

Confirm the [PIA/gluetun boundary](../pia/README.md) actually fails closed.

- **Resume state across a restart:** verified when `/config` moved to a
  directory (2026-10-28).
- **Restart ordering:** a gluetun restart leaves Transmission without a
  network. `overmind-svc restart gluetun` restarts Transmission afterwards;
  compose's own `up` orders them by `depends_on`.
