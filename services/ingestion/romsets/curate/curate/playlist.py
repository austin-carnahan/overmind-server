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
from .titles import clean_title

PLAYLIST_VERSION = "1.5"


def _game_files(library_dir: Path):
    """Yields (device-relative path parts, label-source stem) for each
    playable entry. A top-level file is one game (cartridge platforms, or
    a single-disc CHD). A top-level subdirectory is a multi-disc game --
    its .m3u is the entry to launch, not the individual discs inside."""
    for entry in sorted(library_dir.iterdir()):
        if entry.is_file():
            yield (entry.name,), entry.stem
        elif entry.is_dir():
            m3u_files = list(entry.glob("*.m3u"))
            if len(m3u_files) == 1:
                yield (entry.name, m3u_files[0].name), m3u_files[0].stem
            # a subfolder with anything other than exactly one .m3u isn't a
            # recognized game entry (e.g. a conversion that never finished
            # promoting) -- skip it rather than guess


def build_playlist(platform: str, library_dir: Path, device_rom_dir: str, out_path: Path) -> int:
    name = retroarch_name(platform)
    lpl_filename = f"{name}.lpl"
    device_root = device_rom_dir.rstrip("/")

    items = []
    for path_parts, label_stem in _game_files(library_dir):
        items.append(
            {
                "path": "/".join([device_root, *path_parts]),
                "label": clean_title(label_stem),
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
