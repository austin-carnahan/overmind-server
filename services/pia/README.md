# PIA / outbound privacy

**Status:** PROPOSED — see [status legend](../../design-notes/README.md#status-legend);
selected implementation below, no deployment verified yet.

## Selected implementation

[Gluetun](https://github.com/qdm12/gluetun) as a VPN-sidecar container
(`compose.yaml`), configured for PIA over **OpenVPN** — gluetun has no native
WireGuard support for PIA, only OpenVPN with `OPENVPN_USER`/`OPENVPN_PASSWORD`.
Chosen over an all-in-one image (e.g. `haugene/transmission-openvpn`) because
Gluetun keeps the VPN concern in its own container, actively maintained,
reusable by any future service that needs the same egress boundary — not
welded to Transmission specifically.

Gluetun's firewall rules block all traffic if the tunnel drops, so this is a
fail-closed kill switch by construction, not something bolted on afterward.
Any container attached via `network_mode: service:gluetun` (see
[transmission](../transmission/README.md)) inherits that boundary and has no
other network path.

Credentials: copy [.env.example](.env.example) to `.env` (git-ignored) and
fill in the real PIA username/password. Never commit the real file.

## Still to verify before unattended use

Routed public address, DNS behavior inside the tunnel, actual kill-switch
behavior (kill the tunnel, confirm Transmission traffic stops rather than
falling back to the host's normal interface), restart ordering, and that host
administration (SSH over Tailscale) keeps working independently of this
container. Tailscale remote access and encrypted DNS do not replace this
egress boundary — they are separate concerns.
