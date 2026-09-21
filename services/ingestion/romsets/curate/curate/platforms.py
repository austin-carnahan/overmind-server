"""Canonical RetroArch playlist/thumbnail names, per platform.

RetroArch selects its XMB icon and thumbnail set by matching a playlist's
base filename (and each item's db_name) against these exact strings, from
Libretro's own database/thumbnail-repo naming -- spelling, capitalization,
spaces, and hyphens must match exactly, or RetroArch falls back to a
generic icon and finds no thumbnails. Confirmed correct against the real
device for genesis (already matched before this table existed).

Our own internal platform keys (genesis, nes, snes, ...) are just our own
convenient shorthand for folder names, DAT lookups, and Skyscraper's own
distinct platform keys (see screenscraper.py's PLATFORM_MAP) -- none of
that needs to match RetroArch's naming, and RetroArch's naming never needs
to match ours. ROM folder names (both server-side
/mnt/library/romsets/<platform> and device-side
/storage/.../roms/<platform>) stay simple; only the playlist file, its
items' db_name, and the thumbnails/<name>/ directory need the canonical
RetroArch name.
"""

RETROARCH_SYSTEM_NAMES = {
    "genesis": "Sega - Mega Drive - Genesis",
    "nes": "Nintendo - Nintendo Entertainment System",
    "snes": "Nintendo - Super Nintendo Entertainment System",
    "n64": "Nintendo - Nintendo 64",
    "psx": "Sony - PlayStation",
    "dreamcast": "Sega - Dreamcast",
}


def retroarch_name(platform: str) -> str:
    try:
        return RETROARCH_SYSTEM_NAMES[platform]
    except KeyError:
        raise SystemExit(
            f"no known RetroArch canonical name for platform {platform!r}; "
            f"add it to RETROARCH_SYSTEM_NAMES in curate/platforms.py"
        )
