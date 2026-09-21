"""Stage: remote-scan. For disc-based systems where the full archive is too
large to download wholesale (multiple TB) -- scan a Minerva-Myrient-style
catalog's per-title metadata pages (already carrying crc32/md5/sha1/size/
region/a shared-torrent file index) and produce an archive-tier-equivalent
inventory.json, without downloading any ROM/disc content.

This replaces the "download full archive -> run Igir" step used for
cartridge systems (see inventory.py) -- there's no local archive tier for
these platforms, so DAT-matching, junk-tag exclusion, region filtering, and
1G1R dedup (the same jobs Igir does locally) all happen here directly
against scraped metadata, reusing dat.py and titles.py.

Only the final selected ~100 titles ever get downloaded (see deploy stage),
via the shared per-system torrent's file-index selection -- not this stage.
"""

import json
import re
import time
from pathlib import Path

import requests

from .dat import load_dat_by_name
from .titles import base_title, clean_title

LISTING_LINK_RE = re.compile(r'<a href="/rom\?id=(\d+)"[^>]*>([^<]*)</a>')
ROM_JSON_RE = re.compile(r"window\.rom\s*=\s*(\{.*?\});", re.DOTALL)

# Same class of junk No-Intro/Redump metadata carries for cartridge DATs --
# Igir's --only-retail/--no-unlicensed excludes these by DAT category; this
# site doesn't expose a category field, so exclude by filename tag instead,
# same heuristic already documented as a known gap in igir.md.
JUNK_TAG_RE = re.compile(
    r"\((?:Beta|Demo|Proto(?:type)?|Sample|Program|Unl|Pirate|Aftermarket|Bad ?Dump)\b[^)]*\)",
    re.IGNORECASE,
)

# Exclusionary, matching --filter-region USA,WORLD used for the cartridge
# archive tiers. Preference order for 1G1R dedup among survivors.
ALLOWED_REGIONS = ["USA", "World"]


def _is_junk(file_name: str) -> bool:
    return bool(JUNK_TAG_RE.search(file_name))


def _get_with_retry(
    session: requests.Session, url: str, max_attempts: int = 5, backoff_base_seconds: float = 3.0, **kwargs
) -> requests.Response:
    """A multi-hour unattended scan against a third-party site WILL see
    transient timeouts/connection resets -- confirmed the hard way (a real
    run crashed after 267/11,170 pages on one ReadTimeout, losing hours of
    progress since nothing was persisted until the very end). Retry with
    backoff instead of letting one bad request kill the whole run."""
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            resp = session.get(url, **kwargs)
            resp.raise_for_status()
            return resp
        except requests.exceptions.RequestException as exc:
            last_exc = exc
            if attempt < max_attempts:
                time.sleep(backoff_base_seconds * attempt)
    raise last_exc


def fetch_listing(session: requests.Session, listing_url: str, cache_path: Path, refresh: bool = False) -> list[dict]:
    if cache_path.exists() and not refresh:
        html = cache_path.read_text()
    else:
        resp = _get_with_retry(session, listing_url, timeout=30)
        html = resp.text
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(html)

    seen_ids = set()
    entries = []
    for match in LISTING_LINK_RE.finditer(html):
        rom_id = int(match.group(1))
        if rom_id in seen_ids:
            continue
        seen_ids.add(rom_id)
        file_name = match.group(2).replace("&#39;", "'").replace("&amp;", "&")
        entries.append({"id": rom_id, "file_name": file_name})
    return entries


def fetch_rom_metadata(
    session: requests.Session,
    base_url: str,
    rom_id: int,
    cache_dir: Path,
    rate_limit_seconds: float,
    refresh: bool = False,
) -> dict | None:
    cache_file = cache_dir / f"{rom_id}.json"
    if cache_file.exists() and not refresh:
        return json.loads(cache_file.read_text())

    resp = _get_with_retry(session, f"{base_url.rstrip('/')}/rom", params={"id": rom_id}, timeout=30)
    match = ROM_JSON_RE.search(resp.text)
    cache_dir.mkdir(parents=True, exist_ok=True)
    if not match:
        cache_file.write_text("null")
        time.sleep(rate_limit_seconds)
        return None

    data = json.loads(match.group(1))
    cache_file.write_text(json.dumps(data))
    time.sleep(rate_limit_seconds)
    return data


def build_remote_inventory(
    platform: str,
    listing_url: str,
    base_url: str,
    dat_path: Path,
    cache_dir: Path,
    out_path: Path,
    rate_limit_seconds: float = 0.5,
    refresh: bool = False,
    limit: int | None = None,
) -> dict:
    dat_index = load_dat_by_name(str(dat_path)) if dat_path.exists() else {}
    session = requests.Session()

    listing_cache = cache_dir / "listing.html"
    entries = fetch_listing(session, listing_url, listing_cache, refresh=refresh)
    if limit is not None:
        entries = entries[:limit]

    rom_cache_dir = cache_dir / "roms"
    raw_records = []
    skipped_junk = 0
    skipped_region = 0
    skipped_fetch_failed = 0

    for i, entry in enumerate(entries, start=1):
        try:
            rom = fetch_rom_metadata(
                session, base_url, entry["id"], rom_cache_dir, rate_limit_seconds, refresh=refresh
            )
        except requests.exceptions.RequestException:
            # Already retried with backoff inside fetch_rom_metadata -- this
            # one page is truly unreachable. Don't let it take down a
            # multi-hour run; count it and move on.
            skipped_fetch_failed += 1
            continue
        if rom is None:
            skipped_fetch_failed += 1
            continue

        # Checkpoint periodically to a side file (never out_path itself --
        # this is pre-dedup, a different shape than the final output, and
        # out_path should only ever hold a complete result). A crash losing
        # a few hundred entries' bookkeeping is a lot cheaper to redo than
        # losing the whole run -- confirmed the hard way once already (see
        # _get_with_retry). The per-page cache already makes redoing them
        # fast regardless; this just makes progress inspectable mid-run.
        if i % 200 == 0:
            checkpoint_path = cache_dir / "raw_records.checkpoint.json"
            checkpoint_path.write_text(json.dumps(raw_records, indent=2))

        file_name = rom.get("file_name", entry["file_name"])
        if _is_junk(file_name):
            skipped_junk += 1
            continue
        if rom.get("region") not in ALLOWED_REGIONS:
            skipped_region += 1
            continue

        sha1 = (rom.get("sha1") or "").lower()
        md5 = (rom.get("md5") or "").lower()
        crc32 = (rom.get("crc32") or "").lower()

        # Site hashes the outer .zip; the DAT hashes the inner disc image --
        # hash matching can't work across that boundary (confirmed against
        # a real title, not assumed). Match by exact filename instead: this
        # site's names already follow the same No-Intro/Redump convention
        # the DAT's own game_name uses.
        canonical_filename = Path(file_name).stem
        dat_entry = dat_index.get(canonical_filename)
        raw_records.append(
            {
                "platform": platform,
                "remote_id": rom.get("id", entry["id"]),
                "path": file_name,
                "canonical_filename": canonical_filename,
                "crc32": crc32,
                "md5": md5,
                "sha1": sha1,
                "sha256": (rom.get("sha256") or "").lower() or None,
                "dat_name": dat_entry.game_name if dat_entry else None,
                "dat_matched": dat_entry is not None,
                "region": [rom.get("region")] if rom.get("region") else [],
                "revision": None,
                "size_bytes": rom.get("size"),
                "magnet": rom.get("magnet"),
                "so_id": rom.get("so_id"),
                "torrent_path": rom.get("torrents"),
            }
        )

    # 1G1R-equivalent: one record per base title, preferring earlier
    # ALLOWED_REGIONS entries (USA over World) -- same policy as
    # --prefer-region USA,WORLD used for the cartridge archive tiers.
    def region_rank(record: dict) -> int:
        regions = record.get("region") or []
        for i, r in enumerate(ALLOWED_REGIONS):
            if r in regions:
                return i
        return len(ALLOWED_REGIONS)

    best_by_title: dict[str, dict] = {}
    for record in raw_records:
        key = base_title(record)
        existing = best_by_title.get(key)
        if existing is None or region_rank(record) < region_rank(existing):
            best_by_title[key] = record

    records = sorted(best_by_title.values(), key=lambda r: r["canonical_filename"])

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(records, indent=2))

    summary = {
        "total_listed": len(entries),
        "fetch_failed": skipped_fetch_failed,
        "junk_excluded": skipped_junk,
        "region_excluded": skipped_region,
        "before_dedup": len(raw_records),
        "after_dedup": len(records),
    }
    return {"records": records, "summary": summary}
