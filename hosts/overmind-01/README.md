# overmind-01

**Status:** PARTIAL — see [status legend](../../design-notes/README.md#status-legend);
base OS/hardware inspected below; storage, network addressing, and services
beyond the base image are pending.

| Item | Value |
| --- | --- |
| Machine | Raspberry Pi 4 (Cortex-A72, 4 cores, aarch64) |
| OS | Ubuntu 26.04.1 LTS "Resolute Raccoon", kernel 7.0.0-1017-raspi |
| RAM | 7.6 GiB |
| OS storage | 128 GB microSD (`mmcblk0`: 512 MB `/boot/firmware`, 117 GB `/`, 4.2 GB used) |
| Attached storage | 2 TB SSD (planned; not yet acquired — no second block device present) |
| Network interface | Wi-Fi (`wlan0` via netplan/`wpa_supplicant`); no Ethernet link observed |

Unverified: SSD identity/filesystem/content once attached, current mounts
beyond the base image, remaining accounts/groups beyond `root`/`austin`, and
LAN addressing/DHCP details.

## Verified access

- Unix account `austin` exists and is used for interactive access.
- Tailscale is enrolled (hostname `overmind-01`, MagicDNS on, node key expiry
  disabled); see [networking](../../design-notes/networking.md).
- Interactive SSH uses plain OpenSSH with a forwarded personal key, including
  through VS Code Remote-SSH; see
  [remote project work](../../runbooks/clients/remote-work.md) for setup.
- `ufw` is inactive.
- Only base-image services are running: `tailscaled`, `ssh`, `chrony`, `cron`,
  `unattended-upgrades`, `ModemManager`, `fwupd`, `snapd`. No application
  services are installed yet.
- Login-capable accounts: `root`, `austin`.

## Intended first roles

Private remote project work and modest media access, supported by tested storage
and recovery. Substrate and Library are separate optional attachments;
Inbox has its own verified backing and intake permissions. Do not assume RetroPie, a GUI,
a local display, or hardware acceleration. DNS on another device is optional.

[paths.env.example](paths.env.example) records proposed logical paths only. No
script automatically sources it and no installer creates those paths. Service
state locations must come from the selected application's supported deployment.

Before implementation, record read-only inspection, decide SSD bindings and
per-service ownership, then follow [rebuild-overmind-01](../../runbooks/rebuild-overmind-01.md).
Keep private host details and secret values in ignored local files/stores.
