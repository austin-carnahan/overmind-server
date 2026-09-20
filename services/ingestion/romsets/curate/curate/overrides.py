"""Load and apply version-controlled manual overrides (never hand-edited gamelists)."""

import json
from pathlib import Path


def load_overrides(overrides_path: Path, platform: str) -> dict:
    if not overrides_path.exists():
        return {}
    data = json.loads(overrides_path.read_text())
    return data.get(platform, {})


def _key(record: dict) -> str:
    return record.get("display_name") or record.get("dat_name") or record["canonical_filename"]


def apply_overrides(candidates: list[dict], overrides: dict) -> list[dict]:
    kept = []
    for c in candidates:
        override = overrides.get(_key(c))
        if override:
            c["override"] = override
            if override.get("igdb_id") and c.get("igdb_id") != override["igdb_id"]:
                c["igdb_id"] = override["igdb_id"]
            if override.get("force_exclude"):
                continue
        kept.append(c)

    forced_titles = {
        title for title, o in overrides.items() if o.get("force_include") and title not in {_key(c) for c in kept}
    }
    for title in forced_titles:
        kept.append({"canonical_filename": title, "display_name": title, "override": overrides[title], "final_score": None})

    return kept
