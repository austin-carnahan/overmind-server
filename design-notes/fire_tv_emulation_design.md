# Fire TV Stick 4K Max — Emulation Design Note

**Device:** Amazon Fire TV Stick 4K Max, 2nd generation  
**Platform:** Fire OS 8 / Android 11 base  
**Role:** Local retro-gaming appliance and thin client  
**Canonical ROM library:** Overmind  
**Local ROM storage:** 128 GB USB flash drive  
**Primary emulator frontend/runtime:** RetroArch

## 1. Purpose

This document captures the current emulation design for the Fire TV Stick 4K Max.

The goal is to build a stable local-emulation tier that runs older systems reliably, handles PS1 well, makes a best-effort pass at N64 and Dreamcast, keeps the Fire Stick replaceable and non-canonical, avoids spending limited performance on cosmetic features, and leaves heavier emulation and enhancement work to a future mini-PC + game-streaming tier.

## 2. Architecture

```text
Overmind
canonical ROM library
        │
        ▼
R-Shop
browse / install / remove local copies
        │
        ▼
128 GB Fire Stick USB cache
        │
        ▼
RetroArch / standalone emulator
        │
        ▼
Syncthing-style save sync
        │
        ▼
Overmind save store
```

### Responsibilities

**Overmind**
- authoritative ROM library;
- metadata and organization;
- ingestion/validation;
- canonical save backup/sync target.

**R-Shop**
- browse the Overmind ROM library;
- install/cache games locally;
- remove local cached games;
- eventually hand off directly to the appropriate emulator.

**RetroArch**
- primary gameplay frontend/runtime;
- default path unless a standalone emulator materially outperforms it.

**Standalone emulators**
- used only when they provide a real performance or compatibility advantage;
- Dreamcast/Flycast is the clearest current example.

**128 GB USB drive**
- disposable local ROM cache;
- not authoritative storage;
- safe to wipe/rebuild from Overmind.

## 3. Performance philosophy

Tune for **stable full-speed emulation first**.

Avoid spending limited CPU/GPU headroom on features that make marginal systems less reliable.

### Baseline rules

- **Rewind:** OFF
- **Run-Ahead:** OFF
- **Heavy shaders:** OFF
- **Threaded Video in RetroArch:** OFF initially
- **Frame skip:** OFF by default; enable only for titles that need it
- **Vulkan:** preferred where the emulator/core is stable with it
- **Upscaling:** conservative
- **Latency features:** conservative; stability wins over marginal latency reductions

### Audio latency

Initial target:

```text
~64 ms
```

If crackling or underruns occur:

```text
~96–128 ms
```

Do not increase latency preemptively if the lower setting is stable.

### Visual enhancements

Avoid by default:

- heavy CRT shaders;
- expensive post-processing;
- aggressive internal-resolution scaling;
- expensive geometry-correction features;
- enhancement settings that materially reduce frame pacing.

The future mini-PC / Sunshine / Moonlight tier is the proper place for high-end enhancement.

## 4. System-by-system baseline

### 4.1 8-bit and 16-bit systems

Examples:

- NES
- SNES
- Genesis / Mega Drive

Goals:

- full speed;
- low latency;
- clean controller behavior;
- no frame skip;
- no aggressive tuning required.

Prefer mature RetroArch cores with good compatibility and low overhead.

### 4.2 PlayStation 1

**Preferred direction:** SwanStation

Priorities:

```text
compatibility
→ frame pacing
→ audio stability
→ modest visual improvement
```

Use conservative enhancement settings rather than pushing maximum internal resolution.

### 4.3 Nintendo 64

Preferred core directions:

- **ParaLLEl**
- **Mupen64Plus-Next**

Do not assume one core will be ideal for every title.

Preferred internal resolution:

```text
~480p when stable
```

Fallback:

```text
~240p / native-ish rendering for difficult titles
```

For problematic games:

1. lower internal resolution;
2. try the alternate preferred core;
3. reduce optional enhancements;
4. only then consider frame skip or more invasive compromises.

Per-game overrides are acceptable and expected.

### 4.4 Dreamcast

Dreamcast is the strongest candidate for a **standalone emulator exception**.

**Preferred direction:** standalone Flycast when it materially outperforms the RetroArch core.

Current baseline:

- **Renderer:** Vulkan
- **Threaded rendering:** ON where validated
- **Frame skip:** OFF by default
- use frame skip only when a specific game requires it

If standalone Flycast clearly provides better frame pacing, compatibility, audio stability, or Vulkan behavior, keep it as the default Dreamcast path.

## 5. RetroArch global baseline

```text
Rewind                OFF
Run-Ahead              OFF
Threaded Video         OFF initially
Heavy shaders          OFF
Frame Skip             OFF by default
Audio latency          ~64 ms baseline
Vulkan                 preferred where stable
```

Threaded video should only be enabled selectively when a specific core/system measurably benefits and latency remains acceptable.

## 6. Controller design

Controller configuration is not yet fully finalized.

Requirements:

- reliable Bluetooth reconnect after reboot/wake;
- stable player-1/player-2 assignment;
- Fire TV remote remains usable alongside gamepads;
- predictable RetroArch menu hotkey;
- reliable quit-game behavior;
- save/load-state hotkeys only if they do not conflict with gameplay;
- no accidental Home/Back collisions.

The final mapping should be documented explicitly once validated.

## 7. ROM storage model

The 128 GB USB drive is a **local cache**.

Suggested organization:

```text
roms/
├── nes/
├── snes/
├── genesis/
├── psx/
├── n64/
└── dreamcast/

bios/
saves/
metadata/
staging/
```

Rules:

- Overmind remains authoritative.
- R-Shop installs or removes local copies.
- Removing a game locally must never delete the canonical Overmind copy.
- RetroArch should load directly from the local USB cache.
- Local cache failures should not threaten canonical data.

## 8. Save synchronization

Desired model:

```text
Fire Stick save data
        ⇅
Syncthing-style client
        ⇅
Overmind save store
```

Sync:

- SRAM / battery saves;
- memory-card saves;
- optionally save states after compatibility testing.

Avoid syncing:

- ROM files;
- thumbnails;
- temporary caches;
- volatile emulator application data.

## 9. R-Shop integration

R-Shop is **not** the emulator frontend.

Its role is browse, metadata, install, remove, and local-cache state.

Desired launch path:

```text
R-Shop selection
      │
      ▼
resolve local ROM path
      │
      ▼
select emulator/core
      │
      ▼
Android intent/helper
      │
      ▼
RetroArch or standalone Flycast
```

Acceptance criteria:

- selecting an installed title launches it without manual file browsing;
- non-installed titles can be cached first;
- removing a game removes only the local copy;
- already-cached games remain playable without Overmind connectivity.

## 10. Validation strategy

Use a small representative test library.

Minimum systems:

- NES
- SNES
- Genesis / Mega Drive
- PS1
- N64
- Dreamcast

For each title record:

```text
Game
System
Core / emulator
Renderer
Internal resolution
Audio behavior
Controller behavior
Frame pacing
Known issue
Pass / fail
```

## 11. Known unresolved items

1. Final controller hotkey mapping
2. Exact preferred N64 core by representative title
3. Which Dreamcast titles require standalone Flycast
4. Whether any RetroArch cores benefit enough from threaded video to justify enabling it selectively
5. Exact save-sync path layout
6. R-Shop → emulator intent/handoff implementation
7. Per-game overrides for difficult N64/Dreamcast titles

These should be settled through validation, not guesses.

## 12. Future streaming tier

```text
Future Overmind mini-PC
        │
        ├── heavier emulation
        ├── higher internal resolution
        ├── advanced shaders
        ├── more expensive enhancement features
        └── Sunshine
               │
               ▼
           Moonlight
               │
               ▼
        Fire TV Stick
```

The local tier remains valuable for offline travel, low-latency older systems, low-complexity gameplay, and resilience when the server is unavailable.

## 13. Current decision summary

> **RetroArch primary; SwanStation for PS1; ParaLLEl/Mupen64Plus-Next for N64; standalone Flycast where it materially improves Dreamcast; Vulkan where stable; no rewind, run-ahead, or heavy shaders; conservative audio/video settings; USB ROM cache; Overmind as canonical storage; separate save synchronization.**

The Fire Stick should behave like a reliable console appliance, not a benchmark project.
