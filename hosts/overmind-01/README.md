# overmind-01

**Status:** PARTIAL — see [status legend](../../design-notes/README.md#status-legend);
base OS/hardware inspected, SSD attached/formatted/mounted, and PIA/Transmission/
Paperclip running below; network addressing (LAN/DHCP) and the remaining media
services are still pending.

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
- Docker is installed; `gluetun` (PIA), `transmission`, `paperclip`, and
  `paperclip-db` are running via [services/compose.yaml](../../services/compose.yaml).
  Jellyfin/Radarr/Sonarr/Bazarr are designed but not yet enabled.
- Login-capable accounts: `root`, `austin`.
- SSD mounted (ext4, `noatime`, `nofail`) at `/mnt/ssd`, with `/mnt/substrate`,
  `/mnt/library`, and `/var/lib/overmind` bind-mounted from subdirectories of
  it — see [storage](../../design-notes/storage-layout.md) for why the
  logical paths didn't need to change. Paperclip's database and app state are
  live on it.

## Intended first roles

Private remote project work and modest media access, supported by tested storage
and recovery. Substrate and Library are mounted but still empty — nothing has
been imported into them yet. Do not assume RetroPie, a GUI, a local display,
or hardware acceleration. DNS on another device is optional.

[paths.env.example](paths.env.example) records the logical paths; SSD bindings
for them are live (see above). Per-service ownership beyond `austin` for
everything, and application-consistent backup/restore, are still open —
see [rebuild-overmind-01](../../runbooks/rebuild-overmind-01.md) and
[backup and restore](../../runbooks/backup-restore.md).
Keep private host details and secret values in ignored local files/stores.
