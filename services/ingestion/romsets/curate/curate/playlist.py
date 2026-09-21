"""Stage: playlist. Build a RetroArch .lpl for the library tier, using
RetroArch's own canonical naming (see platforms.py), not our internal key.

Known limitation: this reads the deployed library tier (everything
curated for the platform), not what's actually been downloaded to a given
device via R-Shop -- curate has no visibility into device storage. A
playlist built here will list every curated title; entries for titles not
yet downloaded to that specific device will fail to launch until R-Shop
downloads them. Regenerate device-side (listing the real ROM directory)
instead if a playlist matching only currently-downloaded titles is wanted.
"""

import json
from pathlib import Path

from .platforms import retroarch_name

PLAYLIST_VERSION = "1.5"


def build_playlist(platform: str, library_dir: Path, device_rom_dir: str, out_path: Path) -> int:
    name = retroarch_name(platform)
    lpl_filename = f"{name}.lpl"
    device_root = device_rom_dir.rstrip("/")

    items = []
    for f in sorted(library_dir.iterdir()):
        if not f.is_file():
            continue
        items.append(
            {
                "path": f"{device_root}/{f.name}",
                "label": f.stem,
                "core_path": "DETECT",
                "core_name": "DETECT",
                "crc32": "00000000|crc",
                "db_name": lpl_filename,
            }
        )

    playlist = {
        "version": PLAYLIST_VERSION,
        "default_core_path": "",
        "default_core_name": "",
        "label_display_mode": 0,
        "right_thumbnail_mode": 0,
        "left_thumbnail_mode": 0,
        "sort_mode": 0,
        "items": items,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(playlist, indent=2))
    return len(items)
