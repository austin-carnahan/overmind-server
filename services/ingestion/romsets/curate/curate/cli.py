import argparse
import os
from pathlib import Path
from urllib.parse import urlsplit

from .deploy import deploy_top
from .igdb import enrich_candidates
from .inventory import build_inventory
from .placeholders import build_placeholders
from .platforms import retroarch_name
from .playlist import build_playlist
from .rank import rank_candidates
from .remote_scan import build_remote_inventory
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


def cmd_placeholders(args):
    inventory_path = platform_dir(args.platform) / "inventory.json"
    out_dir = Path(args.out_dir) if args.out_dir else platform_dir(args.platform) / "placeholders"
    created = build_placeholders(inventory_path, out_dir)
    print(f"{created} placeholder(s) created -> {out_dir}")


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
    rom_dir = Path(args.rom_dir) if args.rom_dir else ARCHIVE_ROOT / args.platform
    identified = scrape_platform(
        args.platform,
        inventory_path,
        rom_dir,
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
    inventory_path = platform_dir(args.platform) / "inventory.json"
    overrides_path = CURATION_ROOT / "overrides.json"
    out_dir = platform_dir(args.platform)
    top = select_top(
        identified_path, candidates_path, overrides_path, out_dir, args.platform, args.limit, inventory_path
    )
    print(f"selected {len(top)} -> {out_dir / 'top-100.json'}")


def cmd_deploy(args):
    top_100_path = platform_dir(args.platform) / "top-100.json"
    result = deploy_top(top_100_path, ARCHIVE_ROOT / args.platform, LIBRARY_ROOT / args.platform)
    print(
        f"copied {len(result['copied'])}, removed {len(result['removed'])} stale file(s) "
        f"-> {LIBRARY_ROOT / args.platform}"
    )


def cmd_remote_scan(args):
    dat_path = Path(args.dat) if args.dat else DATS_ROOT / f"{args.platform}.dat"
    base_url = args.base_url
    if base_url is None:
        parts = urlsplit(args.listing_url)
        base_url = f"{parts.scheme}://{parts.netloc}"
    cache_dir = CURATION_ROOT / "cache" / "remote-scan" / args.platform
    out_path = platform_dir(args.platform) / "inventory.json"
    result = build_remote_inventory(
        args.platform,
        args.listing_url,
        base_url,
        dat_path,
        cache_dir,
        out_path,
        rate_limit_seconds=args.rate_limit_seconds,
        refresh=args.refresh,
        limit=args.limit,
    )
    s = result["summary"]
    print(
        f"{s['total_listed']} listed, {s['fetch_failed']} fetch-failed, "
        f"{s['junk_excluded']} junk-excluded, {s['region_excluded']} region-excluded, "
        f"{s['before_dedup']} survived filtering, {s['after_dedup']} after 1G1R dedup -> {out_path}"
    )


def cmd_playlist(args):
    library_dir = LIBRARY_ROOT / args.platform
    out_path = platform_dir(args.platform) / f"{retroarch_name(args.platform)}.lpl"
    count = build_playlist(args.platform, library_dir, args.device_rom_dir, out_path)
    print(f"{count} items -> {out_path} (db_name/filename: {retroarch_name(args.platform)}.lpl)")


def main():
    parser = argparse.ArgumentParser(prog="curate")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("inventory")
    p.add_argument("--platform", required=True)
    p.add_argument("--dat")
    p.set_defaults(func=cmd_inventory)

    p = sub.add_parser("placeholders")
    p.add_argument("--platform", required=True)
    p.add_argument("--out-dir", help="Defaults to curation/<platform>/placeholders")
    p.set_defaults(func=cmd_placeholders)

    p = sub.add_parser("scrape")
    p.add_argument("--platform", required=True)
    p.add_argument("--rom-dir", help="Override the ROM directory Skyscraper scans (e.g. a placeholders dir for remote-sourced platforms)")
    p.add_argument("--refresh", action="store_true")
    p.set_defaults(func=cmd_scrape)

    p = sub.add_parser("rank")
    p.add_argument("--platform", required=True)
    p.add_argument("--candidates", type=int, default=300)
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

    p = sub.add_parser("remote-scan")
    p.add_argument("--platform", required=True)
    p.add_argument("--listing-url", required=True, help="Browse/listing page URL for this platform")
    p.add_argument("--base-url", help="Defaults to the scheme+host of --listing-url")
    p.add_argument("--dat")
    p.add_argument("--rate-limit-seconds", type=float, default=0.75, help="Delay between per-title page fetches")
    p.add_argument("--limit", type=int, help="Only scan the first N listing entries (testing)")
    p.add_argument("--refresh", action="store_true")
    p.set_defaults(func=cmd_remote_scan)

    p = sub.add_parser("playlist")
    p.add_argument("--platform", required=True)
    p.add_argument(
        "--device-rom-dir",
        required=True,
        help="Absolute path on the target device where these ROMs live, e.g. /storage/DF3B-5BC7/roms/genesis",
    )
    p.set_defaults(func=cmd_playlist)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
