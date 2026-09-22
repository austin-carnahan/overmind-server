#!/usr/bin/env python3
"""Poll the Fire TV Stick's real on-device ROM directories over adb and
regenerate/push RetroArch .lpl playlists when their contents change.

This is the trigger point for the "R-Shop change -> RetroArch sees it"
automation: R-Shop is a sideloaded APK with no local database and no
add/remove hooks (it reads its SMB source live and writes downloaded ROMs
straight into /storage/DF3B-5BC7/roms/<platform>/), so the only reliable
signal that the on-device library changed is that directory's own
contents. Run every 5 minutes by firetv-playlist-sync.timer (see
../README.md); each run is a short-lived, stateless adb session -- no
persistent connection or on-device process required.

Deliberately conservative: if adb is unreachable (device asleep/off) this
exits quietly and tries again next tick. If a listing comes back empty
while the last-known state was not, that's treated as a suspect transient
read rather than "the user deleted everything" and the run is skipped,
never blindly pushing an empty playlist over a real one.
"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, "/opt/overmind/services/ingestion/romsets/curate")
from curate.platforms import retroarch_name  # noqa: E402

ADB = "/usr/bin/adb"
DEVICE = "192.168.68.62:5555"
DEVICE_ROM_ROOT = "/storage/DF3B-5BC7/roms"
DEVICE_PLAYLIST_DIR = "/storage/emulated/0/RetroArch/playlists"
STATE_DIR = Path("/var/lib/overmind/fire-tv-roms")
PLAYLIST_VERSION = "1.5"

# Only platforms actually wired up in R-Shop's on-device config so far --
# extend as more platforms get a SystemConfig block there.
PLATFORMS = ["genesis"]


def adb_shell(args: list[str]) -> str | None:
    try:
        result = subprocess.run(
            [ADB, "-s", DEVICE, "shell", *args],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        return result.stdout
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return None


def list_device_roms(platform: str) -> list[str] | None:
    output = adb_shell(["ls", "-1", f"{DEVICE_ROM_ROOT}/{platform}"])
    if output is None:
        return None
    names = [line.strip() for line in output.splitlines() if line.strip()]
    return sorted(names)


def build_playlist(platform: str, filenames: list[str]) -> dict:
    name = retroarch_name(platform)
    device_dir = f"{DEVICE_ROM_ROOT}/{platform}"
    items = [
        {
            "path": f"{device_dir}/{filename}",
            "label": Path(filename).stem,
            "core_path": "DETECT",
            "core_name": "DETECT",
            "crc32": "00000000|crc",
            "db_name": f"{name}.lpl",
        }
        for filename in filenames
    ]
    return {
        "version": PLAYLIST_VERSION,
        "default_core_path": "",
        "default_core_name": "",
        "label_display_mode": 0,
        "right_thumbnail_mode": 0,
        "left_thumbnail_mode": 0,
        "sort_mode": 0,
        "items": items,
    }


def push_playlist(platform: str, playlist: dict) -> bool:
    name = retroarch_name(platform)
    local_tmp = Path(f"/tmp/{name}.lpl")
    local_tmp.write_text(json.dumps(playlist, indent=2))
    try:
        subprocess.run(
            [ADB, "-s", DEVICE, "push", str(local_tmp), f"{DEVICE_PLAYLIST_DIR}/{name}.lpl"],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        print(f"[{platform}] push failed: {exc}", file=sys.stderr)
        return False
    finally:
        local_tmp.unlink(missing_ok=True)


def sync_platform(platform: str) -> None:
    state_path = STATE_DIR / f"{platform}.json"
    previous = json.loads(state_path.read_text()) if state_path.exists() else None

    current = list_device_roms(platform)
    if current is None:
        print(f"[{platform}] device unreachable, skipping this cycle")
        return

    if not current and previous:
        print(f"[{platform}] listing came back empty but state was not -- "
              f"treating as a transient read, skipping")
        return

    if current == previous:
        return

    playlist = build_playlist(platform, current)
    if not push_playlist(platform, playlist):
        return

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(current, indent=2))
    print(f"[{platform}] {len(current)} item(s), playlist updated")


def main() -> None:
    for platform in PLATFORMS:
        sync_platform(platform)


if __name__ == "__main__":
    main()
