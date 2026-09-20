"""Stage: score. Bayesian blend of ScreenScraper + IGDB ratings.

score = (C*25 + S*10 + I*min(V,100)) / (25 + 10 + min(V,100))
Falls back to the two-source-missing variants documented in
design-notes/romset-curation-pipeline.md when S or I is absent. Weights
(25, 10, 100) are starting points, not derived constants -- expect to retune
after looking at real output.
"""

import json
from pathlib import Path

DEFAULT_CROSS_PLATFORM_PRIOR = 70.0
PRIOR_WEIGHT = 25.0
SCREENSCRAPER_WEIGHT = 10.0
IGDB_VOTE_CAP = 100.0


def _to_100(rating_0_to_1: float | None) -> float | None:
    return None if rating_0_to_1 is None else rating_0_to_1 * 100.0


def _platform_prior(candidates: list[dict]) -> float:
    combined = []
    for c in candidates:
        s = _to_100(c.get("screenscraper_rating"))
        i = c.get("igdb_rating")
        vals = [v for v in (s, i) if v is not None]
        if vals:
            combined.append(sum(vals) / len(vals))
    if len(combined) < 5:  # not enough data to trust a platform-specific prior
        return DEFAULT_CROSS_PLATFORM_PRIOR
    return sum(combined) / len(combined)


def _bayesian_score(prior: float, s: float | None, i: float | None, v: float | None) -> float | None:
    if s is None and i is None:
        return None
    v = min(v or 0.0, IGDB_VOTE_CAP)
    if s is not None and i is not None:
        numerator = prior * PRIOR_WEIGHT + s * SCREENSCRAPER_WEIGHT + i * v
        denominator = PRIOR_WEIGHT + SCREENSCRAPER_WEIGHT + v
    elif i is not None:
        numerator = prior * PRIOR_WEIGHT + i * v
        denominator = PRIOR_WEIGHT + v
    else:
        numerator = prior * PRIOR_WEIGHT + s * SCREENSCRAPER_WEIGHT
        denominator = PRIOR_WEIGHT + SCREENSCRAPER_WEIGHT
    return numerator / denominator


def score_candidates(candidates_path: Path) -> list[dict]:
    candidates = json.loads(candidates_path.read_text())
    prior = _platform_prior(candidates)
    for c in candidates:
        s = _to_100(c.get("screenscraper_rating"))
        i = c.get("igdb_rating")
        v = c.get("igdb_rating_count")
        c["platform_prior"] = prior
        c["final_score"] = _bayesian_score(prior, s, i, v)
        c["rating_coverage"] = sum(1 for val in (s, i) if val is not None)
    candidates_path.write_text(json.dumps(candidates, indent=2))
    return candidates
