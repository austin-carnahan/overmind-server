# Romset curation pipeline: archive → library

**Status:** PARTIAL — see [status legend](README.md#status-legend). This is
the answer to the "Curation strategies" open problem in
[runbooks/romsets/igir.md](../runbooks/romsets/igir.md#curation-strategies-archive--library)
and [services/ingestion/romsets/README.md](../services/ingestion/romsets/README.md#curation-strategies-archive--library).
Implemented as a Python CLI at
[services/ingestion/romsets/curate](../services/ingestion/romsets/curate/README.md);
the credential-free stages (`inventory`, `rank`, `score`, `select`,
`deploy`) are built and tested against synthetic fixtures. The
ScreenScraper (`scrape`) and IGDB (`enrich-igdb`) stages are written against
each API's documented contract but not yet exercised against the live APIs
— that needs a ScreenScraper account and a Twitch developer application,
neither obtained yet.

## Objective

For every supported platform:

- Maintain the complete, verified **archive tier** on Overmind (already
  built for Genesis — see AGENTS.md rule 3).
- Produce a browsable **library tier** of roughly 100 highest-ranked games.
- Use only free/noncommercial-access data sources.
- Make the process deterministic and repeatable.
- Preserve every source response and scoring input.
- Never delete a game from the archive tier merely because it doesn't make
  the library tier.

## Central idea

Igir already establishes file-level identity (checksum, canonical name,
region/language, 1G1R) when promoting into the archive tier — that part is
done. ScreenScraper establishes *game* identity (hash → clean name,
metadata, artwork, a first rating) for every archive-tier ROM. IGDB adds a
**second** rating, but only for the games that are already in real
contention for the top 100 — not the whole archive. We do not build a
custom ROM-name-matching system unless both sources fail on a given game.

Restricting IGDB to candidates only is a deliberate simplification from an
earlier draft of this plan, which ran full IGDB matching + enrichment
across the entire archive tier (potentially 900+ games per platform).
That's a lot of fuzzy-matching surface area — the most fragile,
human-attention-heavy part of the whole pipeline — for games that have no
realistic path into the top 100 anyway. Ranking by ScreenScraper rating
alone first and only fetching IGDB for the survivors keeps the IGDB
matching workload to the size of the actual decision (~150-200
games/platform) instead of the size of the archive.

**ScreenScraper access, revised 2026-09-20:** use
[Skyscraper](https://github.com/Gemba/skyscraper) (the actively-maintained
fork — the original `muldjord/skyscraper` explicitly says it's unmaintained
and points there) as the actual ScreenScraper client, not direct API calls.
ScreenScraper's own developer credentials (`devid`/`devpassword`) are
gated behind an application process that's difficult to get approved for a
small personal project. Skyscraper ships with its own registered developer
credentials compiled in, so an end user only needs a normal, freely
created ScreenScraper account (`ssid`/`sspassword`, set via `-u`) —
confirmed in Skyscraper's own docs ("User credential support: Yes, and
strongly recommended, but not required" — meaning the *user* credential,
not a developer one). This restores the original design's intent (see the
implementation README for the brief period this repo instead called the
ScreenScraper API directly, which has been reverted).

## Pipeline

```text
Archive tier (/mnt/library/romsets-archive/<system>, already Igir-verified)
    ↓
Stage A: ScreenScraper hash identification, full archive
    ↓
Clean identity + metadata + first rating, for every archive-tier game
    ↓
Stage B: rank by ScreenScraper rating, take top ~150-200 candidates
    ↓
Stage C: IGDB rating enrichment, candidates only
    ↓
Bayesian combined score, candidates only
    ↓
Top-100 manifest
    ↓
Library tier (/mnt/library/romsets/<system>, promoted from manifest)
```

## Stage A: ScreenScraper identification (full archive)

Run this against every game in the archive tier — it's needed regardless of
curation, since it supplies the display names, artwork, and metadata that
RetroArch/R-Shop show, not just the first rating.

Use [Skyscraper](https://github.com/Gemba/skyscraper) — the
actively-maintained fork — as the command-line ScreenScraper client, built
via Skyscraper's own official `docker/Dockerfile`. Skyscraper's
`screenscraper` module identifies by checksum first, falling back to
filename, and only needs a normal user account (`-u ssid:sspassword`) —
its bundled developer credentials are what actually talk to the
ScreenScraper API. Output is an EmulationStation-format `gamelist.xml`,
joined back to our inventory by path (the archive-tier filenames Skyscraper
was given as input).

For every archive-tier ROM:

- Skyscraper computes/caches the ROM's checksum itself (its cache is keyed
  by hash, not just filename) and queries ScreenScraper, preferring
  checksum identification over filename search.
- Skyscraper retrieves metadata and media and maintains its own resource
  cache on disk — reruns should reuse it; `--cache refresh` (or an
  equivalent explicit flag) is a separate, explicit choice.
- From the generated `gamelist.xml`, collect: clean display name,
  description, release date, developer, publisher, genre, player count,
  community rating, and box art path. (Skyscraper's own resource cache has
  finer-grained fields including its internal game ID, but parsing that
  cache directly instead of `gamelist.xml` is a possible future
  enhancement, not required for this pipeline.)

**Known constraint:** ScreenScraper's free/anonymous tier is aggressively
rate-limited (often ~1 concurrent thread). A full-archive pass across
multiple platforms should be expected to take real wall-clock time —
budget for it, don't assume it completes in minutes.

The canonical identity record per game:

```json
{
  "platform": "genesis",
  "rom_sha1": "...",
  "dat_name": "Sonic the Hedgehog",
  "display_name": "Sonic the Hedgehog",
  "release_year": 1991,
  "screenscraper_rating": 0.84,
  "identity_method": "path_matched_gamelist_entry",
  "identity_confidence": 1.0
}
```

`display_name` (ScreenScraper's clean name, via Skyscraper's
`gamelist.xml`) is what RetroArch, R-Shop, and generated reports show.
`dat_name` (Igir's canonical DAT name) is preserved alongside it for
auditing, never overwritten. No `screenscraper_id` field — `gamelist.xml`
doesn't carry ScreenScraper's internal game ID; only its cache does (see
Stage A note above).

Identity hierarchy, in order — a game identified by both Igir and
ScreenScraper needs no manual cleanup:

1. Igir DAT checksum match (already done at archive promotion).
2. A `gamelist.xml` entry at the matching archive-tier path (Skyscraper
   identified it, by checksum or filename internally).
3. Normalized filename match against `gamelist.xml` if the path didn't
   line up exactly.
4. Manual exception (`overrides.json`, see below).

## Stage B: rank by ScreenScraper rating, cut to candidates

Normalize ScreenScraper's 0.0-1.0 rating to 0-100. Sort each platform's
identified games by this rating alone. Take the top ~150-200 (roughly 1.5-2x
the final target) as **candidates** — the only games that proceed to Stage
C. Everything else stays in the archive tier, fully identified and playable
if browsed directly, just not IGDB-enriched or eligible for the automatic
top 100 in this pass.

The cutoff is a size, not a hard rule — widen it if a platform's
ScreenScraper ratings are sparse or bunched near the cutoff, so a game that
would clearly place in the final 100 given IGDB data isn't excluded by
ScreenScraper noise alone.

## Stage C: IGDB rating enrichment (candidates only)

Query IGDB (free API, noncommercial use, Twitch developer auth) using the
already-established ScreenScraper identity — only for the ~150-200
candidates from Stage B.

Request: `name`, `alternative_names`, `platforms`, `first_release_date`,
`rating`, `rating_count`, `aggregated_rating`, `aggregated_rating_count`,
`slug`. Use `rating` and `rating_count` (IGDB user rating and vote count)
for the initial scoring system.

Matching order:

1. Same normalized title, platform, and approximate release year.
2. Alternative title, same platform, and approximate year.
3. Same title and platform.
4. Fuzzy title match only when platform and year agree.
5. Otherwise: unmatched.

Do not auto-accept a fuzzy match on title similarity alone. Automatic
thresholds:

- Exact title + platform: accept.
- Alias + platform + year within one year: accept.
- Fuzzy title ≥ 95% + platform + year within one year: accept.
- Anything weaker: review (`ambiguous-matches.csv`, see Stage D output).

Store the selected IGDB ID so later runs never rematch. Because this only
runs on ~150-200 games per platform instead of the full archive, manual
review load stays proportional to the actual curation decision.

## Combining ratings: Bayesian score

Missing means missing — never treat an unpopulated rating as zero.

Per platform, compute a prior `C` = mean rating of sufficiently-matched
games on that platform (candidates only is fine, since that's the
population being ranked). If a platform lacks enough data, use a fixed
cross-platform prior of 70.

```
score = (C·25 + S·10 + I·min(V,100)) / (25 + 10 + min(V,100))
```

Where `C` = platform prior, `S` = ScreenScraper rating (0-100), `I` = IGDB
user rating, `V` = IGDB rating count. 25/10/100 are starting weights (prior
strength, ScreenScraper's fixed pseudo-vote weight, and the IGDB vote-count
cap), not derived constants — expect to retune them after looking at a
platform's actual top-100 output rather than trying to get them exactly
right up front.

If ScreenScraper is missing (shouldn't happen for a candidate, since
Stage B selected on it, but possible after Stage A cache gaps):
`(C·25 + I·min(V,100)) / (25 + min(V,100))`.

If IGDB is missing (unmatched at Stage C): `(C·25 + S·10) / 35`.

Games with neither rating stay in the archive tier but don't enter the
automatic top 100.

## Stage D: select the top 100

Per platform: filter to verified retail games, sort by Bayesian score
descending, use rating coverage as first tiebreaker, then release year and
canonical title for deterministic final ordering. Take the first 100.

```text
curation/
  genesis/
    all-candidates.csv
    top-100.csv
    top-100.json
    unmatched-screenscraper.csv
    unmatched-igdb.csv
    ambiguous-matches.csv
    overrides.json
```

Each ranked record shows: rank, canonical name, display name, ROM hash,
ScreenScraper rating, IGDB rating, IGDB rating count, platform prior, final
score, match methods/IDs, and any manual override.

## Promotion into the library tier

`top-100.json` is the authoritative selection — not a hand-maintained
folder. From it:

```text
/mnt/library/romsets-archive/genesis/   ← complete verified archive tier (unchanged)
curation/genesis/top-100.json           ← authoritative selection
/mnt/library/romsets/genesis/           ← library tier, promoted from the manifest
```

The archive tier is never touched by this step; promotion only copies the
selected 100 into the library tier (the tier actually exposed via
SMB/R-Shop).

## Exceptions

Manual decisions live in a version-controlled `overrides.json`, never as
hand-edited `gamelist.xml` entries:

```json
{
  "genesis": {
    "Some Game": {
      "igdb_id": 1234,
      "force_include": false,
      "force_exclude": false,
      "note": "Resolved alternate North American title"
    }
  }
}
```

Overrides can assign a ScreenScraper/IGDB identity, correct a platform
mapping, force-include/exclude a game, or choose between revisions.

## Reproducibility

Pin and preserve: Igir version, DAT versions/checksums, platform mapping
file, ScreenScraper/Skyscraper config, cached ScreenScraper responses,
cached IGDB responses, scoring constants, match overrides, and generated
manifests. Normal reruns use cached metadata; refreshing external ratings
is a separate explicit command.

Conceptual CLI shape:

```text
curate inventory genesis
curate scrape genesis            # Stage A, full archive
curate rank genesis              # Stage B, cut to candidates
curate enrich-igdb genesis       # Stage C, candidates only
curate score genesis             # Bayesian combine
curate select genesis --limit 100
curate deploy genesis --target fire-stick
```

## Division of responsibility

| Component | Responsibility |
|---|---|
| Igir | Verify files, DAT matching, canonical naming, 1G1R and region selection — archive-tier promotion |
| ScreenScraper | Hash-based game identity, clean metadata, artwork, and first rating — full archive |
| Skyscraper | Automate ScreenScraper retrieval and cache results |
| IGDB | Supply the second rating and its vote count — candidates only |
| Curation script | Rank by ScreenScraper, cut to candidates, join IGDB, score, emit top-100 manifest |
| R-Shop | Browse and manage the device-local (library-tier) game cache |
| RetroArch/emulators | Launch and play games |
| Overmind | Hold the archive tier, metadata cache, and generated manifests |
