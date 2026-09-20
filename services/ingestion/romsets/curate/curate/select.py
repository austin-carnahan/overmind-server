"""Stage: select. Deterministic ordering and top-N cut, plus the review CSVs."""

import csv
import json
from pathlib import Path

from .overrides import apply_overrides, load_overrides

REPORT_FIELDS = [
    "rank",
    "canonical_filename",
    "display_name",
    "sha1",
    "screenscraper_rating",
    "igdb_rating",
    "igdb_rating_count",
    "platform_prior",
    "final_score",
    "identity_method",
    "igdb_match_method",
    "igdb_id",
    "screenscraper_id",
    "override",
]


def _sort_key(record: dict):
    score = record.get("final_score")
    return (
        -(score if score is not None else -1),
        -record.get("rating_coverage", 0),
        record.get("release_date") or "",
        record.get("canonical_filename") or "",
    )


def _write_csv(path: Path, records: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=REPORT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)


def select_top(
    identified_path: Path,
    candidates_path: Path,
    overrides_path: Path,
    out_dir: Path,
    platform: str,
    limit: int = 100,
) -> list[dict]:
    identified = json.loads(identified_path.read_text())
    candidates = json.loads(candidates_path.read_text())

    overrides = load_overrides(overrides_path, platform)
    candidates = apply_overrides(candidates, overrides)
    candidates.sort(key=_sort_key)
    for i, record in enumerate(candidates, start=1):
        record["rank"] = i

    top = candidates[:limit]

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "top-100.json").write_text(json.dumps(top, indent=2))
    _write_csv(out_dir / "top-100.csv", top)
    _write_csv(out_dir / "all-candidates.csv", candidates)

    unmatched_ss = [r for r in identified if r.get("identity_method") == "unmatched"]
    _write_csv(out_dir / "unmatched-screenscraper.csv", unmatched_ss)

    unmatched_igdb = [r for r in candidates if r.get("igdb_match_method") == "unmatched"]
    _write_csv(out_dir / "unmatched-igdb.csv", unmatched_igdb)

    return top
