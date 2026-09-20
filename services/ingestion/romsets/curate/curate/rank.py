"""Stage: rank. Cut the full identified archive down to IGDB-enrichment candidates.

Pure local sort -- no external calls. This is the step that keeps IGDB
matching (the fragile, human-review-heavy part) proportional to the actual
decision instead of the whole archive.
"""

import json
from pathlib import Path


def rank_candidates(identified_path: Path, out_path: Path, candidate_count: int = 150) -> list[dict]:
    identified = json.loads(identified_path.read_text())
    rated = [r for r in identified if r.get("screenscraper_rating") is not None]
    rated.sort(key=lambda r: r["screenscraper_rating"], reverse=True)
    candidates = rated[:candidate_count]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(candidates, indent=2))
    return candidates
