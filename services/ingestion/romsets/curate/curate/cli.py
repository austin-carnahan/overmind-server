import argparse
import os
from pathlib import Path

from .deploy import deploy_top
from .igdb import enrich_candidates
from .inventory import build_inventory
from .rank import rank_candidates
from .scoring import score_candidates
from .screenscraper import scrape_platform
from .select import select_top

CURATION_ROOT = Path(os.environ.get("CURATION_ROOT", "/curation"))
ARCHIVE_ROOT = Path(os.environ.get("ARCHIVE_ROOT", "/archive"))
LIBRARY_ROOT = Path(os.environ.get("LIBRARY_ROOT", "/library"))
DATS_ROOT = Path(os.environ.get("DATS_ROOT", "/dats"))


def platform_dir(platform: str) -> Path:
    return CURATION_ROOT / platform


def cmd_inventory(args):
    dat_path = Path(args.dat) if args.dat else DATS_ROOT / f"{args.platform}.dat"
    out_path = platform_dir(args.platform) / "inventory.json"
    records = build_inventory(args.platform, ARCHIVE_ROOT / args.platform, dat_path, out_path)
    unmatched = sum(1 for r in records if not r["dat_matched"])
    print(f"{len(records)} archive files hashed, {unmatched} not found in the DAT -> {out_path}")


def cmd_scrape(args):
    creds = {
        "ssid": os.environ["SCREENSCRAPER_SSID"],
        "sspassword": os.environ["SCREENSCRAPER_SSPASSWORD"],
    }
    inventory_path = platform_dir(args.platform) / "inventory.json"
    gamelist_dir = CURATION_ROOT / "cache" / "skyscraper-gamelist" / args.platform
    media_dir = gamelist_dir / "media"
    cache_dir = CURATION_ROOT / "cache" / "skyscraper-resources"
    out_path = platform_dir(args.platform) / "identified.json"
    identified = scrape_platform(
        args.platform,
        inventory_path,
        ARCHIVE_ROOT / args.platform,
        gamelist_dir,
        media_dir,
        cache_dir,
        creds,
        out_path,
        refresh=args.refresh,
    )
    matched = sum(1 for r in identified if r["identity_method"] != "unmatched")
    print(f"{matched}/{len(identified)} identified -> {out_path}")


def cmd_rank(args):
    identified_path = platform_dir(args.platform) / "identified.json"
    out_path = platform_dir(args.platform) / "candidates.json"
    candidates = rank_candidates(identified_path, out_path, args.candidates)
    print(f"{len(candidates)} candidates (top {args.candidates} by ScreenScraper rating) -> {out_path}")


def cmd_enrich_igdb(args):
    creds = {
        "client_id": os.environ["IGDB_CLIENT_ID"],
        "client_secret": os.environ["IGDB_CLIENT_SECRET"],
    }
    candidates_path = platform_dir(args.platform) / "candidates.json"
    cache_dir = CURATION_ROOT / "cache" / "igdb" / args.platform
    ambiguous_out = platform_dir(args.platform) / "ambiguous-matches.csv"
    candidates = enrich_candidates(candidates_path, cache_dir, creds, ambiguous_out, refresh=args.refresh)
    matched = sum(1 for c in candidates if c["igdb_match_method"] != "unmatched")
    print(f"{matched}/{len(candidates)} IGDB-matched -> {candidates_path}")


def cmd_score(args):
    candidates_path = platform_dir(args.platform) / "candidates.json"
    score_candidates(candidates_path)
    print(f"scored -> {candidates_path}")


def cmd_select(args):
    identified_path = platform_dir(args.platform) / "identified.json"
    candidates_path = platform_dir(args.platform) / "candidates.json"
    overrides_path = CURATION_ROOT / "overrides.json"
    out_dir = platform_dir(args.platform)
    top = select_top(identified_path, candidates_path, overrides_path, out_dir, args.platform, args.limit)
    print(f"selected {len(top)} -> {out_dir / 'top-100.json'}")


def cmd_deploy(args):
    top_100_path = platform_dir(args.platform) / "top-100.json"
    deployed = deploy_top(top_100_path, ARCHIVE_ROOT / args.platform, LIBRARY_ROOT / args.platform)
    print(f"copied {len(deployed)} files into {LIBRARY_ROOT / args.platform}")


def main():
    parser = argparse.ArgumentParser(prog="curate")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("inventory")
    p.add_argument("--platform", required=True)
    p.add_argument("--dat")
    p.set_defaults(func=cmd_inventory)

    p = sub.add_parser("scrape")
    p.add_argument("--platform", required=True)
    p.add_argument("--refresh", action="store_true")
    p.set_defaults(func=cmd_scrape)

    p = sub.add_parser("rank")
    p.add_argument("--platform", required=True)
    p.add_argument("--candidates", type=int, default=150)
    p.set_defaults(func=cmd_rank)

    p = sub.add_parser("enrich-igdb")
    p.add_argument("--platform", required=True)
    p.add_argument("--refresh", action="store_true")
    p.set_defaults(func=cmd_enrich_igdb)

    p = sub.add_parser("score")
    p.add_argument("--platform", required=True)
    p.set_defaults(func=cmd_score)

    p = sub.add_parser("select")
    p.add_argument("--platform", required=True)
    p.add_argument("--limit", type=int, default=100)
    p.set_defaults(func=cmd_select)

    p = sub.add_parser("deploy")
    p.add_argument("--platform", required=True)
    p.set_defaults(func=cmd_deploy)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
