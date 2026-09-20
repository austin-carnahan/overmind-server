# Doclet

Document → Markdown/JSON service on Overmind, per the
[Doclet Service V3 design](../../design-notes/Doclet%20Service%20—%20Implementation%20Design%20V3.md).
Two containers ([compose.yaml](compose.yaml)):

- `doclet` — Docling Serve itself (the public API, async jobs, standard
  parsing pipeline).
- `doclet-vlm-adapter` — internal-only OpenAI-compatible shim in front of
  MLServer's real `inference.home.arpa` endpoint, for selective
  Pixel/Granite-Docling enrichment. See
  [its own README](vlm-adapter/README.md) for why it isn't a new public
  hostname.

## Real hardware-compatibility bug found and fixed before this could run at all

The official `ghcr.io/docling-project/docling-serve-cpu` image crash-looped
with exit 132 (SIGILL) on overmind-01's Raspberry Pi 4 — confirmed via the
most minimal possible test (`docker run --entrypoint /bin/true <image>`
alone crashed). Root cause, found by reading the image's own
[Containerfile](https://github.com/docling-project/docling-serve/blob/main/Containerfile)
directly: it sets `ENV LD_PRELOAD=/usr/local/lib/libmimalloc.so` globally,
injecting a custom-built `mimalloc` allocator into every process in the
container. That library is built via a plain `cmake && make` on whatever
arm64 CI runner GitHub Actions uses (almost certainly a newer server-class
ARM core with LSE/ARMv8.2 support) and crashes immediately on the Pi 4's
older Cortex-A72 (ARMv8.0-A, no LSE atomics) — confirmed directly:
`docker run -e LD_PRELOAD= --entrypoint /bin/true <image>` succeeds
immediately once the injection is disabled.

Not fixable by trying a different `docling-serve` release tag — every
version shares the same base image family
(`quay.io/sclorg/python-312-c9s`) and the same mimalloc build step, so
this affects all of them equally. Fixed with one line in
[compose.yaml](compose.yaml): `LD_PRELOAD: ""`, overriding the image's own
env var. Verified the actual application (not just `/bin/true`) imports
and runs correctly with the override in place before trusting it further.

## Real memory finding, and how it was addressed

A genuine Docling Serve conversion job OOM-killed the bare-process version
of this workload on overmind-01 (before this was containerized) —
confirmed via kernel log, `anon-rss` ~2.3GB, host had zero swap and other
production services already using most of its 7.6GB. See
[experiments/doclet-service Stage 3 findings](../../experiments/doclet-service/stage1-picture-description-api/README.md)
and the [vlm-adapter README](vlm-adapter/README.md) for the full
investigation, including the memory-profiling pass across every
production service on the host (no single pathological consumer found —
the aggregate baseline plus Docling's own genuine ~2.3-3GB burst simply
exceeded available headroom with no cushion).

Addressed with two changes, verified together against a real, genuine
conversion job (not a synthetic test):

1. **4GB SSD-backed swapfile** added to overmind-01
   (`/mnt/disks/ssd1/swapfile`) — gives the kernel somewhere to push cold
   anonymous pages from idle services during a burst, instead of having
   no option but to kill something.
2. **`mem_limit: 4g`** on the `doclet` container (see
   [compose.yaml](compose.yaml) for the full reasoning, including why 3g
   was tried first and raised after a real run peaked at ~2.96GB) —
   contains a runaway `doclet` process to its own budget instead of
   letting the kernel OOM-killer pick an arbitrary victim across the
   whole host, which is what happened to the bare-process version.

Verified together (2026-09-18): a real conversion job with real Pixel
enrichment completed successfully — correct DocTags/`line_chart` output,
542s total — with `doclet` never `OOMKilled` (confirmed via
`docker inspect`), and swap genuinely engaging (379MB swapped out during
the run, confirmed via `/proc/meminfo`) rather than the system running
out of options. Other production services (Jellyfin, Sonarr, checked
directly) stayed responsive throughout.
