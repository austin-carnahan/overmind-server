#!/usr/bin/env bash
# Stage 3 of design-notes/fire_tv_4k_max_emulation_optimization_design.md:
# force-stop only a reviewed allowlist of nonessential third-party apps
# before an emulation session, and capture a memory/CPU snapshot before and
# after. Temporary only (am force-stop, not pm disable) -- no persistent
# package state changes, nothing here needs a rollback command.
#
# Run from a host with adb already connected to the Fire TV Stick this
# session (adb connect <LAN IP>:5555, approved on-device) -- connectivity
# is deliberately session-based, not a standing connection; see the
# emulator validation design's "Connectivity model" section.

set -euo pipefail

DEVICE_SERIAL="${DEVICE_SERIAL:-192.168.68.62:5555}"
ADB="adb -s $DEVICE_SERIAL"

# Reviewed 2026-09-22 against the real device's actual installed
# third-party package list (`adb shell pm list packages -3 -f`), not an
# internet debloat list. Every package here is a streaming/file-manager/
# utility app with no role during active gameplay.
STOPPABLE_PACKAGES=(
  org.smarttube.stable      # SmartTube (YouTube client)
  com.koushikdutta.vysor    # Vysor (screen mirroring)
  com.retro.rshop           # R-Shop (ROM library browser)
  com.mixplorer             # MiXplorer (file manager)
  com.seerr.tv              # Seerr TV (Jellyseerr/Overseerr client)
  org.jellyfin.androidtv    # Jellyfin (media streaming)
)

# Never force-stop these. Projectivy and the Home-routing utility per the
# design doc's explicit caution; Tailscale because it's this device's
# remote-access path; RetroArch because it's what we're about to launch.
PROTECTED_PACKAGES=(
  com.spocky.projengmenu       # Projectivy Launcher
  io.github.toolicious.homeonfire  # Home-routing utility
  com.tailscale.ipn            # Tailscale (remote access)
  com.retroarch.ra32           # RetroArch
)

echo "== Verifying protected packages are enabled =="
enabled_packages="$($ADB shell pm list packages -e)"
for pkg in "${PROTECTED_PACKAGES[@]}"; do
  if ! grep -q "$pkg" <<<"$enabled_packages"; then
    echo "REFUSING to continue: protected package $pkg is not enabled" >&2
    exit 1
  fi
  echo "  ok: $pkg"
done

echo "== Prelaunch memory snapshot =="
$ADB shell dumpsys meminfo | head -3
mem_before="$($ADB shell cat /proc/meminfo | head -3)"
echo "$mem_before"

echo "== Force-stopping approved nonessential packages =="
for pkg in "${STOPPABLE_PACKAGES[@]}"; do
  echo "  stopping: $pkg"
  $ADB shell am force-stop "$pkg"
done

echo "== Confirming no unexpected media/VPN foreground service remains =="
active_sessions="$($ADB shell dumpsys media_session | grep -A2 'Sessions Stack' || true)"
echo "$active_sessions"

echo "== Postlaunch (post-stop) memory snapshot =="
mem_after="$($ADB shell cat /proc/meminfo | head -3)"
echo "$mem_after"

echo "== Confirming protected packages still running/enabled =="
for pkg in "${PROTECTED_PACKAGES[@]}"; do
  if ! $ADB shell pm list packages -e | grep -q "$pkg"; then
    echo "WARNING: protected package $pkg no longer enabled" >&2
  fi
done

echo "== Done. Stopped packages will relaunch normally next time they're opened. =="
