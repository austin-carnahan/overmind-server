# Igir Workflow

Use Igir primarily for authoritative validation, canonical naming, and curated outputs.

## Running Igir (no host install needed)

No `services/igir/` exists and none is needed — Igir has no official Docker
image, but runs fine via the generic Node image. **Use `node:lts`, not
`node:lts-alpine`** — Alpine's musl libc segfaults on Igir's native
postinstall on at least aarch64 (confirmed on overmind-01); the standard
glibc-based image works without issue.

```sh
docker run --rm \
  -v /var/lib/overmind/romarr/dats:/dats:ro \
  -v /var/spool/overmind/media/romsets/<system>:/input:ro \
  -v /mnt/library/romsets-archive/<system>:/output \
  node:lts npx --yes igir@latest copy \
  --dat '/dats/<system>.dat' \
  --input '/input/**/*.zip' \
  --output /output \
  --single \
  --filter-language EN \
  --filter-region USA,WORLD \
  --prefer-language EN \
  --prefer-region USA,WORLD \
  --prefer-revision newer \
  --only-retail \
  --no-unlicensed
```

Always `copy`, never `move`, into a fresh preview output directory first —
inspect the result before it's the thing you promote. Run `igir report --dat
... --input ...` (no `--output`) first if you want a match-rate sanity check
before committing to a full curation run.

## `--prefer-*` vs `--filter-*` — a real distinction, not a naming quirk

`--prefer-*` flags only choose among clones that survive filtering — they do
not remove anything. `--prefer-language EN` alone will still happily keep a
Japan-only game if that's the only surviving dump for its parent. Actual
pruning comes from `--filter-*` and `--no-*`/`--only-*` flags. If the goal is
"English-only, USA/World-only," you need `--filter-language EN
--filter-region USA,WORLD`, not just the `--prefer-*` equivalents.

`--only-retail` bundles most junk exclusions (BIOS, debug, demo, beta,
sample, prototype, program, aftermarket, homebrew, unverified, bad dumps) but
does **not** exclude unlicensed releases — those need `--no-unlicensed`
explicitly, since Igir still considers them "retail."

`--only-retail`'s demo/beta exclusion is DAT-category-based, not
filename-based — a handful of oddly-named legitimate dumps (e.g. Sega
Channel "(Auto Demo)" promotional versions) can slip through if the DAT
doesn't tag them with a demo category despite the name saying so. Spot-check
the output for stray "(Demo)"/"(Beta)"/"(Auto Demo)" filenames after a run;
a few false positives are normal too (e.g. "Demolition Man" isn't a demo).

`--dat-ignore-parent-clone` forces Igir to infer parent/clone grouping
instead of trusting the DAT's own — tested against a real No-Intro Genesis
DAT and it changed nothing (byte-identical output with and without), meaning
that DAT's grouping was already clean. Don't reach for this flag by default;
it's a second-stage lever only if the DAT's own grouping is visibly leaving
obvious regional duplicates in a `--single` (1G1R) output.

## Curation strategies (archive → library)

**Decided** (was open, superseded 2026-09-20) — see the full design at
[romset-curation-pipeline.md](../../design-notes/romset-curation-pipeline.md).
Summary: ScreenScraper identifies and rates every archive-tier game (needed
regardless of curation, since it supplies display names/artwork too); rank
by that rating alone and take the top ~150-200 as candidates; only those
candidates get a second IGDB rating; a Bayesian blend of the two produces
the final top-100 manifest that gets promoted into the library tier. IGDB is
deliberately not run against the whole archive — it's the most
fuzzy-matching-heavy, human-review-heavy step, so it only runs on games
already in real contention.

A real Genesis run went 4,233 raw files → 922 archive-tier games with
`--filter-language EN --filter-region USA,WORLD --only-retail
--no-unlicensed --single` — none of Igir's own filters get you further,
since they filter by metadata (region/language/license/dump-quality), not
by "is this game actually good/known/worth including," which is what the
curation pipeline above is for.

## Lessons from the first Mega Drive cleanup

- Do not assume old GoodTools filename inference will provide trustworthy 1G1R decisions.
- Prefer authoritative No-Intro checksum matching.
- Canonicalize verified ROMs first.
- Then apply 1G1R to the set actually owned.
- Review ambiguous regional/title relationships manually.
- Treat save files separately from ROM files.
- Never use destructive `move`/`clean` operations against either romset tier
  without a tested dry-run first — the archive tier makes the library tier
  recoverable without repeating acquisition, but the archive itself has no
  further backup (AGENTS.md rule 3).
- Be aggressive about discarding non-ROM cruft (NFOs, scans, samples,
  non-matching alt dumps) during the archive-tier curation pass — there's no
  reason to carry it forward into either tier.
