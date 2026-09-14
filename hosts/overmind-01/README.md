# overmind-01

**Status:** PARTIAL — see [status legend](../../design-notes/README.md#status-legend);
base OS/hardware inspected, SSD attached/formatted/mounted, and the full media
pipeline (below) validated end to end — a real movie flowed through
Radarr → Transmission → Library → Jellyfin playback. Network addressing
(LAN/DHCP) and ROM/romset ingestion are still pending.

| Item | Value |
| --- | --- |
| Machine | Raspberry Pi 4 (Cortex-A72, 4 cores, aarch64) |
| OS | Ubuntu 26.04.1 LTS "Resolute Raccoon", kernel 7.0.0-1017-raspi |
| RAM | 7.6 GiB |
| OS storage | 128 GB microSD (`mmcblk0`: 512 MB `/boot/firmware`, 117 GB `/`, 4.2 GB used) |
| Attached storage | 2 TB SSD, SABRENT USB enclosure (JMicron JMS579 bridge), ext4, label `overmind-ssd` |
| Network interface | Wi-Fi (`wlan0` via netplan/`wpa_supplicant`); no Ethernet link observed |

Unverified: remaining accounts/groups beyond `root`/`austin`, and LAN
addressing/DHCP details.

## Known hardware issue: this specific USB enclosure needs a kernel quirk

The SSD's JMicron JMS579 bridge (USB `idVendor=152d, idProduct=a578`) crashes
the Pi 4's entire xHCI USB controller under sustained write load in UAS mode —
not a firmware-currency issue (VL805 EEPROM was already current when this was
first hit). The fix, already applied and required for this drive to work at
all on this host, is a `usb-storage` quirk forcing plain USB Mass Storage
instead of UAS for that one device, in
`/boot/firmware/current/cmdline.txt` (**not** the top-level
`/boot/firmware/cmdline.txt`, which Ubuntu's Raspberry Pi image does not
actually boot from):

```text
usb-storage.quirks=152d:a578:u
```

A rebuild of this host, or attaching this exact drive/enclosure to a
different Pi, needs this reapplied — it isn't optional tuning, the drive
reliably crashes the USB controller without it under real write load.

## Verified access

- Unix account `austin` exists and is used for interactive access.
- Tailscale is enrolled (hostname `overmind-01`, MagicDNS on, node key expiry
  disabled); see [networking](../../design-notes/networking.md).
- Interactive SSH uses plain OpenSSH with a forwarded personal key, including
  through VS Code Remote-SSH; see
  [remote project work](../../runbooks/clients/remote-work.md) for setup.
- `ufw` is inactive.
- Docker is installed; `gluetun` (PIA), `transmission`, `paperclip`,
  `paperclip-db`, `jellyfin`, `radarr`, `sonarr`, `bazarr`, `prowlarr`, and
  `cloudflare-solver` are all running via
  [services/compose.yaml](../../services/compose.yaml). The movie pipeline
  (Prowlarr → Radarr → Transmission → Library → Jellyfin) is verified
  working end to end, not just deployed.
- Login-capable accounts: `root`, `austin`.
- SSD mounted (ext4, `noatime`, `nofail`) at `/mnt/disks/ssd1` — numbered
  rather than matching the filesystem's own `overmind-ssd` label, since a
  number scales to a second/third disk more simply than a label match would.
  Physical mounts live isolated under `/mnt/disks/`, never referenced
  directly by any service. `/mnt/substrate`, `/mnt/library`, `/mnt/downloads`,
  and `/var/lib/overmind` are bind-mounted from subdirectories of it — see
  [storage](../../design-notes/storage-layout.md). Revised 2026-09-14 from an
  earlier flat `/mnt/ssd` layout that collided physical and logical paths at
  the same level and didn't scale to a second disk; no service config needed
  to change except `TRANSMISSION_DOWNLOAD_ROOT`, which gained a proper bind
  mount instead of referencing the disk directly. Paperclip's database and
  app state are live on it.

## Intended first roles

Private remote project work and modest media access, supported by tested storage
and recovery. Library has real content (movies, verified playable); Substrate
is mounted but still empty — no project work moved there yet. Do not assume
RetroPie, a GUI, a local display, or hardware acceleration. DNS on another
device is optional.

[paths.env.example](paths.env.example) records the logical paths; SSD bindings
for them are live (see above). Per-service ownership beyond `austin` for
everything, and application-consistent backup/restore, are still open —
see [rebuild-overmind-01](../../runbooks/rebuild-overmind-01.md) and
[backup and restore](../../runbooks/backup-restore.md).
Keep private host details and secret values in ignored local files/stores.
