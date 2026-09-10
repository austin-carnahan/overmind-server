# Igir Workflow

Use Igir primarily for authoritative validation, canonical naming, and curated outputs.

## Lessons from the first Mega Drive cleanup

- Do not assume old GoodTools filename inference will provide trustworthy 1G1R decisions.
- Prefer authoritative No-Intro checksum matching.
- Canonicalize verified ROMs first.
- Then apply 1G1R to the set actually owned.
- Review ambiguous regional/title relationships manually.
- Treat save files separately from ROM files.
- Never use destructive `move`/`clean` operations against the master backup.
