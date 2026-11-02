---
name: reference-research
description: "Find reference images and ideas for a design brief across many sources (Pinterest, Are.na, design publications, licensed photo libraries, museum collections, makers' catalogs) with web_search and web_fetch, keep provenance, and use Pinterest and Bright Data through Composio. Use when gathering inspiration or references."
---

# Reference research

How to find images and ideas for a design brief. Started 2026-11-01. This is a starting list, not a boundary: add good sources as you find them, and drop ones that disappoint.

## Tools

- `web_search` (Brave, free plan with a monthly limit) to find pages. Plan a few strong queries per brief. `site:` narrows to one source, for example `japandi bedroom site:pinterest.com/pin` or `site:are.na`.
- `web_fetch` (or `curl` from the shell) to read a page and pull its image URLs (`og:image` is usually the main image).
- `view_image` to actually look at what you found before recommending it.
- Composio Pinterest for the user's own boards (`composio-cli` skill, `references/composio.md`).

## Where to look

Match sources to the brief, and tell the user about ones they may not know.

**Curated inspiration**

- **Pinterest**: broad and popular, good for trends and the user's own boards. Pin pages read as plain HTML (`references/composio.md`, "Finding Pins by keyword").
- **Are.na**: slower, more thoughtful boards kept by designers, architects and artists; often less obvious than Pinterest. Has a public API.
- **Cosmos** and **Savee**: visual bookmarking communities with a design-professional audience.

**Interiors and architecture**

- Design publications: Dezeen, Dwell, Architectural Digest, Remodelista, Apartment Therapy, Design Milk, Yellowtrace.
- Project databases: ArchDaily, Archello, Houzz (real rooms, often with product and dimension details).
- Minimal and calm spaces: Leibal.

**Freely licensed photos** (usable beyond inspiration; check each license)

- Unsplash and Pexels: high-quality photos with simple licenses and APIs (a free API key may be needed).
- Wikimedia Commons: licensed media with attribution details on every file.

**History, craft and material**

- Museum open-access collections: The Met, Rijksmuseum, Cooper Hewitt (the Smithsonian's design museum), Google Arts & Culture. Good for period styles, patterns, textiles and objects; many have APIs and public-domain images.

**Real objects**

- Makers' and manufacturers' catalogs (for example IKEA, Muji, HAY, Muuto): actual products with dimensions, useful when a design has to be buildable or modeled in Sweet Home 3D.

**Graphics and layout**

- Behance and Dribbble for graphic design, typography and layout work.

## Keeping references

- Save chosen images into the project's working folder (for example `projects/<project>/references/`), not `/tmp`.
- Keep a `sources.md` (or `.json`) beside them: page URL, image URL, source, creator if known, license if stated, and why it was picked.
- References are for inspiration. Don't republish them or present them as the user's or your own work.

## Being a good guest

- A handful of lookups per brief, not crawling. Prefer a site's API when one exists.
- Respect logins and paywalls: don't work around them. Instagram, for example, mostly needs a login.
- Bright Data is paid: only with the user's approval (`references/composio.md`).
