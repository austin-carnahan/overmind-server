# Igir Workflow

Use Igir primarily for authoritative validation, canonical naming, and curated outputs.

## Lessons from the first Mega Drive cleanup

- Do not assume old GoodTools filename inference will provide trustworthy 1G1R decisions.
- Prefer authoritative No-Intro checksum matching.
- Canonicalize verified ROMs first.
- Then apply 1G1R to the set actually owned.
- Review ambiguous regional/title relationships manually.
- Treat save files separately from ROM files.
- Never use destructive `move`/`clean` operations against the library without
  a tested dry-run first — one tier, no preserved-original fallback copy.
- Be aggressive about discarding non-ROM cruft (NFOs, scans, samples,
  non-matching alt dumps) at ingestion — there's no archive tier to keep it
  in "just in case."
