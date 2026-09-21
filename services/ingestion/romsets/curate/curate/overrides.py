"""Load version-controlled manual overrides (never hand-edited gamelists).

Override keys are matched against a record's normalized base title (region/
edition tags stripped, case-insensitive) -- see titles.py -- not the exact
archive filename, so "Golden Axe" in overrides.json matches whichever
edition of Golden Axe is in the archive.
"""

import json
from pathlib import Path

from .titles import base_title, clean_title


def load_overrides(overrides_path: Path, platform: str) -> dict:
    if not overrides_path.exists():
        return {}
    data = json.loads(overrides_path.read_text())
    return data.get(platform, {})


def excluded_base_titles(overrides: dict) -> set[str]:
    return {clean_title(title).lower() for title, o in overrides.items() if o.get("force_exclude")}


def forced_base_titles(overrides: dict) -> dict[str, dict]:
    return {clean_title(title).lower(): o for title, o in overrides.items() if o.get("force_include")}


def resolve_forced_records(forced: dict[str, dict], identified: list[dict]) -> tuple[list[dict], list[str]]:
    """Look up each force_include title against the full identified pool
    (not just the ranked candidates -- a personal favorite may not have
    scored high enough to make the candidate cut at all) and pick one
    concrete file per title. Returns (resolved records, titles not found)."""
    from .titles import plainness

    by_base: dict[str, list[dict]] = {}
    for record in identified:
        by_base.setdefault(base_title(record), []).append(record)

    resolved = []
    missing = []
    for title_key, override in forced.items():
        matches = by_base.get(title_key)
        if not matches:
            missing.append(title_key)
            continue
        chosen = min(matches, key=lambda r: (plainness(r), -(r.get("screenscraper_rating") or 0)))
        record = dict(chosen)
        record["override"] = override
        record["forced_include"] = True
        resolved.append(record)
    return resolved, missing
