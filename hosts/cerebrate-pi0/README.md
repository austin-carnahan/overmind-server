# cerebrate-pi0

**Status:** PARTIAL — see [status legend](../../design-notes/README.md#status-legend);
base OS/hardware inspected, AdGuard Home verified running and serving
`home.arpa` DNS rewrites (see
[home DNS + reverse-proxy plan](../../design-notes/2026-09-15-home-dns-reverse-proxy-plan.md)).
Caddy reverse proxy not yet deployed as of this writing.

| Item | Value |
| --- | --- |
| Machine | Raspberry Pi Zero 2 W, Rev 1.0 (aarch64) |
| OS | Debian GNU/Linux 13 "trixie", kernel `6.18.39+rpt-rpi-v8` |
| RAM | 512 MB total (constrained — factor this into anything else considered for this host) |
| Storage | 59.5 GB microSD (`mmcblk0`: 512 MB `/boot/firmware`, 58 GB `/`, 5.7 GB used) |
| Network interface | Wired (`eth0`), reserved LAN address `192.168.68.59/22` |

"Cerebrate" is a fleet/class name for small auxiliary compute nodes, not a
single machine — see the naming-convention section of the DNS plan linked
above. `cerebrate-pi0` is the first and, as of this writing, only member.

## Verified access

- Unix account `austin` exists and is used for interactive access; it's the
  only non-system account (UID 1000).
- `austin` has **passwordless `sudo` (`NOPASSWD: ALL`)** — a real deviation
  from `overmind-01`'s "stop and ask before anything needing `sudo`"
  handling. That policy is still honored deliberately when working on this
  host (mutating commands are still called out and confirmed before
  running), but nothing technical enforces it here the way it's enforced by
  needing a password on Overmind.
- Tailscale is enrolled (hostname `cerebrate-pi0`, tailnet IP
  `100.64.153.104`); `home.arpa` is configured as a Tailscale split-DNS
  domain pointed at this host, and it advertises the `192.168.68.0/22` LAN
  subnet as a Tailscale subnet router. See
  [networking](../../design-notes/networking.md) and the DNS plan.
- Interactive SSH uses plain OpenSSH with a forwarded personal key, same
  convention as `overmind-01`.
- No `ufw` installed (not just inactive — the package isn't present).
- No Docker — AdGuard Home runs natively (systemd-managed binary at
  `/opt/AdGuardHome/AdGuardHome`, version `v0.107.79`), and that's the
  intended pattern for anything else added to this host too, given the RAM
  constraint: prefer native binaries over container runtime overhead.
- AdGuard Home's admin UI listens on `:3000` (not `:80`) — confirmed via
  `ss -tlnp`, nothing else listens on `80`/`443`, so a future Caddy install
  doesn't need to relocate anything first.
- DNS rewrites are managed from the `overmind-server` repo, not AdGuard's
  UI directly — see `hosts/dns-rewrites.yaml` and
  `scripts/sync-dns-rewrites`.

## Intended role

DNS/network-management appliance for the home network (AdGuard Home) plus,
per the home DNS plan, a host-local Caddy reverse proxy for
`adguard.home.arpa` specifically — Cerebrate proxies only what Cerebrate
hosts, never anything running on Overmind. Given the 512 MB RAM ceiling,
this host should stay narrowly scoped to DNS/network-management duties
rather than accumulating unrelated services.
