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
| Network interface | Wired (`eth0`), reserved LAN address `192.168.68.55/22`, DNS name `overmind-01.home.arpa`; Wi-Fi (`wlan0`) also has a reservation at `192.168.68.50/22` but is not the primary route (higher metric) and may be removed once eth0 is confirmed as the sole connection |

Unverified: remaining accounts/groups beyond `root`/`austin`.

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
- Login-capable accounts: `root`, `austin`, plus a scoped system account
  `pixel-tunnel` (`/usr/sbin/nologin`, no interactive shell) — exists only
  to terminate `cerebrate-pixel6`'s reverse SSH tunnel on
  `127.0.0.1:2206`; see
  [hosts/cerebrate-pixel6](../cerebrate-pixel6/README.md) and the
  [Pixel 6 inference node design notes](../../design-notes/2026-09-16-pixel6-inference-node.md)
  for the full credential shape and verification.
- `austin` also holds an independent `adb tcpip` session to
  `cerebrate-pixel6` (`192.168.68.60:5555`), separate from any Mac/USB
  tether — used to remotely relaunch the guest's Terminal app after a
  force-stop, with no physical touch to the phone. That session can drop
  (observed: Overmind's `adb` server lost it entirely, `adb devices`
  came back empty, while the phone itself stayed on Wi-Fi and the guest's
  `pixel-tunnel.service` kept running throughout — two independent
  connections, only one of which had failed). `pixel-adb-reconnect.timer`
  (`/etc/systemd/system/pixel-adb-reconnect.timer`, not committed as a
  live file, installed manually — see block below) runs `adb connect
  192.168.68.60:5555` every 30s as `austin`; the call is a ~20ms no-op
  when already connected, so this is cheap self-healing, not polling
  overhead. Deliberately narrow: it only reconnects an existing `adb
  tcpip` pairing, and does nothing if that pairing itself expires (which
  needs physical/Developer-settings re-pairing, same as before).

  ```ini
  # /etc/systemd/system/pixel-adb-reconnect.service
  [Unit]
  Description=Reconnect adb to cerebrate-pixel6 (self-heal for dropped adb tcpip sessions)
  After=network-online.target
  Wants=network-online.target

  [Service]
  Type=oneshot
  User=austin
  ExecStart=/usr/bin/adb connect 192.168.68.60:5555
  ```

  ```ini
  # /etc/systemd/system/pixel-adb-reconnect.timer
  [Unit]
  Description=Periodically reconnect adb to cerebrate-pixel6

  [Timer]
  OnBootSec=20s
  OnUnitActiveSec=30s
  AccuracySec=5s

  [Install]
  WantedBy=timers.target
  ```

- **`pixel-vm-watchdog.timer`** (added 2026-10-24) relaunches the Pixel's
  Debian VM if Android kills it. Prompted by a real outage: an Edge TPU
  compile exhausted the phone's memory and the low-memory killer took the
  Terminal app — the VM, MLServer and both reverse tunnels — for ~7 minutes
  until a manual relaunch ([lane notes](../../design-notes/Cerebrate%20Pixel%206%20%E2%80%94%20Segmentation%20and%20Labeling%20Lane.md)).
  Every 60s it probes MLServer through the tunnel; after 3 consecutive
  failures it asks the phone (over the same adb pairing) whether the VM
  process `crosvm` exists, and only if it doesn't, runs the documented
  relaunch (`am start ... .new2.ui.MainActivity`), at most once per 5
  minutes. A running-but-unreachable VM is left alone — that's the network
  case the tunnels already heal (see the Wi-Fi row above). Pause it with
  `sudo systemctl stop pixel-vm-watchdog.timer` (e.g. while deliberately
  stopping the VM). Installed manually, like the timer above:

  ```bash
  # /usr/local/bin/pixel-vm-watchdog
  #!/bin/bash
  # pixel-vm-watchdog -- relaunch cerebrate-pixel6's Debian VM if Android killed it.
  # Probes MLServer through its reverse tunnel; after THRESHOLD consecutive
  # failures, checks over adb whether the VM process (crosvm) exists, and only
  # if it doesn't, relaunches the Terminal app (the documented recovery). A VM
  # that is running but unreachable is a network problem the tunnels heal
  # themselves; it is left alone. COOLDOWN_S between relaunches.
  set -u
  ADB="/usr/bin/adb -s 192.168.68.60:5555"
  PROBE_URL=${PROBE_URL:-http://127.0.0.1:8500/v2/health/live}
  STATE_DIR=${STATE_DIR:-/run/pixel-vm-watchdog}
  THRESHOLD=3
  COOLDOWN_S=300

  if curl -s -m 5 -f -o /dev/null "$PROBE_URL"; then
      echo 0 > "$STATE_DIR/failures"
      exit 0
  fi
  n=$(( $(cat "$STATE_DIR/failures" 2>/dev/null || echo 0) + 1 ))
  echo "$n" > "$STATE_DIR/failures"
  echo "MLServer probe failed ($n consecutive)"
  [ "$n" -lt "$THRESHOLD" ] && exit 0

  if [ "$($ADB get-state 2>/dev/null)" != "device" ]; then
      echo "adb not connected to the Pixel; can't check the VM"
      exit 0
  fi
  if $ADB shell pidof crosvm > /dev/null 2>&1; then
      echo "VM process is running; treating it as a network/tunnel problem, not relaunching"
      exit 0
  fi
  now=$(date +%s); last=$(cat "$STATE_DIR/last-relaunch" 2>/dev/null || echo 0)
  if [ $((now - last)) -lt "$COOLDOWN_S" ]; then
      echo "VM not running, but relaunched $((now - last)) s ago; waiting for it to boot"
      exit 0
  fi
  echo "VM not running: relaunching the Terminal app"
  $ADB shell am start -n com.android.virtualization.terminal/.new2.ui.MainActivity
  echo "$now" > "$STATE_DIR/last-relaunch"
  ```

  ```ini
  # /etc/systemd/system/pixel-vm-watchdog.service
  [Unit]
  Description=Relaunch cerebrate-pixel6's Debian VM if Android killed it
  After=network-online.target
  Wants=network-online.target

  [Service]
  Type=oneshot
  User=austin
  RuntimeDirectory=pixel-vm-watchdog
  RuntimeDirectoryPreserve=yes
  ExecStart=/usr/local/bin/pixel-vm-watchdog
  ```

  ```ini
  # /etc/systemd/system/pixel-vm-watchdog.timer
  [Unit]
  Description=Check cerebrate-pixel6's Debian VM every minute

  [Timer]
  OnBootSec=2min
  OnUnitActiveSec=60s
  AccuracySec=5s

  [Install]
  WantedBy=timers.target
  ```

- **`pixel-supervisor-watchdog.timer`** (installed 2026-10-25; see the
  [Pixel 6 models runbook](../../runbooks/cerebrate-pixel6-models.md). The
  repo version since then fixes a TIME_WAIT false positive and clears orphans
  of every worker binary; reinstall it with the `install` line below after
  pulling)
  restarts `cerebrate-supervisor` on the phone when its control port (8767)
  isn't listening: after a crash or the low-memory killer. After an Android
  reboot it can act only once `adb tcpip` has been re-enabled by hand;
  reboot recovery is not unattended. It kills orphaned on-demand `cerebrate-hetero`
  workers first (a new supervisor can't adopt them), launches the supervisor
  with the documented detached command, and then asks MLServer to load any
  model that isn't READY. At most one start per 2 minutes; it never touches a
  running supervisor, the VM, or the pinned workers. Tested against the
  side-by-side test supervisor (`kill -9` → orphan cleared, supervisor back,
  models reloaded, next request served). The script is in the repo:
  [`pixel-supervisor-watchdog`](../cerebrate-pixel6/cerebrate-supervisor/pixel-supervisor-watchdog),
  installed as `/usr/local/bin/pixel-supervisor-watchdog`. **Stop the timer
  during any deliberate supervisor swap**, or it relaunches the old binary
  in the middle of the swap: `sudo systemctl stop pixel-supervisor-watchdog.timer`.

  ```ini
  # /etc/systemd/system/pixel-supervisor-watchdog.service
  [Unit]
  Description=Restart cerebrate-pixel6's cerebrate-supervisor if it isn't running
  After=network-online.target pixel-adb-reconnect.service
  Wants=network-online.target

  [Service]
  Type=oneshot
  User=austin
  RuntimeDirectory=pixel-supervisor-watchdog
  RuntimeDirectoryPreserve=yes
  TimeoutStartSec=15min
  ExecStart=/usr/local/bin/pixel-supervisor-watchdog
  ```

  ```ini
  # /etc/systemd/system/pixel-supervisor-watchdog.timer
  [Unit]
  Description=Check cerebrate-pixel6's cerebrate-supervisor every minute

  [Timer]
  OnBootSec=3min
  OnUnitActiveSec=60s
  AccuracySec=5s

  [Install]
  WantedBy=timers.target
  ```

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
  app state are live on it. Swap (`swapfile`), Docker/containerd storage, and
  `~austin/.cache` are on it too. Docker refuses to start without the SSD; see
  [storage](../../design-notes/storage-layout.md#logical-paths-and-physical-disks).
- **`/tmp` is RAM (tmpfs, 3.9 GB). Don't put large files there.** Its contents
  take memory and are pushed to swap when RAM is short. On 2026-10-27, 2.7 GB of
  leftover model-conversion staging in `/tmp` had filled the 4 GB swap
  completely, leaving no headroom for a compile or a Python job.
  - **Large scratch** (models, conversions, datasets, anything over ~100 MB): use a
    working directory on the SSD, for example under `/mnt/disks/ssd1` or the
    substrate. Delete it when the work is done.
  - **Check:** `df -h /tmp` and `free -h`.
- **The OpenClaw Gateway's memory warning is expected.** It logs
  `memory pressure: level=warning reason=rss_threshold` every 5 minutes because
  it runs at a steady ~1.8 GiB, over OpenClaw's default 1.5 GiB warning line.
  - Not a leak: flat all day, with a normal garbage-collection cycle, and back at
    the same level after a restart.
  - Act only on `level=critical` or usage that keeps climbing.

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
