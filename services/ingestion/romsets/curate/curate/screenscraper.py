"""Stage: scrape. Shell out to Skyscraper for ScreenScraper identification,
full archive tier.

Skyscraper (https://github.com/Gemba/skyscraper) is a compiled C++ binary
present in this image (see Dockerfile) -- this module just drives it and
parses the EmulationStation-format gamelist.xml it produces. Only a normal
ScreenScraper user account is needed (-u ssid:sspassword); Skyscraper's own
bundled developer credentials do the actual API authentication.
"""

import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

# Skyscraper's own platform keys differ from ours in some cases -- see
# docs/PLATFORMS.md in the Skyscraper repo. Extend as new platforms are added.
PLATFORM_MAP = {
    "genesis": "megadrive",
}


def _run_skyscraper(
    platform: str,
    rom_dir: Path,
    gamelist_dir: Path,
    media_dir: Path,
    cache_dir: Path,
    ssid: str,
    sspassword: str,
    refresh: bool,
):
    sky_platform = PLATFORM_MAP.get(platform, platform)
    gamelist_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "Skyscraper",
        "-p", sky_platform,
        "-s", "screenscraper",
        "-u", f"{ssid}:{sspassword}",
        "-i", str(rom_dir),
        "-g", str(gamelist_dir),
        "-o", str(media_dir),
        "-d", str(cache_dir),
        "--flags", "relative,unattend",
    ]
    if refresh:
        cmd += ["--cache", "refresh"]
    subprocess.run(cmd, check=True)


def _text(game: ET.Element, tag: str) -> str | None:
    el = game.find(tag)
    return el.text if el is not None else None


def _parse_gamelist(gamelist_path: Path) -> dict[str, dict]:
    if not gamelist_path.exists():
        return {}
    root = ET.parse(gamelist_path).getroot()
    by_filename: dict[str, dict] = {}
    for game in root.findall("game"):
        path = _text(game, "path")
        if not path:
            continue
        rating = _text(game, "rating")
        by_filename[Path(path).name] = {
            "display_name": _text(game, "name"),
            "description": _text(game, "desc"),
            "release_date": _text(game, "releasedate"),
            "developer": _text(game, "developer"),
            "publisher": _text(game, "publisher"),
            "genres": [g for g in [_text(game, "genre")] if g],
            "players": _text(game, "players"),
            "screenscraper_rating": float(rating) if rating else None,
            "image": _text(game, "image"),
        }
    return by_filename


def scrape_platform(
    platform: str,
    inventory_path: Path,
    rom_dir: Path,
    gamelist_dir: Path,
    media_dir: Path,
    cache_dir: Path,
    creds: dict,
    out_path: Path,
    refresh: bool = False,
) -> list[dict]:
    inventory = json.loads(inventory_path.read_text())
    _run_skyscraper(
        platform, rom_dir, gamelist_dir, media_dir, cache_dir, creds["ssid"], creds["sspassword"], refresh
    )
    by_filename = _parse_gamelist(gamelist_dir / "gamelist.xml")

    identified = []
    for record in inventory:
        filename = Path(record["path"]).name
        fields = by_filename.get(filename)
        if fields:
            identified.append(
                {**record, **fields, "identity_method": "gamelist_path_match", "identity_confidence": 1.0}
            )
        else:
            identified.append({**record, "identity_method": "unmatched", "identity_confidence": 0.0})

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(identified, indent=2))
    return identified
