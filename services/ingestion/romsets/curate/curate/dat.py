"""Parse a clrmamepro-format DAT (the libretro-database No-Intro format):

clrmamepro (
    name "..."
)
game (
    name "Some Game (USA)"
    rom ( name "Some Game (USA).md" size 524288 crc AEB4B262 md5 ... sha1 ... )
)

Not XML -- this is clrmamepro's original text syntax, distinct from the
Logiqx XML DAT format some other DAT sources use.
"""

import re
from dataclasses import dataclass

NAME_LINE_RE = re.compile(r'^\s*name "([^"]*)"')
ROM_LINE_RE = re.compile(
    r'^\s*rom\s*\('
    r'\s*name "([^"]*)"'
    r'\s*size (\d+)'
    r'(?:.*?\bcrc ([0-9A-Fa-f]+))?'
    r'(?:.*?\bmd5 ([0-9A-Fa-f]+))?'
    r'(?:.*?\bsha1 ([0-9A-Fa-f]+))?'
)


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
    by_hash: dict[str, DatEntry] = {}
    in_game_block = False
    current_game_name: str | None = None

    with open(dat_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith("game ("):
                in_game_block = True
                current_game_name = None
                continue
            if not in_game_block:
                continue
            if stripped == ")":
                in_game_block = False
                continue

            rom_match = ROM_LINE_RE.match(line)
            if rom_match:
                rom_name, size, crc32, md5, sha1 = rom_match.groups()
                entry = DatEntry(
                    game_name=current_game_name or rom_name,
                    rom_name=rom_name,
                    size=int(size) if size else None,
                    crc32=(crc32 or "").lower() or None,
                    md5=(md5 or "").lower() or None,
                    sha1=(sha1 or "").lower() or None,
                )
                for key in (entry.sha1, entry.md5, entry.crc32):
                    if key:
                        by_hash[key] = entry
                continue

            if current_game_name is None:
                name_match = NAME_LINE_RE.match(line)
                if name_match:
                    current_game_name = name_match.group(1)

    return by_hash
