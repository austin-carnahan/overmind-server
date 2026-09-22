"""Shared title normalization: strip No-Intro-style region/language/edition
tags (e.g. "(USA)", "(Rev 1)", "(Sega Channel)") to get a bare title for
matching across ScreenScraper/IGDB/override/dedup lookups. Was duplicated
three times (igdb.py, select.py, overrides.py) before this -- centralized
to keep them from drifting apart.
"""

import re

_TAG_RE = re.compile(r"\s*\([^)]*\)")

# Matches a No-Intro/Redump-style parenthetical tag containing a junk
# keyword anywhere within it (not just at the start), so both "(Demo)" and
# oddly-worded Redump tags like "(Trade Demo)" or "(Playable Game Preview)"
# are caught by the same pattern.
JUNK_TAG_RE = re.compile(
    r"\([^)]*\b(?:Beta|Demo|Proto(?:type)?|Sample|Program|Unl|Pirate|Aftermarket|Bad ?Dump|Preview)\b[^)]*\)",
    re.IGNORECASE,
)

_DISC_TAG_RE = re.compile(r"\(Disc\s*(\d+)\)", re.IGNORECASE)


def clean_title(raw: str) -> str:
    return _TAG_RE.sub("", raw or "").strip()


def is_junk_title(raw: str) -> bool:
    return bool(JUNK_TAG_RE.search(raw or ""))


def disc_number(raw: str) -> int | None:
    match = _DISC_TAG_RE.search(raw or "")
    return int(match.group(1)) if match else None


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
