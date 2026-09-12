# Overmind ROM & Emulator Design Brief

**Status:** DEFERRED — see [status legend](README.md#status-legend); adopted
architecture, nothing built or tested yet. ROMarr and R-Shop verified as real,
active projects before adoption (see
[runbooks/clients/fire-tv.md](../runbooks/clients/fire-tv.md)); neither
confirmed to actually work well on Fire TV specifically yet.
**Date:** 2026-09-12

## Goal

Build a durable retro-gaming stack where **Overmind owns the canonical ROM library** and Fire TV Stick clients browse that library, cache selected games locally, and launch them through RetroArch.

Favor ordinary files, standard protocols, replaceable tools, and minimal custom code.

## Architecture

```text
ROM sources
    ↓
ROMarr
acquisition / scoring / collection completion
    ↓
staging
    ↓
Igir
DAT audit / 1G1R / normalization
    ↓
OVERMIND CANONICAL ROM LIBRARY
    ↓
read-only SMB over LAN / Tailscale
    ↓
R-Shop on Fire Stick
browse / metadata / install / remove
    ↓
SanDisk Ultra Fit 256 GB local cache
    ↓
RetroArch
launch / emulate / couch UI
    ↓
per-user saves / states
    ↓
Syncthing-Fork
backup / sync to Overmind
```

## Component Roles

### Overmind filesystem

The server filesystem is the source of truth for ROMs, BIOS files, and save backups. The collection should remain usable without RomM, R-Shop, or any catalog database.

### ROMarr

Use ROMarr as the **acquisition and collection-building frontend** for:

- search and manual acquisition;
- candidate/release scoring;
- collection completion;
- archive handling;
- first-pass DAT/checksum verification.

For static systems such as SNES or N64, prefer completing a desired collection rather than maintaining a long-lived wanted queue.

ROMarr should initially write to staging, not directly to the canonical library.

### Igir

Use Igir as the deterministic collection-quality layer for:

- No-Intro/Redump DAT verification;
- 1G1R;
- region/language/revision preference;
- normalization and renaming;
- duplicate cleanup;
- reports/fixdats;
- complex multi-disc or arcade transformations where needed.

If ROMarr proves sufficient for simple platforms, Igir can become a periodic audit/rebuild tool rather than a mandatory step for every file.

### SMB + Tailscale

Expose the canonical ROM library **read-only over SMB**.

Use LAN access at home and Tailscale when remote. Fire Stick clients should normally copy games locally before launch instead of running them directly from the network share.

### R-Shop

R-Shop is the Fire Stick's **library and cache manager**.

Use it to:

- browse the complete remote collection;
- view artwork, descriptions, ratings, and metadata;
- search/filter titles;
- see what is installed locally;
- install selected games to USB storage;
- remove local cached copies.

R-Shop does not need to launch games.

### Fire Stick local cache

Use the existing **SanDisk Ultra Fit 256 GB USB-A flash drive** through a compact powered Micro-USB OTG adapter.

The Fire Stick is a cache, not a source of truth. Extra USB capacity may later also hold offline travel media.

### RetroArch

RetroArch is the emulator and couch-friendly gaming frontend.

Use it for launching games, cores, controller mapping, playlists, thumbnails/box art, TV-friendly themes, saves, and save states.

```text
R-Shop   → browse / install / remove
RetroArch → browse installed games / play
```

### Syncthing-Fork

Use Syncthing-Fork for lightweight save backup/synchronization. Do not build a custom save-sync service initially.

## Per-User Save Namespaces

Save storage should be designed around **users, not devices**.

```text
/saves/
├── austin/
├── friend-1/
└── friend-2/
```

A user's Fire Stick, browser emulator, handheld, or future device should share that user's save namespace.

Different users therefore never conflict even when playing the same game at the same time.

No locking, leasing, or merge machinery is required initially. The important decision is simply to preserve this directory/account shape from the beginning.

Save states may later need emulator/core compatibility rules, but that is not an MVP concern.

## RetroAchievements

**RetroAchievements support is a known nice-to-have.**

Prefer enabling it through RetroArch's native RetroAchievements integration rather than building anything custom.

Later, achievement progress or metadata may also appear through R-Shop, RomM, or another optional catalog layer.

RetroAchievements must not become a dependency for launching or managing games.

## RomM

RomM remains optional.

It may later provide a richer server-side web catalog, metadata aggregation, collections, manuals, browser play, RetroAchievements views, or multi-user features.

It should **not** own:

- canonical ROM files;
- acquisition;
- normalization;
- Fire Stick distribution;
- the gameplay path.

If RomM disappears, the core stack should continue working unchanged.

## Permissions

```text
ROMarr       → write staging/incoming
Igir         → read staging, write canonical output
SMB/R-Shop   → read-only canonical ROM library
RetroArch    → local USB cache + user save namespace
Syncthing    → user save/state directories
```

Fire Stick clients should never receive write access to the canonical ROM collection.

## Initial Build Order

1. **Canonical library** — establish directories, DATs, and Igir policy.
2. **Acquisition** — deploy ROMarr against staging and test one static-console collection.
3. **Distribution** — expose the canonical library read-only over SMB and Tailscale.
4. **Fire Stick cache** — configure the 256 GB Ultra Fit and R-Shop.
5. **RetroArch** — configure cores, playlists, artwork, and TV-friendly UI.
6. **Save sync** — add Syncthing-Fork using per-user namespaces.
7. **Nice-to-haves** — enable RetroAchievements; evaluate RomM only if its catalog features are useful.

## What Not to Build

Do not build a custom:

- ROM launcher;
- metadata scraper;
- acquisition UI;
- save-sync service;
- network filesystem client;
- normalization engine;
- Fire Stick cache manager.

Prefer composing:

```text
ROMarr
Igir
SMB
Tailscale
R-Shop
RetroArch
Syncthing-Fork
```

with RomM optional.

## Summary

> **Overmind owns the canonical ROM library. ROMarr handles acquisition and collection completion; Igir handles deterministic verification and normalization. The clean library is exposed read-only over SMB and Tailscale. R-Shop browses the full collection and manages a 256 GB Fire Stick cache. RetroArch provides the gaming interface. Syncthing-Fork keeps per-user saves synchronized across that user's devices. RetroAchievements is a planned nice-to-have, and RomM remains optional.**
