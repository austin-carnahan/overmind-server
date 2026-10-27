# Upstream and local adaptations

## Sources

| Source | Revision | License | Used for |
| --- | --- | --- | --- |
| [LevyBytes/AI-SKILL-gimp](https://github.com/LevyBytes/AI-SKILL-gimp) | `10b82859acc747e01e4fc3188b9be3c786286e2c` (2026-10-23) | Apache-2.0 ([LICENSE](LICENSE), [NOTICE](NOTICE)) | The router structure and the GIMP concept references |
| [gimp-agent-mcp](https://github.com/SarutobiSasuke8/gimp-agent-mcp) `skills/gimp-layered-assets` | as shipped in the installed package, `gimp-agent-mcp==0.5.0` | Apache-2.0 | Working rules in `SKILL.md` (status first, ids, look-then-measure, completion evidence, flat images are partial recoveries) |

Reviewed 2026-10-26: AI-SKILL-gimp's files, references and its one script; the layered-assets
`SKILL.md` and its `game-assets.md` reference.

## What changed

**Kept verbatim:** `references/interface-and-workflow.md`, `references/tools-overview.md`.

**Kept, lightly edited** (each marked "Adapted from AI-SKILL-gimp" at the top): `layers-and-modes.md`,
`selections.md`, `masks-and-channels.md`, `paths.md`, `colors-and-adjustments.md`, `filters.md`,
`file-formats-and-export.md`. Links to removed files now point to `pdb-calls.md` or `tool-surface.md`;
`filters.md` and `layers-and-modes.md` add the agent-tool equivalents (GEGL filters, pass-through groups).

**Rewritten:** `SKILL.md` (router kept, agent working rules added, routed to the agent's tools);
`references/pdb-calls.md` replaces `pdb-reference.md` and the three `pdb-recipes-*.md` files (same
procedures, as `gimp_pdb_call` arguments, with examples verified on GIMP 3.2.6).

**New:** `references/tool-surface.md` (the 38 GIMP Agent MCP tools, conventions, this installation's
restrictions and failure modes, environment-dependent alternatives).

**Removed, and why:**

- `python-fu.md`, `script-fu.md`, `scripting-overview.md`: writing and installing plug-ins and Script-Fu,
  and the scripting consoles. Agents here call named operations; the code-running PDB procedures are
  refused (`patch-gimp-agent-bridge`).
- `pdb-recipes-io-batch.md` and `scripts/convert_to_jpeg.py`: the script runs `gimp-console` with the
  `python-fu-eval` batch interpreter through `subprocess`. Export is `gimp_export` here.
- `languages.md`, `INDEX.md`, `topics.json`: the router in `SKILL.md` covers the remaining files; the
  topic catalog listed removed topics.
- layered-assets' `game-assets.md` and its sprite/batch sibling skills: not this project's work.

## Updating

Compare a newer upstream revision against the one above (`git diff 10b82859..<new> -- references SKILL.md`),
carry over corrections to the kept files, record the new revision here, and keep the removals unless
the agent tool surface changes.
