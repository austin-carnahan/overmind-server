"""Shared title normalization: strip No-Intro-style region/language/edition
tags (e.g. "(USA)", "(Rev 1)", "(Sega Channel)") to get a bare title for
matching across ScreenScraper/IGDB/override/dedup lookups. Was duplicated
three times (igdb.py, select.py, overrides.py) before this -- centralized
to keep them from drifting apart.
"""

import re

_TAG_RE = re.compile(r"\s*\([^)]*\)")


def clean_title(raw: str) -> str:
    return _TAG_RE.sub("", raw or "").strip()


def base_title(record: dict) -> str:
    """Normalized, lowercased title for a ROM record -- the join key for
    dedup and override matching."""
    raw = record.get("dat_name") or record.get("canonical_filename") or record.get("display_name") or ""
    return clean_title(raw).lower()


def plainness(record: dict) -> int:
    """Fewer parenthetical tags = more likely the plain retail release
    rather than a compilation/rerelease/Sega Channel variant. Used to pick
    one canonical file when an override title matches several editions."""
    raw = record.get("canonical_filename") or ""
    return len(re.findall(r"\([^)]*\)", raw))
