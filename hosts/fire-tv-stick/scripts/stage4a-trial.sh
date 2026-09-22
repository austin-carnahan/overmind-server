#!/usr/bin/env bash
# Stage 4A trial runner (design-notes/fire_tv_4k_max_emulation_optimization_design.md).
# Captures PSS/system-pressure snapshots at fixed timestamps around one of
# three trial actions, to attribute the Amazon-service memory burst
# correlated with RetroArch launch before acting on it.
#
# Usage: stage4a-trial.sh <control|generic|retroarch> <output-dir>
# Requires adb already connected to the Fire TV Stick this session.

set -euo pipefail

TRIAL="${1:?usage: stage4a-trial.sh <control|generic|retroarch> <output-dir>}"
OUT_DIR="${2:?usage: stage4a-trial.sh <control|generic|retroarch> <output-dir>}"
DEVICE_SERIAL="${DEVICE_SERIAL:-192.168.68.62:5555}"
ADB="adb -s $DEVICE_SERIAL"

mkdir -p "$OUT_DIR"

capture() {
  local label="$1"
  local f="$OUT_DIR/$label"
  $ADB shell dumpsys meminfo > "$f.meminfo.txt"
  $ADB shell dumpsys cpuinfo > "$f.cpuinfo.txt"
  $ADB shell cat /proc/meminfo > "$f.procmeminfo.txt"
  $ADB shell cat /proc/vmstat > "$f.vmstat.txt"
  $ADB shell dumpsys activity processes > "$f.activity.txt"
  echo "captured: $label"
}

echo "== Trial: $TRIAL -> $OUT_DIR =="
capture "00-idle"

case "$TRIAL" in
  control)
    echo "control: no action taken, observing baseline drift only"
    ;;
  generic)
    $ADB shell am force-stop com.mixplorer
    $ADB shell monkey -p com.mixplorer -c android.intent.category.LAUNCHER 1 >/dev/null
    ;;
  retroarch)
    $ADB shell am force-stop com.retroarch.ra32
    $ADB shell am start -n com.retroarch.ra32/com.retroarch.browser.retroactivity.RetroActivityFuture \
      -e ROM "'/storage/DF3B-5BC7/roms/genesis/Golden Axe (World) (Rev A).zip'" \
      -e LIBRETRO "'/data/user/0/com.retroarch.ra32/cores/genesis_plus_gx_libretro_android.so'" \
      -e CONFIGFILE "'/storage/emulated/0/RetroArch/retroarch.cfg'"
    ;;
  *)
    echo "unknown trial: $TRIAL (expected control|generic|retroarch)" >&2
    exit 1
    ;;
esac

capture "01-t0-immediately-after"

# Checkpoints at 15/30/60/120/300s total elapsed since the action.
declare -A LABELS=( [15]=02-t15s [30]=03-t30s [60]=04-t60s [120]=05-t120s [300]=06-t300s )
prev=0
for t in 15 30 60 120 300; do
  delta=$((t - prev))
  sleep "$delta"
  capture "${LABELS[$t]}"
  prev=$t
done

echo "== Trial complete: $TRIAL =="
