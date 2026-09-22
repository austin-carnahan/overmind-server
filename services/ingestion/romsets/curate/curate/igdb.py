"""Stage: enrich-igdb. Second rating source, candidates only (see README).

Twitch client-credentials OAuth + IGDB's query API. Untested against the
live API pending real credentials -- built against IGDB's documented v4
contract.
"""

import csv
import difflib
import json
import time
from pathlib import Path

import requests

from .titles import clean_title

TOKEN_URL = "https://id.twitch.tv/oauth2/token"
GAMES_URL = "https://api.igdb.com/v4/games"

FIELDS = (
    "name,alternative_names.name,platforms.name,first_release_date,"
    "rating,rating_count,aggregated_rating,aggregated_rating_count,slug"
)


def _get_token(client_id: str, client_secret: str) -> str:
    resp = requests.post(
        TOKEN_URL,
        params={"client_id": client_id, "client_secret": client_secret, "grant_type": "client_credentials"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _escape_query_string(title: str) -> str:
    """Escape for embedding in an Apicalypse double-quoted string literal.
    Confirmed necessary against the real API: an unescaped title containing
    a literal quote (e.g. 'Ivan "Ironman" Stewart's Super Off Road') closes
    the query's string early and IGDB returns a 400 Syntax Error."""
    return title.replace("\\", "\\\\").replace('"', '\\"')


def _query(session: requests.Session, client_id: str, token: str, title: str) -> list[dict]:
    headers = {"Client-ID": client_id, "Authorization": f"Bearer {token}"}
    body = f'search "{_escape_query_string(title)}"; fields {FIELDS}; limit 10;'
    resp = session.post(GAMES_URL, headers=headers, data=body, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _year(unix_ts: int | None) -> int | None:
    if unix_ts is None:
        return None
    import datetime

    return datetime.datetime.utcfromtimestamp(unix_ts).year


def _match(record: dict, title: str, results: list[dict]) -> tuple[dict | None, str, float]:
    """Return (best_match, method, confidence) per the documented matching order/thresholds."""
    want_year = None
    if record.get("release_date"):
        try:
            want_year = int(str(record["release_date"])[:4])
        except ValueError:
            want_year = None

    def year_ok(candidate_year: int | None) -> bool:
        if want_year is None or candidate_year is None:
            return True
        return abs(candidate_year - want_year) <= 1

    for game in results:
        if game.get("name", "").lower() == title.lower() and year_ok(_year(game.get("first_release_date"))):
            return game, "exact_title", 1.0

    for game in results:
        alt_names = [a.get("name", "") for a in game.get("alternative_names", [])]
        if title.lower() in [a.lower() for a in alt_names] and year_ok(_year(game.get("first_release_date"))):
            return game, "alias", 0.9

    for game in results:
        if game.get("name", "").lower() == title.lower():
            return game, "title_only", 0.8

    best, best_ratio = None, 0.0
    for game in results:
        ratio = difflib.SequenceMatcher(None, title.lower(), game.get("name", "").lower()).ratio()
        if ratio > best_ratio:
            best, best_ratio = game, ratio
    if best is not None and best_ratio >= 0.95 and year_ok(_year(best.get("first_release_date"))):
        return best, "fuzzy_95", best_ratio

    return None, "unmatched", 0.0


def enrich_candidates(
    candidates_path: Path,
    cache_dir: Path,
    creds: dict,
    ambiguous_out: Path,
    refresh: bool = False,
    rate_limit_seconds: float = 0.3,
) -> list[dict]:
    candidates = json.loads(candidates_path.read_text())
    cache_dir.mkdir(parents=True, exist_ok=True)
    token = _get_token(creds["client_id"], creds["client_secret"])
    session = requests.Session()

    ambiguous_rows = []
    for record in candidates:
        raw_title = record.get("display_name") or record.get("dat_name") or record["canonical_filename"]
        title = clean_title(raw_title)
        cache_key = record["sha1"]
        cache_file = cache_dir / f"{cache_key}.json"
        if cache_file.exists() and not refresh:
            results = json.loads(cache_file.read_text())
        else:
            results = _query(session, creds["client_id"], token, title)
            cache_file.write_text(json.dumps(results))
            time.sleep(rate_limit_seconds)

        best, method, confidence = _match(record, title, results)
        if best:
            record["igdb_id"] = best.get("id")
            record["igdb_rating"] = best.get("rating")
            record["igdb_rating_count"] = best.get("rating_count")
            record["igdb_match_method"] = method
            record["igdb_match_confidence"] = confidence
        else:
            record["igdb_id"] = None
            record["igdb_rating"] = None
            record["igdb_rating_count"] = None
            record["igdb_match_method"] = "unmatched"
            record["igdb_match_confidence"] = 0.0

        if method not in ("exact_title", "alias", "unmatched"):
            ambiguous_rows.append(
                {"title": title, "method": method, "confidence": confidence, "sha1": record["sha1"]}
            )

    candidates_path.write_text(json.dumps(candidates, indent=2))

    ambiguous_out.parent.mkdir(parents=True, exist_ok=True)
    with ambiguous_out.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["title", "method", "confidence", "sha1"])
        writer.writeheader()
        writer.writerows(ambiguous_rows)

    return candidates
