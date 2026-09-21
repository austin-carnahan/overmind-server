"""Stage: select. Deterministic ordering, dedup, force-include/exclude, and
the top-N cut, plus the review CSVs."""

import csv
import json
from pathlib import Path

from .overrides import excluded_base_titles, forced_base_titles, load_overrides, resolve_forced_records
from .scoring import bayesian_score, to_100
from .titles import base_title

REPORT_FIELDS = [
    "rank",
    "pool_rank",
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
    "forced_include",
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


def _score_forced_record(record: dict, prior: float) -> dict:
    """Forced records come from the full identified pool, not the scored
    candidates -- give them a comparable score (ScreenScraper-only variant,
    since we don't IGDB-enrich outside the candidate pool) so final ordering
    isn't arbitrary. Inclusion never depends on this score."""
    s = to_100(record.get("screenscraper_rating"))
    record.setdefault("platform_prior", prior)
    record.setdefault("final_score", bayesian_score(prior, s, None, None))
    record.setdefault("rating_coverage", 1 if s is not None else 0)
    return record


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
    excluded = excluded_base_titles(overrides)
    forced = forced_base_titles(overrides)

    forced_records, missing_forced = resolve_forced_records(forced, identified)
    prior = candidates[0]["platform_prior"] if candidates else 70.0
    forced_records = [_score_forced_record(r, prior) for r in forced_records]
    forced_bases = {base_title(r) for r in forced_records}

    candidates = [c for c in candidates if base_title(c) not in excluded and base_title(c) not in forced_bases]
    candidates.sort(key=_sort_key)
    for i, record in enumerate(candidates, start=1):
        record["pool_rank"] = i  # position among all candidates, before dedup

    # Forced titles always make the list; fill remaining slots from the
    # normally-ranked, deduped pool.
    top = list(forced_records)
    seen_base_titles = set(forced_bases)
    for record in candidates:
        if len(top) >= limit:
            break
        base = base_title(record)
        if base in seen_base_titles:
            continue
        seen_base_titles.add(base)
        top.append(record)

    top.sort(key=_sort_key)
    for i, record in enumerate(top, start=1):
        record["rank"] = i

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "top-100.json").write_text(json.dumps(top, indent=2))
    _write_csv(out_dir / "top-100.csv", top)
    _write_csv(out_dir / "all-candidates.csv", candidates)

    unmatched_ss = [r for r in identified if r.get("identity_method") == "unmatched"]
    _write_csv(out_dir / "unmatched-screenscraper.csv", unmatched_ss)

    unmatched_igdb = [r for r in candidates if r.get("igdb_match_method") == "unmatched"]
    _write_csv(out_dir / "unmatched-igdb.csv", unmatched_igdb)

    if missing_forced:
        (out_dir / "overrides-not-found.txt").write_text("\n".join(missing_forced) + "\n")

    return top
