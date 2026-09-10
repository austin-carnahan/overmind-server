# Overmind — Agentic Media & ROM Automation Design

## Status

Future enhancement / architectural design note.

## Purpose

Overmind should evolve from a passive home server into an intent-driven personal infrastructure platform.

For entertainment workflows, the goal is to move away from manually managing individual downloads, files, subtitles, ROMs, metadata, and deployment targets. Instead, the user should be able to express a desired outcome in natural language and allow an agent to coordinate mature deterministic tools that perform the actual work.

Examples:

> “I want to watch season 2 of Show X.”

> “Keep downloading new episodes of Show Y as they come out.”

> “Put Game Z for Sega Genesis on my travel setup.”

> “Make sure the latest episodes of everything I’m following are ready before I leave Friday.”

The LLM/agent should not replace existing media-management tools. It should serve as the **intent, orchestration, and exception-handling layer** above them.

---

# 1. Design Principles

## 1.1 Prefer mature deterministic tools over custom agent logic

Overmind should not ask an LLM to reproduce functionality already solved by mature software.

Examples:

- Sonarr owns TV-series monitoring, metadata, release schedules, quality profiles, retries, and download-client coordination.
- Bazarr owns subtitle discovery, language policies, synchronization, and retry behavior.
- Transmission owns transfers.
- RomM owns ROM-library metadata, browsing, and distribution.
- Igir owns ROM identification, DAT verification, normalization, deduplication, and multi-disc organization.

The agent integrates these systems rather than replacing them.

## 1.2 Agents express intent; deterministic services execute policy

The architecture should distinguish:

```text
Intent
    ↓
Paperclip / local agent
    ↓
bounded application APIs
    ↓
Sonarr / RomM / Transmission / Bazarr / Igir
    ↓
deterministic execution
```

This limits hallucination-driven infrastructure changes and keeps routine operations predictable.

## 1.3 Desired state is preferable to one-off imperative commands

Where practical, user requests should modify a durable representation of what Overmind should maintain.

For example:

```yaml
series:
  - title: Example Show
    seasons:
      - 2
      - 3
    monitor: future
    quality: 1080p-efficient
    subtitles:
      - en
```

or:

```yaml
games:
  - title: Sonic the Hedgehog 3
    platform: genesis
    status: wanted
    targets:
      - home
      - travel
```

The agent reconciles this desired state with the actual state of Sonarr, RomM, the filesystem, and deployment targets.

## 1.4 Agents should handle exceptions, not poll everything constantly

Routine monitoring should remain deterministic.

Paperclip heartbeats should focus on situations that require interpretation or escalation, such as:

- failed downloads;
- missing subtitles;
- validation failures;
- unidentified ROMs;
- incomplete multi-disc sets;
- storage pressure;
- stalled transfers;
- deployment targets falling out of sync;
- a monitored episode remaining unavailable for an unusual amount of time.

---

# 2. Shared High-Level Architecture

```text
                         USER
                          │
                          │ natural-language intent
                          ▼
                 Paperclip / Agent Layer
                          │
             ┌────────────┴────────────┐
             │                         │
             ▼                         ▼
       Video / TV tools             Game tools
       Sonarr / Bazarr              RomM / Igir
             │                         │
             └────────────┬────────────┘
                          │
                          ▼
                  Acquisition / Import
                          │
                     Transmission
                     manual import
                     other backends
                          │
                          ▼
                       incoming
                          │
                          ▼
                     quarantine
                          │
             ┌────────────┼────────────┐
             │            │            │
             ▼            ▼            ▼
          malware      file/type     archive
           scan        validation    inspection
             │            │            │
             └────────────┴────────────┘
                          │
                          ▼
                 domain-specific validation
                          │
             ┌────────────┴────────────┐
             ▼                         ▼
        media validation           ROM validation
          ffprobe/etc.                Igir/DAT
             │                         │
             ▼                         ▼
        organization              normalization
             │                         │
             └────────────┬────────────┘
                          ▼
                      promotion
                          │
             ┌────────────┴────────────┐
             ▼                         ▼
       video library                ROM library
      Jellyfin / Kodi                 RomM
```

---

# 3. Movies and Television Workflow

## 3.1 Natural-language request

Example:

> “Add Show X. I want season 2 and any future episodes. 1080p is fine and get English subtitles.”

The agent should:

1. resolve the show identity;
2. inspect whether it already exists in Sonarr;
3. select a predefined Overmind quality profile;
4. set monitored seasons/episodes;
5. apply language/subtitle preferences;
6. initiate an immediate search when appropriate;
7. persist or update desired-state configuration;
8. report the resulting state to the user.

The agent should not manually search arbitrary sites when Sonarr can perform the configured search itself.

---

# 4. Ongoing-Series Automation

For currently airing shows, Sonarr should provide the persistent monitoring layer.

Conceptually:

```text
series added
    ↓
Sonarr tracks episode schedule
    ↓
episode becomes available
    ↓
Sonarr evaluates candidates
    ↓
candidate satisfies quality policy
    ↓
Transmission receives job
    ↓
download completes
    ↓
Overmind ingestion pipeline
    ↓
Sonarr organizes episode
    ↓
Bazarr handles subtitles
    ↓
Jellyfin / Kodi sees finished media
```

This eliminates the need to maintain our own release-date cron files for ordinary television.

A human-readable desired-state configuration may still mirror the user's intentions, but Sonarr remains authoritative for operational episode state.

---

# 5. Quality Profiles

Overmind should define a small number of human-understandable profiles rather than exposing every underlying release parameter to the user.

Possible profiles:

```text
efficient-1080p
high-quality-1080p
efficient-4k
archive-quality
travel-copy
```

A user can therefore say:

> “I don't care about 4K for sitcoms.”

or:

> “Get this movie in high-quality 4K.”

The agent maps those phrases onto deterministic Sonarr/Radarr-style profiles.

These profiles should eventually live in version-controlled infrastructure configuration.

---

# 6. Subtitle Workflow

Bazarr should own routine subtitle acquisition.

Overmind-level intent might look like:

```yaml
subtitles:
  preferred:
    - en
  hearing_impaired: false
  sync: true
```

The agent becomes useful when ordinary automation fails.

Example heartbeat finding:

```text
Show X S02E04
video: available
English subtitle: missing for 18 hours
```

The agent can then:

- trigger another search;
- inspect alternate subtitle sources;
- determine whether an embedded subtitle exists;
- attempt synchronization;
- report the unresolved exception.

---

# 7. Media Ingestion Trust Boundary

A completed transfer should not automatically become trusted canonical media merely because a download client finished it.

The shared ingestion pipeline should be:

```text
incoming
   ↓
quarantine
   ↓
malware scan
   ↓
extension / MIME allowlist
   ↓
archive inspection
   ↓
extraction if allowed
   ↓
ffprobe / media validation
   ↓
classification
   ↓
rename / organize
   ↓
promote
```

Failed or suspicious objects should move to:

```text
rejected/
```

rather than silently entering the library.

This ingestion layer should remain independent of whichever acquisition backend created the file.

---

# 8. ROM and Emulator Workflow

ROM management follows the same architectural philosophy but does not require Sonarr-style release scheduling for historical platforms.

The basic workflow is:

```text
USER
 │
 │ "I want to play Game X on Genesis"
 ▼
Paperclip agent
 │
 ├── resolve title
 ├── resolve platform
 ├── resolve preferred region/version
 │
 ▼
RomM lookup
 │
 ├── already present ───────────────┐
 │                                  │
 └── missing                        │
      │                             │
      ▼                             │
 acquisition / supplied dump       │
      │                             │
      ▼                             │
 incoming                           │
      ↓                             │
 quarantine                         │
      ↓                             │
 security validation                │
      ↓                             │
 Igir / DAT identification          │
      ↓                             │
 normalization                      │
      ↓                             │
 promote                            │
      ↓                             │
 RomM library ◄─────────────────────┘
      │
      ▼
 deploy to requested target
```

---

# 9. RomM as the Game Library Control Plane

RomM should become the canonical interface for the ROM collection.

Responsibilities include:

- cataloging games;
- storing metadata;
- identifying platform and title relationships;
- browsing the collection;
- exposing APIs to Overmind agents;
- supporting clients that retrieve games from the canonical library;
- potentially managing save/state synchronization.

The filesystem remains canonical storage, but RomM becomes the human- and agent-friendly catalog over it.

---

# 10. Igir as the ROM Validation Layer

Igir should provide deterministic ROM-library hygiene.

Expected responsibilities:

- identify ROMs against known DAT sets;
- checksum files;
- normalize filenames;
- organize platform directories;
- detect unknown or invalid dumps;
- resolve duplicate variants;
- apply region/version preferences;
- inspect archives;
- generate multi-disc playlists where appropriate.

For example, a PlayStation game imported as:

```text
disc1.bin
disc1.cue
disc2.bin
disc2.cue
```

can ultimately be promoted into a normalized library representation including an `.m3u` playlist for emulator consumption.

The agent should not improvise these transformations when Igir already understands the domain.

---

# 11. ROM Desired State

A simple declarative layer may describe games the user wants available and where.

Example:

```yaml
games:
  - title: Sonic the Hedgehog 3
    platform: genesis
    region: USA
    targets:
      - home
      - travel

  - title: Metal Gear Solid
    platform: psx
    region: USA
    targets:
      - home

  - title: Chrono Trigger
    platform: snes
    targets:
      - travel
```

This creates an important distinction between:

```text
canonical library
```

and:

```text
what should be deployed to each device
```

A travel Fire TV device does not need the entire home collection.

---

# 12. Agent-Assisted Device Deployment

Eventually the user should be able to say:

> “Put Chrono Trigger and Sonic 3 on the travel setup.”

The agent should:

1. resolve the canonical games;
2. confirm they exist and are validated;
3. determine the target device's emulator profile;
4. stage appropriate files;
5. sync them to the device;
6. verify the transfer;
7. update deployment state.

Likewise:

> “Make the travel setup have all my currently active games.”

should reconcile the target device against desired state rather than requiring manual file copying.

---

# 13. Paperclip Agent Responsibilities

Paperclip should orchestrate higher-level goals.

Example bounded capabilities:

```text
media.findSeries()
media.addSeries()
media.monitorSeason()
media.searchMissing()
media.getDownloadStatus()
media.retryDownload()

subtitles.getMissing()
subtitles.search()
subtitles.sync()

games.find()
games.import()
games.validate()
games.deploy()
games.syncTarget()

storage.getCapacity()
ingestion.getFailures()
ingestion.retry()
```

The agent should prefer these application-level tools over unrestricted shell access.

Shell access may still exist for trusted maintenance agents, but it should not be the default interface for entertainment workflows.

---

# 14. Heartbeats and Scheduled Agent Work

Paperclip heartbeats should operate above the deterministic services.

Potential heartbeat:

```text
Every few hours:

1. Check ingestion failures.
2. Check missing subtitles beyond threshold.
3. Check monitored media that remains unavailable unusually long.
4. Check stalled Transmission jobs.
5. Verify VPN health.
6. Check disk-space thresholds.
7. Check ROM imports awaiting identification.
8. Check device deployment drift.
9. Notify or attempt bounded remediation where appropriate.
```

Successful routine operations should generate little or no LLM traffic.

This produces an **exception-driven agent architecture** rather than an LLM-powered cron replacement.

---

# 15. Possible Filesystem Layout

The exact server hierarchy should be finalized separately, but the media subsystem should anticipate something like:

```text
/srv/
├── media/
│   ├── movies/
│   ├── tv/
│   └── music/
│
├── games/
│   ├── roms/
│   ├── saves/
│   └── metadata/
│
├── ingestion/
│   ├── incoming/
│   ├── quarantine/
│   ├── staging/
│   └── rejected/
│
├── automation/
│   ├── media/
│   │   ├── desired-state.yaml
│   │   └── policies/
│   │
│   └── games/
│       ├── desired-state.yaml
│       ├── device-profiles/
│       └── policies/
│
└── appdata/
    ├── transmission/
    ├── sonarr/
    ├── bazarr/
    ├── romm/
    └── paperclip/
```

Where possible, container volume design should preserve a common shared filesystem hierarchy so files can be moved or hard-linked efficiently rather than copied unnecessarily.

---

# 16. Security Model

Overmind agents should operate according to least privilege.

An entertainment agent should not need unrestricted root access.

Preferred model:

```text
Agent
 ↓
Overmind tool/API
 ↓
specific service
```

rather than:

```text
Agent
 ↓
sudo shell
 ↓
entire server
```

Acquisition clients should remain isolated from canonical libraries through the quarantine boundary.

VPN routing should remain scoped to services that require it rather than tunneling unrelated Overmind traffic by default.

Secrets such as service API keys and VPN credentials should remain outside agent-editable Markdown or desired-state files.

---

# 17. Role of Local Inference

These workflows are good candidates for local models because much of the reasoning is inexpensive and repetitive.

Examples:

- resolving natural-language titles;
- translating user intent into quality profiles;
- inspecting failure logs;
- generating metadata;
- identifying likely duplicates;
- interpreting ingestion errors;
- summarizing overnight activity;
- reconciling desired state;
- deciding whether an exception requires user attention.

More difficult or consequential tasks can be escalated to stronger hosted models through Paperclip.

This gives Overmind a layered intelligence model:

```text
deterministic automation
        ↓
small/medium local agent
        ↓
stronger local model
        ↓
frontier hosted model when necessary
```

---

# 18. Implementation Sequence

## Phase 1 — Deterministic media stack

Establish:

```text
Transmission
Sonarr
Bazarr
media directories
shared paths
quarantine pipeline
library promotion
Jellyfin/Kodi integration
```

Verify the entire path manually before introducing an agent.

## Phase 2 — ROM management

Establish:

```text
RomM
Igir
ROM quarantine
DAT validation
normalized library
multi-disc handling
device profiles
```

## Phase 3 — Agent API

Implement a small Overmind service exposing bounded operations over:

```text
Sonarr
Bazarr
Transmission
RomM
Igir
ingestion state
storage state
```

## Phase 4 — Paperclip

Add natural-language workflows and desired-state reconciliation.

## Phase 5 — Heartbeats

Add exception-oriented periodic checks and remediation.

## Phase 6 — Device synchronization

Support:

```text
home emulator
travel Fire TV
laptop
future handheld/device
```

with device-specific desired state.

---

# 19. Success Criteria

The entertainment subsystem reaches its intended state when interactions such as these are routine:

> “I want to watch season 2 of Show X.”

> “Follow Show Y from now on.”

> “Stop following Show Y.”

> “What episodes am I missing?”

> “Why didn't last night's episode show up?”

> “Get English subtitles for this episode.”

> “I want to play Game X on Genesis.”

> “Put these five games on the travel setup.”

> “What ROMs failed validation this week?”

> “Make sure my travel media is ready for Friday.”

The user should reason primarily in terms of **desired outcomes**, while Overmind handles the underlying applications, state, retries, validation, and deployment.

---

# 20. Architectural Summary

The defining principle is:

> **Agents provide intent and supervision. Mature software provides deterministic execution.**

For video:

```text
Paperclip
   ↓
Sonarr + Bazarr
   ↓
Transmission
   ↓
Overmind ingestion
   ↓
Jellyfin / Kodi
```

For games:

```text
Paperclip
   ↓
RomM + Igir
   ↓
Overmind ingestion
   ↓
canonical ROM library
   ↓
emulator/device deployment
```

This avoids turning Overmind into a collection of custom scripts while still producing a system that feels substantially more capable than the underlying individual applications.

Overmind becomes not merely a server containing entertainment files, but a persistent system capable of understanding and maintaining the user's desired entertainment environment.