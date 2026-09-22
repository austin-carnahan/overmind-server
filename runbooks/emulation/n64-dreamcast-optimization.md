# N64 and Dreamcast optimization runbook

**Status:** PROPOSED — see [status legend](../../design-notes/README.md#status-legend);
operationalizes
[N64 and Dreamcast Automated Emulator Validation Design](../../design-notes/n64_dreamcast_emulator_settings_handoff.md),
whose Phase 1 harness isn't built yet. Until it is, every step below is run
manually by an operator (human or agent) following this procedure by hand;
the harness's job is to automate exactly these steps, not replace them.

N64 and Dreamcast are the hardest platforms in this project to emulate well
and have the most per-game variance — unlike Genesis/NES/SNES, a "good
enough" global default reliably breaks specific titles. Expect this runbook
to be used per-game far more often than per-platform.

## Prerequisites

- Fire TV Stick powered on, on the same LAN as the operator's machine.
- `adb connect <current LAN IP>:5555` — **session-based only**, established
  fresh each time (see the design doc's "Connectivity model" section for why
  this deliberately isn't a persistent background connection). Approve the
  on-screen prompt if this client hasn't connected before.
- The target game already deployed to the device (`roms/n64/` or
  `roms/dreamcast/`, per [design-notes/fire_tv_emulation_design.md](../../design-notes/fire_tv_emulation_design.md#7-rom-storage-model)).
- Know the exact on-device content path (`adb shell ls /storage/DF3B-5BC7/roms/<platform>/`).

## Hard constraint: launch via intent, never via menu

Confirmed elsewhere in this repo (see the design doc's "Known input-automation
constraint" section): RetroArch does not respond to synthetic ADB input
events at the menu level. **Every launch in this runbook uses a direct
Android launch intent**, never `adb shell input keyevent` menu navigation.

```sh
# RetroArch, direct content launch
adb shell am start -n com.retroarch/.browser.retroactivity.RetroActivityFuture \
  -e ROM '/storage/DF3B-5BC7/roms/n64/Example Game (USA).z64' \
  -e LIBRETRO '/data/data/com.retroarch/cores/parallel_n64_libretro_android.so' \
  -e CONFIGFILE '/storage/emulated/0/RetroArch/retroarch.cfg'

# Standalone Flycast (Dreamcast alternate core) -- confirm real package/
# activity names on-device before first use, do not assume these:
adb shell am start -n <flycast-package>/<flycast-activity> \
  -e <flycast-equivalent-content-extra> '/storage/DF3B-5BC7/roms/dreamcast/Example Game (USA).chd'
```

## Testing a single game

1. **Connect and reset state.** `adb connect`, `adb logcat -c`, confirm no
   stale RetroArch/Flycast process (`adb shell pidof com.retroarch`; kill if
   present).
2. **Launch directly into content** (above), with RetroArch's running
   statistics overlay and file logging already enabled in the test profile
   (see the design doc's Phase 1).
3. **Tier 1 boot sweep**: wait the expected boot interval, `adb exec-out
   screencap -p > screen.png`, confirm a recognizable title/menu/gameplay
   frame (not black/frozen). Collect the RetroArch log and a filtered
   `adb logcat -v threadtime` window around launch.
4. **Tier 2 representative gameplay** (only if Tier 1 passes): load the
   game's save-state/save-file fixture if one exists yet (none do initially
   — see "Building fixtures" below), run a short warm-up, then sample
   RetroArch's statistics overlay (core-requested FPS, actual video FPS,
   audio underrun/blocking) via repeated screenshots, without screen
   recording running (recording adds load and skews the numbers).
5. **Classify** using the design doc's status vocabulary (`pass`,
   `pass_with_override`, `degraded`, `manual_review`, `fail_boot`,
   `fail_crash`, `fail_performance`, `fail_graphics`, `fail_input`).
6. **If it fails**, apply the platform's tuning ladder (design doc,
   "Controlled Tuning Loop") one step at a time, re-running steps 2-5 after
   each change, and stop at the first passing profile — don't over-tune past
   what's needed.
7. **Record the result** (see "Result record" below) and, if a
   `pass_with_override` was needed, write the per-game override.
8. **Clean shutdown**: return to a known state before testing the next game
   — don't leave the emulator running or a modified global config in place.

## Testing a platform sweep

Run step 1-3 (Tier 1 only) across every game in the library tier before
doing any Tier 2 work — it's cheap and finds crashes/black-screens/missing-
content issues fast. Only run Tier 2 on games that passed Tier 1. Don't run
Tier 3 (soak/regression) except for the default profile itself and titles
already flagged difficult — it's expensive and most titles don't need it.

## Building fixtures (save states / input scripts)

No representative-gameplay fixtures exist yet for any N64 or Dreamcast
title in this library. Per the design doc's fixture preference order (known
save file + navigation script, then version-pinned save state + input
script), building these is inherently manual/per-game work — there's no way
to script "reach a demanding section" without first playing to that section.
Do this by hand: play the game normally to a representative point (ideally
a graphically/CPU demanding one, not just anywhere), save, and pull the save
file/state via `adb pull`. Record the emulator/core version and config hash
alongside it — a fixture is invalid once either changes (design doc,
"Per-Game Test Manifest").

## Result record

One record per game/profile/scenario/software-version, per the design doc's
"Result Record" section — game ID, ROM hash, emulator/core/version,
configuration hash, scenario, launch outcome, FPS/audio samples, process
health, visual findings, artifact paths, final status and rationale. No
schema/storage location is finalized yet (see design doc "Remaining
Decisions") — until it is, keep results as one Markdown or YAML file per
game under a `results/` directory alongside this runbook, and note the
schema is expected to change.

## Verification

A test run is complete when: the result record exists, artifacts (log,
screenshots, and a recording if visual issues were found) are saved, and the
game has a final status. A `pass_with_override` isn't verified until the
override is actually written to the per-game config and re-tested once more
against that exact override (not assumed from the tuning-loop result alone).

## Rollback

- **Per-game override causing problems**: delete the override file/config
  entry; the game falls back to the platform default profile.
- **A tuning-loop change made mid-session left global config modified**:
  restore the platform's baseline config (kept version-controlled/backed up
  before any test session starts) rather than hand-reverting individual
  settings.
- **Bad fixture** (save state stops loading after an emulator/core update):
  discard it and rebuild per "Building fixtures" above; don't keep testing
  against a fixture whose validity is in question.

## Reference documentation for per-game quirks

Verified 2026-09-22 (fetched directly unless noted). Consult these before
building a fixture or reaching for the tuning ladder on a difficult title
— per-game answers already exist for a lot of this.

**N64 (Mupen64Plus-Next / ParaLLEl):**

- [docs.libretro.com/library/mupen64plus](https://docs.libretro.com/library/mupen64plus/)
  — authoritative core-options reference: CPU core (dynamic recompiler /
  cached interpreter / pure interpreter), RSP (HLE vs LLE via ParaLLEl-RSP),
  graphics plugin choice (GLideN64 default, Angrylion, ParaLLEl-RDP),
  texture packs, MSAA, framebuffer/depth options. No dedicated
  ParaLLEl-N64-specific docs.libretro.com page exists — don't look for one.
- [github.com/libretro/parallel-n64/issues](https://github.com/libretro/parallel-n64/issues)
  — real per-config quirks, e.g. Angrylion RDP integration (#608),
  Vulkan/parallel rendering errors (#649), `gfxplugin-accuracy` being an
  HLE-only option that's a silent no-op under LLE.
- [forums.libretro.com/t/mupen64plus-next-correct-plugins-for-accuracy/29147](https://forums.libretro.com/t/mupen64plus-next-correct-plugins-for-accuracy/29147)
  — community discussion of accuracy-vs-speed plugin tradeoffs. Not
  independently re-verified this pass; treat as a starting point, not gospel.
- Explicitly **not useful, don't waste time on**: the official
  mupen64plus GitHub wiki just redirects to mupen64plus.org, which has no
  visible compatibility list; various old personal-fork wikis (ricrpi,
  ttk2, Tim237 mupen64plus forks) claiming a "Game Compatibility List" are
  abandoned, not authoritative; no stable/citable GLideN64
  compatibility-list URL exists (past attempts lived in an editable Google
  Doc linked from GitHub issues, not a stable page).

**Dreamcast (Flycast):**

- **Core-choice decision (revised 2026-09-22, corrected same day):**
  start with the RetroArch Flycast core — it's already sideloaded, zero
  friction to test right now. Escalate to standalone Flycast only on a
  concrete problem, not as a default first step. **Correction to the
  original research**: `docs.libretro.com/library/flycast` now attributes
  the RetroArch core directly to `flyinghead/flycast` upstream (not the
  old, genuinely-deprecated `libretro/flycast` fork) — confirmed via
  `flyinghead/flycast`'s own CI building libretro-target artifacts
  directly. RetroArch's shipped core is **not** stale/lagging the way the
  first research pass assumed; that concern was already solved. Also
  confirmed no alternative Dreamcast-capable libretro core exists
  (Redream, Deecy — both standalone-only). See the
  [design doc's Established Configuration Baseline](../../design-notes/n64_dreamcast_emulator_settings_handoff.md#sega-dreamcast)
  for the full correction and remaining (not re-verified) escalation
  triggers: two upstream issues documenting rendering differences at the
  time
  ([flyinghead/flycast#1007](https://github.com/flyinghead/flycast/issues/1007),
  [#1308](https://github.com/flyinghead/flycast/issues/1308)), and no
  save-state/rewind advantage either way
  ([libretro/RetroArch#17779](https://github.com/libretro/RetroArch/issues/17779)
  still open). No FPS numbers exist for this exact device — verify
  empirically once testing actually starts.
- [docs.libretro.com/library/flycast](https://docs.libretro.com/library/flycast/)
  — full core-options reference AND real per-game notes: e.g. Sonic
  Adventure (PAL) needs VGA output mode, Unreal Tournament (USA) needs the
  VGA cable type set to avoid crashing, known polygon-sorting artifacts.
  Start here for any Dreamcast title acting up.
- [github.com/TheArcadeStriker/flycast-wiki/wiki](https://github.com/TheArcadeStriker/flycast-wiki/wiki)
  — actively maintained third-party wiki: settings, config files/CLI
  params, troubleshooting, BIOS/Arcade ROM verification, NAOMI/Atomiswave
  button mapping and VMU guides. Broadest current third-party reference.
- [github.com/flyinghead/flycast](https://github.com/flyinghead/flycast)
  (issues/discussions) — canonical upstream repo (current maintainer;
  `libretro/flycast` is explicitly deprecated in favor of this one). Real
  per-game reports live in its issue tracker.
- [emulation.gametechwiki.com/index.php/Flycast](https://emulation.gametechwiki.com/index.php/Flycast)
  and [.../Nintendo_64_emulators](https://emulation.gametechwiki.com/index.php/Nintendo_64_emulators)
  — the r/emulation community wiki's per-system pages; general tuning
  philosophy and emulator overviews. Site blocked automated fetch this
  pass (bot-blocking, not evidence it's down) — open in a browser to
  confirm current content before relying on it.

## Controller and UX checks (manual, not automatable)

Per the design doc's "Human Review Boundary" and "Controller and UX
Validation" sections, these need a human at the device, not this runbook's
ADB procedure: Bluetooth controller reconnect reliability, Player 1/2
assignment stability, hotkey collisions with Fire TV Home/Back, audio
crackle/desync (Android screen recording captures no audio at all), and
whether a test scene is actually representative of real play.
