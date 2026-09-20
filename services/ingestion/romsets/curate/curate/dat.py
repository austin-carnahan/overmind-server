"""Parse a No-Intro Logiqx-style DAT (<datafile><game><rom .../></game></datafile>)."""

import xml.etree.ElementTree as ET
from dataclasses import dataclass


@dataclass
class DatEntry:
    game_name: str
    rom_name: str
    size: int | None
    crc32: str | None
    md5: str | None
    sha1: str | None


def load_dat(dat_path: str) -> dict[str, DatEntry]:
    """Return entries indexed by lowercase sha1, falling back to md5/crc32 keys too."""
    tree = ET.parse(dat_path)
    root = tree.getroot()
    by_hash: dict[str, DatEntry] = {}
    for game in root.findall("game"):
        game_name = game.get("name", "")
        for rom in game.findall("rom"):
            entry = DatEntry(
                game_name=game_name,
                rom_name=rom.get("name", ""),
                size=int(rom.get("size")) if rom.get("size") else None,
                crc32=(rom.get("crc") or "").lower() or None,
                md5=(rom.get("md5") or "").lower() or None,
                sha1=(rom.get("sha1") or "").lower() or None,
            )
            for key in (entry.sha1, entry.md5, entry.crc32):
                if key:
                    by_hash[key] = entry
    return by_hash
