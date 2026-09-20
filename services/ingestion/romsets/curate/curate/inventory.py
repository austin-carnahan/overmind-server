"""Stage: inventory. Hash every archive-tier ROM and join it against the DAT.

No external services involved -- this is the stable join point every later
stage keys off of (rom_sha1).
"""

import hashlib
import json
import re
import zipfile
import zlib
from pathlib import Path

from .dat import load_dat

REGION_TAG_RE = re.compile(r"\(([^)]*)\)")
REVISION_RE = re.compile(r"Rev\s*([0-9A-Za-z.]+)", re.IGNORECASE)
ARCHIVE_EXTS = {".zip"}


def _hash_bytes(data: bytes) -> tuple[str, str, str]:
    return (
        format(zlib.crc32(data) & 0xFFFFFFFF, "08x"),
        hashlib.md5(data).hexdigest(),
        hashlib.sha1(data).hexdigest(),
    )


def _hash_rom(path: Path) -> tuple[str, str, str]:
    if path.suffix.lower() in ARCHIVE_EXTS:
        with zipfile.ZipFile(path) as zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
            if not names:
                raise ValueError(f"{path}: empty archive")
            # No-Intro archives are one ROM per zip; if not, hash the largest
            # entry (heuristic, flagged in the record for manual review).
            name = max(names, key=lambda n: zf.getinfo(n).file_size)
            return _hash_bytes(zf.read(name))
    return _hash_bytes(path.read_bytes())


def _parse_regions_and_revision(filename: str) -> tuple[list[str], str | None]:
    tags = REGION_TAG_RE.findall(filename)
    region_tag = tags[0] if tags else ""
    regions = [r.strip() for r in region_tag.split(",") if r.strip()]
    revision = None
    for tag in tags:
        m = REVISION_RE.search(tag)
        if m:
            revision = m.group(1)
    return regions, revision


def build_inventory(platform: str, archive_dir: Path, dat_path: Path, out_path: Path) -> list[dict]:
    dat_index = load_dat(str(dat_path))
    records = []
    for path in sorted(archive_dir.rglob("*")):
        if not path.is_file():
            continue
        crc32, md5, sha1 = _hash_rom(path)
        dat_entry = dat_index.get(sha1) or dat_index.get(md5) or dat_index.get(crc32)
        regions, revision = _parse_regions_and_revision(path.stem)
        records.append(
            {
                "platform": platform,
                "path": str(path.relative_to(archive_dir)),
                "canonical_filename": path.stem,
                "crc32": crc32,
                "md5": md5,
                "sha1": sha1,
                "dat_name": dat_entry.game_name if dat_entry else None,
                "dat_matched": dat_entry is not None,
                "region": regions,
                "revision": revision,
            }
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(records, indent=2))
    return records
