"""Stage: placeholders. For remote-sourced platforms (remote_scan.py), create
zero-byte stub files matching each archive-tier entry's real filename, so
Skyscraper can identify/rate them via its filename fallback -- confirmed
against the real ScreenScraper API (100% match, full metadata) without
downloading any ROM/disc content. `scrape` then points at this directory
exactly as it would a real local archive tier.
"""

import json
from pathlib import Path


def build_placeholders(inventory_path: Path, out_dir: Path) -> int:
    records = json.loads(inventory_path.read_text())
    out_dir.mkdir(parents=True, exist_ok=True)

    wanted_names = {record["path"] for record in records}
    for existing in out_dir.iterdir():
        if existing.is_file() and existing.name not in wanted_names:
            existing.unlink()

    created = 0
    for record in records:
        stub_path = out_dir / record["path"]
        if not stub_path.exists():
            stub_path.touch()
            created += 1
    return created
