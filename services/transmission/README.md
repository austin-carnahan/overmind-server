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

## Storage: temporary until the SSD arrives

`TRANSMISSION_DOWNLOAD_ROOT` in [.env.example](.env.example) currently points
at a microSD-backed directory — there is no SSD attached yet. Keep this to
small/test downloads only; the microSD has limited capacity and write
endurance and is not where sustained downloading should happen. Once the SSD
is attached, update `TRANSMISSION_DOWNLOAD_ROOT` and treat any temporary
downloads as disposable.

Once a download completes and is seeding-safe, it becomes an ordinary
`media/<type>` Inbox arrival for the [ingestion](../ingestion/README.md)
workflow to pick up — see [storage](../../design-notes/storage-layout.md) for
why there's no separate `torrents/` Inbox root. Retain download data until
both import verification and seeding policy allow removal.

## Still to verify before unattended use

Confirm the [PIA/gluetun boundary](../pia/README.md) actually fails closed,
that resume/session state under `/config` survives a restart, and that
restart ordering brings gluetun up healthy before Transmission starts.
