# curate

On-demand Python CLI implementing the
[romset curation pipeline](../../../../design-notes/romset-curation-pipeline.md):
archive tier → ScreenScraper identification → candidate ranking → IGDB
enrichment (candidates only) → Bayesian score → top-100 manifest → library
tier promotion.

Not a service — nothing here runs continuously. Each stage is a subcommand,
run on demand via Docker, like Igir already is (see
[Igir workflow](../../../../runbooks/romsets/igir.md)):

```sh
docker build -t overmind-curate .
docker run --rm --env-file config.env \
  -v /mnt/library/romsets-archive:/archive:ro \
  -v /mnt/library/romsets:/library \
  -v /var/lib/overmind/romarr/dats:/dats:ro \
  -v /var/lib/overmind/curation:/curation \
  overmind-curate <subcommand> --platform genesis [options]
```

**I/O-heavy stages (`deploy-disc`, and any large `scrape`/`inventory` run)
should add `--blkio-weight 100 --cpu-shares 256`** to that `docker run`
(default weight/shares are 500/1024) so they yield to overmind-01's other
services under contention, confirmed necessary the hard way: two
concurrent `deploy-disc` copies (~110GB combined) pushed load average to
7.4 on this 4-core Pi and made Radarr's web UI unresponsive. Shell-level
`nice`/`ionice` on the `docker run` command does **not** work for this —
it doesn't propagate into the container's actual process, which Docker's
own daemon spawns separately; the container-level flags are the only
mechanism that actually works. Also: never run two heavy `curate`
invocations concurrently on this host regardless — serialize them, one
`docker run` at a time, matching [AGENTS.md's guidance](../../../../AGENTS.md)
that heavy work belongs on the future mini-PC, not this Pi, and needs
handling conservatively until that migration happens.

`/var/lib/overmind/curation` holds the persistent cache (ScreenScraper/IGDB
raw responses) and generated manifests — small, low-write state per the
[storage layout](../../../../design-notes/storage-layout.md) convention, not
Library content.

**`<platform>/identified.json` and `cache/skyscraper-resources/` are
archive-tier-durable — never pruned, never treated as disposable scratch.**
They're the output of `scrape`, the one genuinely expensive/slow stage
(rate-limited against a real third-party API, taking anywhere from minutes
to hours depending on platform size); everything downstream (`rank`,
`enrich-igdb`, `score`, `select`) is cheap to regenerate from them in
seconds. Same durability posture as `/mnt/library/romsets-archive` itself —
re-running `scrape` without `identified.json`/the resource cache already
present means redoing real API work, not a quick rebuild, so don't delete
or exclude either path from backups on the assumption they're "just cache."
`inventory.json`/`candidates.json`/`top-100.*` are genuinely cheap
derivatives and don't need this treatment.

## ScreenScraper access goes through Skyscraper

The `scrape` stage shells out to [Skyscraper](https://github.com/Gemba/skyscraper)
(the actively-maintained fork) rather than calling the ScreenScraper API
directly. ScreenScraper's own developer credentials are gated behind an
approval process that's impractical for a small personal project; Skyscraper
ships with its own registered developer credentials compiled in, so it only
needs a normal, freely created ScreenScraper account
(`SCREENSCRAPER_SSID`/`SCREENSCRAPER_SSPASSWORD`). The image builds
Skyscraper from source using its own official `docker/Dockerfile` recipe
(adapted below to also carry the Python `curate` package in the same
image, so `scrape` can just shell out to the `Skyscraper` binary without a
second container). Output is parsed from the `gamelist.xml` Skyscraper
generates, joined back to our inventory by archive-tier path.

## Stages

| Subcommand | Needs | Reads | Writes |
| --- | --- | --- | --- |
| `inventory` | nothing external | archive tier + DAT file | `curation/<platform>/inventory.json` |
| `scrape` | ScreenScraper account | `inventory.json` | `curation/<platform>/identified.json`, response cache |
| `rank` | nothing external | `identified.json` | `curation/<platform>/candidates.json` |
| `enrich-igdb` | Twitch/IGDB app credentials | `candidates.json` | `candidates.json` (in place), `ambiguous-matches.csv` |
| `score` | nothing external | `candidates.json` | `candidates.json` (scored, in place) |
| `select` | nothing external | scored `candidates.json`, `overrides.json` | `top-100.json`, `top-100.csv`, `all-candidates.csv`, `unmatched-*.csv` |
| `deploy` | nothing external | `top-100.json`, archive tier | copies into library tier |
| `remote-scan` | nothing external | Minerva-Myrient-style listing page | `curation/<platform>/inventory.json` |
| `queue-download` | Transmission RPC (disc platforms only) | `top-100.json` | adds/selects one torrent in Transmission |
| `deploy-disc` | nothing external (disc platforms only) | `top-100.json`, the romset Inbox | copies into library tier |
| `convert-chd` | `chdman` (disc platforms only) | deployed library tier (ZIPs) | in-place CHD/M3U library, `curation/<platform>/chd-convert-log.json` |
| `playlist` | nothing external | deployed library tier | `curation/<platform>/<RetroArch name>.lpl` |

## Disc-based platforms (remote-scan / queue-download)

For platforms whose full archive is too large to download wholesale
(PSX, Dreamcast, ...) there's no local archive tier: `remote-scan` scans a
Minerva/Myrient-style catalog's per-title pages directly (crc32/md5/sha1/
size/region/a shared per-system torrent's file index), producing an
inventory equivalent to the cartridge platforms' Igir-built one, without
downloading any disc content. `scrape` then runs against zero-byte
placeholder stubs (`placeholders` stage) instead of real ROM files --
confirmed Skyscraper identifies/rates by filename alone. `select` still
applies as normal; the one difference is each selected record may carry a
`disc_files` list for multi-disc releases (all sibling discs, looked up
from `inventory.json`, not the scraped/rated pool -- their own filenames/
hashes are already known there, no ScreenScraper identification needed
just to know they exist).

`queue-download` adds the torrent: every title in one platform's catalog
shares one torrent (one info-hash), so it adds that single torrent to
Transmission **paused**, waits for its metadata (file list) to arrive from
the swarm, then sets `files-wanted` to exactly the selected titles' file
indices (`so_id`, plus every disc's `so_id` for multi-disc releases) before
starting it -- never the whole multi-terabyte archive. Needs
`TRANSMISSION_RPC_USERNAME`/`TRANSMISSION_RPC_PASSWORD` in `config.env`
(from Transmission's own `settings.json` `rpc-username`/`rpc-password`);
`--download-dir` defaults to `/romsets-staging`, the path as
*Transmission's own container* sees it (its bind-mounted romset Inbox, see
[services/transmission/README.md](../../../transmission/README.md)), not a
`curate`-local path -- `curate` only talks to Transmission over RPC, it
never touches torrent data directly.

`deploy-disc` is the actual final step, run once the torrent finishes:
disc platforms have no archive tier (unlike cartridge platforms' `deploy`,
which reads from one), so this promotes straight from the Inbox
(`$INBOX_ROOT/Minerva_Myrient/Redump/<RetroArch canonical name>/`, e.g.
`Sony - PlayStation/`) into the library tier -- same selected-title-plus-
every-disc-sibling set `queue-download` used, sourced from `top-100.json`
again rather than re-deriving it. Unlike `deploy`, a selected file missing
from the Inbox is a hard error here, not a silent skip: `queue-download`
already confirmed every `so_id` mapped to a real torrent file, so a
missing file at this stage means something went wrong (torrent not
actually finished, wrong `INBOX_ROOT` mount, ...), not an expected gap.

`convert-chd` is optional, run whenever the M3U/CHD disc-swapping
experience is wanted (a plain single disc launched directly and swapped
mid-game via RetroArch's Disc Control → Disc Image Append already works
against the raw ZIPs `deploy-disc` leaves behind — confirmed against a
real multi-disc PS1 title -- CHD is only needed for the nicer "launch one
`.m3u`, cycle discs by index" experience). Converts **in place**: reads
the flat `.zip` files `deploy-disc` left in the library tier and replaces
them one disc at a time, per-disc pipeline: hash the zip → test its
integrity → extract to an isolated scratch dir → find the `.cue` → verify
every file it references exists (handles PSX's single-BIN and
Dreamcast's multi-BIN/track layouts identically) → `chdman createcd` →
`chdman verify` → atomically promote the verified `.chd` into the
library → only then delete the source `.zip`. A failed disc leaves its
source `.zip` untouched and logs the failure to
`curation/<platform>/chd-convert-log.json`; it never stops the rest of
the batch. Multi-disc games land in their own subfolder with an `.m3u`
listing the discs in order; single-disc games are just a flat `.chd`.
Output names are normalized (`Final Fantasy IX (USA) (Disc 1) (Rev 1)` →
`Final Fantasy IX (USA) (Disc 1).chd`) — keeps the title and region tag,
drops everything else, matching the "no name cleanup at deploy time"
gap identified when checking `playlist.py`'s labels (see that stage's
own note below). `chdman` (from Ubuntu's `mame-tools` package) needs to
be on the image; nothing else external.

Per this project's Pi-load-management convention (see the `deploy-disc`
note above): `chdman createcd` is real CPU-bound transcoding-class work. `convert-chd` already processes one disc fully
before starting the next (never parallel), but still add
`--blkio-weight 100 --cpu-shares 256` to the `docker run` and never run
it alongside another heavy `curate` job.

## RetroArch playlist naming

`playlist` builds a `.lpl` using RetroArch's own canonical per-platform
names (`curate/platforms.py`'s `RETROARCH_SYSTEM_NAMES`) — RetroArch
matches its XMB icon and thumbnail set to a playlist's exact base filename
(and each item's `db_name`), not our own internal platform key, so
spelling/capitalization/spaces/hyphens must match Libretro's own
database/thumbnail-repo naming exactly:

| Internal key | RetroArch canonical name |
| --- | --- |
| `genesis` | `Sega - Mega Drive - Genesis` |
| `nes` | `Nintendo - Nintendo Entertainment System` |
| `snes` | `Nintendo - Super Nintendo Entertainment System` |
| `n64` | `Nintendo - Nintendo 64` |
| `psx` | `Sony - PlayStation` |
| `dreamcast` | `Sega - Dreamcast` |

ROM folder names (both `/mnt/library/romsets/<platform>` on the server and
`/storage/<device>/roms/<platform>` on the device) stay simple and never
need to match this table — only the playlist filename, each item's
`db_name`, and the `thumbnails/<name>/` directory RetroArch expects
alongside `playlists/` do.

`playlist` has no visibility into what R-Shop has actually downloaded to a
given device — it builds a playlist entry for every title in the deployed
library tier, pointed at `--device-rom-dir`. Entries for titles not yet
downloaded to that specific device will fail to launch until R-Shop
downloads them; regenerate device-side (listing the real ROM directory,
as was done for the initial Genesis playlist) instead if a playlist
matching only currently-downloaded titles is wanted. The generated file
still needs to be pushed to the device manually (`adb push` into
`/storage/emulated/0/RetroArch/playlists/`) — this tool has no device
access from inside its Docker container.

Every stage reads/caches to disk so reruns are cheap: `scrape` and
`enrich-igdb` skip anything already cached by hash/identity, so a rerun
after adding new archive-tier games only fetches what's new. Force a
refresh of external data with `--refresh` on the relevant subcommand — this
is a separate, explicit choice, never automatic.

`rank --candidates` defaults to 300 (raised from 150 after PSX): a
narrower pool cuts candidates by raw ScreenScraper rating *before*
IGDB/dedup/override filtering ever runs, so a title can lose its shot at
the top-100 purely for not making that first, cruder cut — confirmed
directly, several well-regarded PSX titles (Xenogears, Tactics Ogre,
Valkyrie Profile, Tomb Raider II, ...) were entirely absent from the
150-candidate pool and only appeared once widened to 250. `enrich-igdb`
and `score` scale with pool size but stay cheap (cached/rate-limited API
calls only for genuinely new entries), so there's no real cost to
defaulting wide.

## Credentials

Copy `config.env.example` to `config.env` (gitignored, never commit it) and
fill in:

- `SCREENSCRAPER_SSID` / `SCREENSCRAPER_SSPASSWORD` — a normal, free
  ScreenScraper account. No separate developer credentials are needed;
  Skyscraper supplies its own.
- `IGDB_CLIENT_ID` / `IGDB_CLIENT_SECRET` — from a Twitch developer
  application (IGDB auth rides on Twitch's OAuth); free for noncommercial
  use.

Two things are still unverified pending real accounts/build: `enrich-igdb`
follows IGDB's documented v4 query contract but hasn't run against the live
API yet; and the Skyscraper build step in the Dockerfile (adapted from
Skyscraper's own official recipe) hasn't been build-tested here — no Docker
daemon was available in the environment that wrote it. Treat the first real
`docker build` and first real `scrape`/`enrich-igdb` runs as verification,
not just execution.

## Example: Genesis, end to end

```sh
docker run --rm --env-file config.env -v ... overmind-curate inventory --platform genesis --dat /dats/genesis.dat
docker run --rm --env-file config.env -v ... overmind-curate scrape --platform genesis
docker run --rm --env-file config.env -v ... overmind-curate rank --platform genesis --candidates 300
docker run --rm --env-file config.env -v ... overmind-curate enrich-igdb --platform genesis
docker run --rm --env-file config.env -v ... overmind-curate score --platform genesis
docker run --rm --env-file config.env -v ... overmind-curate select --platform genesis --limit 100
docker run --rm --env-file config.env -v ... overmind-curate deploy --platform genesis
```

`scrape` maps our platform names to Skyscraper's own platform keys (e.g.
`genesis` → `megadrive`) via `PLATFORM_MAP` in `curate/screenscraper.py` —
extend that dict before curating a new platform; check
[Skyscraper's PLATFORMS.md](https://github.com/Gemba/skyscraper/blob/master/docs/PLATFORMS.md)
for the right key and aliases.
