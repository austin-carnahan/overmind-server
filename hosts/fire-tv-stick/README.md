# fire-tv-stick

**Status:** PARTIAL — see [status legend](../../design-notes/README.md#status-legend);
ADB connected, device baseline captured, Projectivy + Home on Fire + Tailscale
sideloaded and confirmed working (Stages 1-3 of the staged plan below). See the
[full implementation plan](../../design-notes/fire_tv_stick_4k_max_implementation_plan.md)
for the complete phased build, and
[runbooks/clients/fire-tv.md](../../runbooks/clients/fire-tv.md) for the
decided ROM pipeline this device is a client of.

## Device baseline (2026-09-19)

Captured via `adb shell getprop`/`df`/`sm list-volumes` after enabling
Developer Options + ADB Debugging and authorizing this Mac's debugging key —
per Phase 1's "capture a device baseline" step, before any modification.

| Property | Value |
| --- | --- |
| Model | `AFTKRT` (Fire TV Stick 4K Max, 2nd gen) |
| Fire OS | 8.1.6.0 (RS8160/3380) |
| Android release / SDK | 11 / 30 |
| CPU ABI list | `armeabi-v7a,armeabi` — **32-bit only, confirmed on this real unit**, matching the plan's platform constraint (Section 3). No `arm64-v8a` in the list at all. |
| Wi-Fi MAC | `fc:0f:76:0c:7a:3e` |
| LAN IP (at capture time) | `192.168.68.62` — DHCP, never reserved; confirmed unreliable in practice (went unreachable, real IP had drifted) — **use the Tailscale IP below for ADB, not this one** |
| Tailscale IP | `100.108.121.2` (`austins-fire-tv`) — stable regardless of local DHCP/network changes, including when the device travels off the home network. This is what `DEVICE_SERIAL` in `scripts/emulation-mode-prepare.sh`/`stage4a-trial.sh` now defaults to. |
| ADB | Reachable over `100.108.121.2:5555` once Tailscale is up and the device is awake; each new connection path (LAN IP vs Tailscale IP) needs its own one-time on-screen authorization approval, even from an already-trusted client. |

### USB ROM cache volume

Real mount ID (not a guessed UUID): **`DF3B-5BC7`**, at `/storage/DF3B-5BC7`.

```text
ROM_DRIVE=/storage/DF3B-5BC7
```

Confirmed writable (probe file created/verified/removed). Reports as
**233GB total**, larger than the implementation plan's "128 GB" header —
confirmed intentional (a bigger drive than originally planned, not a wrong
drive); no action needed, more headroom than assumed.

```text
$ adb shell df -h
/dev/fuse             233G  5.9M  233G   1% /storage/DF3B-5BC7
```

### Installed third-party packages: none yet, at capture time

```text
$ adb shell pm list packages -3
package:com.amazon.tv.legal.notices.overlay.localisation.common
package:com.amazon.tv.settings.v2.overlay.localisation.common
package:com.amazon.tv.parentalcontrols.overlay.localisation.common
```

Since captured: Fire OS update applied. Jellyfin installed via Appstore,
signed in, working (over `http://192.168.68.55:8096` directly —
`jellyfin.home.arpa` works from other LAN clients but the Fire TV wasn't
confirmed to resolve it, likely not using AdGuard as its DNS server; not
yet root-caused, not blocking). Silk confirmed present. Stock streaming
apps (Netflix/Prime) explicitly skipped — not needed for this build.

**Real finding: neither Tailscale nor Projectivy actually appear in this
device's Amazon Appstore listing**, despite generic documentation/citations
suggesting both should — confirmed by direct on-device inspection, not a
search-technique issue, and not an ABI problem either. Two data points now;
updated working assumption is to default every remaining app to sideload
and only trust "available via Appstore" once actually confirmed present on
this real unit. Both are sideloaded and working now — see Stages 2-3 below
and `manifest/apps.yaml` for exact sources/versions.

## Decisions made resolving open questions in the implementation plan

- **R-Shop**: confirmed real, existing project —
  [AverageConsumer/R-Shop](https://github.com/AverageConsumer/R-Shop) — not
  something to build. Matches
  [runbooks/clients/fire-tv.md](../../runbooks/clients/fire-tv.md)'s already
  -decided ROM pipeline (SMB canonical library, R-Shop as the browse/cache
  client). That doc separately flags R-Shop/RetroArch's Android-TV-remote
  compatibility as "not yet verified... needs real hardware testing" (its
  listed target audience is handhelds); accepted here as a working
  assumption per R-Shop's controller-first design, to be confirmed
  naturally when Phase 7 is reached rather than as an earlier blocking spike.
- **Seerr TV client**: [Vermino/seerr-tv](https://github.com/Vermino/seerr-tv),
  not the devmesh-git alternative.
- **RetroArch tuning source, corrected**: it does exist —
  [design-notes/fire_tv_emulation_design.md](../../design-notes/fire_tv_emulation_design.md),
  found after this note originally claimed otherwise. Matches the
  implementation plan's Phase 6.3 bullets almost exactly, with real added
  depth: per-system baselines, a per-title validation-record template, and
  an explicit "known unresolved items" list (controller hotkeys, exact N64
  core per title, which Dreamcast titles need standalone Flycast, whether
  threaded video ever earns its keep). This is the authoritative source for
  Phase 6 — settle its open items through the validation testing it already
  calls for, not by guessing. The two general setup-mechanics references
  ([TroyPoint](https://troypoint.com/retro-games-firestick-firestick-retroarch/),
  [ashcroft.dev](https://ashcroft.dev/blog/a-guide-to-setting-up-retroarch-on-the-amazon-fire-tv/),
  both fairly dated — the latter references RetroArch 1.6.7 and Gen 2 Fire
  TV hardware) remain useful only for install/controller-binding mechanics,
  not settings.
- **Workspace location**: `hosts/fire-tv-stick/` (this directory), matching
  the existing `hosts/cerebrate-pixel6/` convention, not the plan's
  originally-sketched standalone `fire-tv/` repo tree.
- **Projectivy Launcher, real correction**: the plan cited
  `fraee/Projectivy-Launcher` as the upstream source — confirmed via the
  GitHub API to be a fork/mirror with **zero releases**. The real upstream
  is [spocky/miproja1](https://github.com/spocky/miproja1) (package
  `com.spocky.projengmenu`). Its README claims an Amazon Appstore listing,
  but that turned out to be the same "documented ≠ actually present on
  this device" pattern as Tailscale — confirmed not installable via the
  Appstore on this real unit, sideloaded instead (see Stage 2).

## RetroArch: gamepad-only, remote support abandoned (2026-09-20)

**Final decision:** RetroArch is used exclusively with a real gamepad
(8BitDo Pro 2) going forward. The Fire TV remote is not used with
RetroArch at all — not for menu navigation, not as a fallback. The
custom trampoline launcher (`retroarch-launcher-app/`) and its config
(`retro_fix2.cfg`) have been removed from the device and this repo;
**"RetroArch (32-bit)"**, the plain unmodified app, is the only tile now.
The remote remains fully normal for every other app on the device
(Projectivy, Jellyfin, R-Shop, etc.) — this decision is scoped to
RetroArch specifically.

This closes out an extensive real-hardware debugging effort, kept below
for the record since the underlying RetroArch regressions are real and
may matter again later (e.g. if a future RetroArch update changes this
calculus, or another remote-driven Android TV app hits the same family
of bugs):

**Bug 1 — remote's OK button did nothing in RetroArch's menu.**
Root-caused (via RetroArch's own GitHub history, not speculation) to a
real RetroArch 1.22.2 regression: a fix for a different bug ("Enter key
not working in menus", PR
[#18405](https://github.com/libretro/RetroArch/pull/18405)) added a side
effect to `input/drivers/android_input.c` that silently relabels any
`AKEYCODE_DPAD_CENTER` (23) press — exactly what this remote's OK button
sends — as `AKEYCODE_ENTER` (66) before RetroArch's own button-state
array sees it, so the remote's autoconfig bind (`input_b_btn = "23"`)
checks a slot that can never be set. Filed upstream as
[libretro/RetroArch#19593](https://github.com/libretro/RetroArch/issues/19593)
with a suggested minimal patch, not submitted as a PR (no build/test
environment here). Worked around at the time with
`input_player1_b_btn = "66"` + `menu_swap_ok_cancel_buttons = "true"` in
a custom config, delivered via a trampoline launcher app since a plain
tap on RetroArch's icon has no way to load a non-default config file.

**Bug 2 — adding a real gamepad broke the workaround.** With the 8BitDo
Pro 2 also connected, using the remote after the gamepad caused
RetroArch to reassign ports ("Fire Stick Remote configured in port 1",
"8BitDo Controller configured in port 2"), after which the gamepad
produced no input at all (every custom bind was `input_player1_*`, and
the gamepad was no longer in port 1). Root-caused to a known Android TV
bug ([libretro/RetroArch#16873](https://github.com/libretro/RetroArch/issues/16873)):
reconnecting/re-activating an input device reports a changed OS-level
identity, which RetroArch reads as a brand-new controller and
increments its port rather than reusing the original. Two other
hypotheses were tried and reverted first (rebinding the OK-button fix
off the global menu-swap broke the remote's Back key without fixing the
port bug; disabling `input_autodetect_enable` broke every input device
entirely) before finding RetroArch's actual purpose-built setting for
this exact bug, `android_input_disconnect_workaround`. **This did not
actually fix the reported symptom when tested for real** — the
port-reassignment recurred even with the workaround enabled, which is
what settled the decision to stop trying to reconcile the remote with
RetroArch's Android input handling at all, rather than keep chasing
further Android-TV-specific edge cases in a two-input-device setup.

**Ruled out along the way** (kept so this isn't re-litigated if anyone
revisits remote support later): Menu Swap / Unified Menu Controls
toggles alone; redirecting RetroArch's "Configuration files" directory;
regenerating the autoconfig profile via "Save Controller Profile";
removing `input_device_type = "remote"` from the bundled autoconfig
(required a repackaged, re-signed APK to test).

## RetroArch playlists (XMB console tabs)

RetroArch's XMB menu only shows a console tab (icon row) for a system once
a non-empty playlist (`.lpl`) exists for it — there's no "available
consoles" view otherwise. Playlists are normally built by RetroArch's own
"Import Content → Scan Directory", but that requires menu navigation,
which (like the OK-button issue above) can't be driven via `adb shell
input` — RetroArch reads raw input devices directly, not synthetic
Android key events. Since playlist files are plain JSON on shared storage
(`/storage/emulated/0/RetroArch/playlists/`, not app-private), the fix is
the same class of workaround as the config edits above: build the `.lpl`
directly and push it.

**Naming is exact and load-bearing.** RetroArch matches its XMB icon and
thumbnail set to a playlist's base filename (and each item's `db_name`)
against Libretro's own canonical database/thumbnail-repo names — not our
own internal platform keys — so spelling/capitalization/spaces/hyphens
must match exactly (e.g. `Sega - Mega Drive - Genesis`, not `genesis` or
`Sega Genesis`). ROM folder names stay simple either way; only the
playlist file, its items' `db_name`, and the eventual
`thumbnails/<canonical name>/` directory need to match. This is now
formalized in `services/ingestion/romsets/curate`'s `playlist` subcommand
and `curate/platforms.py`'s canonical-name table (covering genesis, nes,
snes, n64, psx, dreamcast) rather than a one-off hand-built file.

First playlist (2026-09-20): built from the 26 Genesis titles actually
downloaded to `/storage/DF3B-5BC7/roms/genesis` at the time (not the full
100-title library tier — `curate` running on Overmind has no visibility
into what a given device has actually downloaded via R-Shop), pushed to
`playlists/Sega - Mega Drive - Genesis.lpl`, confirmed working: a new
console tab appeared on RetroArch's XMB main menu showing the real
library. Regenerate (device-side, from an actual directory listing, or via
`curate playlist` if listing everything curated is acceptable) after
downloading more titles.

## R-Shop bugs and workarounds

Three real, separate bugs/gaps, all worked around without touching
R-Shop's own code or rebuilding it:

**1. No home-screen tile.** R-Shop's manifest doesn't declare
`LEANBACK_LAUNCHER`, so it's invisible on Fire TV's actual TV-apps row
(it's still reachable via Projectivy's "Mobile Apps"/All Apps list, just
not prominently). A trampoline app (`rshop-launcher-app/`, same pattern as
RetroArch's) was built for a proper tile, but — unlike RetroArch's, which
passes a required launch argument — this one passed nothing special; it
existed purely for tile visibility, and R-Shop's own icon works
identically. Removed again (2026-09-20) as not worth maintaining a second
launcher for: default to R-Shop's own icon in Projectivy's app list
instead.

**2. Onboarding is completely unreachable.** The "Welcome to R-Shop"
screen's four setup options (Pair RomM / RomM login / Add my own server /
Local games only) all route through the same first step -- a system
folder-picker call (`ACTION_OPEN_DOCUMENT_TREE`) -- before doing anything
else. Fire OS ships **no app at all** capable of handling that intent
(confirmed via `pm query-activities -a android.intent.action.OPEN_DOCUMENT_TREE`,
before and after installing both Amaze File Manager and MiXplorer with its
SAF document-provider setting enabled -- neither implements a
self-contained picker *activity*, only a provider role that needs a picker
*host* app to work, and Fire OS has neither). This is a real Android TV
platform gap, not an R-Shop bug, and not fixable by installing yet another
file manager.

The actual bypass: R-Shop's release build is `run-as`-debuggable (unlike
RetroArch's), giving full read/write access to its private storage with no
root and no SAF picker involved at all:

```sh
# 1. Skip onboarding entirely -- gates purely on one bool (lib/main.dart):
#    home: onboardingCompleted ? HomeView() : OnboardingScreen()
adb push FlutterSharedPreferences.xml /data/local/tmp/
adb shell run-as com.retro.rshop cp /data/local/tmp/FlutterSharedPreferences.xml \
  shared_prefs/FlutterSharedPreferences.xml
# (added: <boolean name="flutter.onboarding_completed" value="true" />)

# 2. Give it something to show -- config.json schema reverse-engineered
#    from lib/models/config/{app_config,system_config,source}.dart and
#    lib/services/config_storage_service.dart (getApplicationDocumentsDirectory()
#    -> app_flutter/config.json on Android):
adb push config.json /data/local/tmp/
adb shell run-as com.retro.rshop cp /data/local/tmp/config.json app_flutter/config.json
```

Verified working end-to-end: boots straight into a real, properly-rendered
console view (tested with a placeholder local system pointed at the
confirmed-writable `DF3B-5BC7` USB volume), skipping the broken screen
entirely.

**3. A hand-written config with an SMB source loaded but showed 0 games.**
Once `services/file-sharing` was deployed and a real config was written
(source of type `smb`, host/share/path, plus a `manual_mappings` entry
tying the `megadrive` system to it — the documented v3 schema in
`lib/models/config/{source,system_config}.dart`), R-Shop loaded it without
error but still showed "Local files only" and 0 games. Root cause,
confirmed by reading `game_list_controller.dart`: the actual game-loading
path branches on the **legacy** `systemConfig.providers` list being empty,
not on the v3 `sources`/`manual_mappings` fields — those only ever get
folded into `providers` by `SourcesNotifier`'s own runtime rebuild
(triggered by in-app source mutations), which never runs for a config
written directly to disk via the onboarding-bypass mechanism above. Fixed
by writing a direct legacy `providers` entry (`type: smb`, `host`, `port`,
`share`, `path`, `auth`) alongside the v3 `sources` entry — the former is
what's actually read for game loading, the latter keeps the in-app Sources
screen and future `SourcesNotifier`-driven edits consistent. Confirmed via
screenshot: "100 Games", every card tagged `SMB`, real curated titles.

**Local storage layout (2026-09-20):** `target_folder` is
`/storage/DF3B-5BC7/roms/genesis` — matching the `roms/<system>/` layout
already decided in
[fire_tv_emulation_design.md](../../design-notes/fire_tv_emulation_design.md#7-rom-storage-model),
not an ad-hoc path. RetroArch's `rgui_browser_directory` (previously
unset, `"default"`) is now pointed at the shared parent
`/storage/DF3B-5BC7/roms` so its own Load Content browser starts at the
same tree R-Shop populates. One real constraint, not fixable from this
side: R-Shop's SMB provider type can't self-describe every platform the
way its RomM integration can (`Source.supportsAutoMap` is `true` only for
`SourceType.romm` — confirmed in `lib/models/config/source.dart`), so
adding each future curated platform still needs one small `SystemConfig`
block (id/name/`target_folder`/`manual_mappings`) added to config.json —
not a full reconfiguration, since the underlying `smb` source (host,
share, credentials) is defined exactly once and reused, but not fully
automatic either.

**Resolved via Stage 8's real gamepad (2026-09-20):** confirm/menu are
bound to real gamepad buttons (`LogicalKeyboardKey.gameButtonA` /
`gameButtonStart` in `lib/core/widgets/console_focusable.dart` and
`lib/core/input/app_actions.dart`), which the Fire TV remote cannot
send — it sends `LogicalKeyboardKey.select` (Android `DPAD_CENTER`)
instead, which isn't in R-Shop's accepted-keys list. Same root-cause
family as the RetroArch `DPAD_CENTER` regression above. Deliberately not
patched at the time, betting on Stage 8's Bluetooth controller sending
`gameButtonA`/`gameButtonStart` natively — confirmed correct: the 8BitDo
Pro 2 navigates R-Shop's menu fine. If a real controller ever doesn't
work here, the fix would need a real Flutter rebuild (isolated SDK
setup — see git history
for `retroarch-launcher-app/README.md`, since removed, for the general
javac/d8/aapt2-without-Gradle pattern if this needs revisiting).

## `retroarch-launcher-app/` — removed (2026-09-20)

Used to exist here: a minimal hand-built trampoline app (no Gradle —
`javac`/`d8`/`aapt2` directly) that launched RetroArch with a custom
config carrying the OK-button fix, shown as its own tile ("RetroArch
(Fixed)"). Removed along with `retro_fix2.cfg` as part of the decision to
abandon remote support in RetroArch entirely and go gamepad-only — see
"RetroArch: gamepad-only, remote support abandoned" above for the full
story, including a real banner/icon-cache saga this trampoline went
through before being removed. **"RetroArch (32-bit)"**, the plain
unmodified app, is the only RetroArch tile now.

## Provisioning workspace

```text
hosts/fire-tv-stick/
├── README.md          # this file
├── manifest/
│   └── apps.yaml       # per-app: upstream, package, version, artifact,
│                       #   architecture, install source -- verified
│                       #   against each project's real current release,
│                       #   not copied from the plan's citations unchecked
├── apks/               # downloaded APKs land here (gitignored contents)
├── scripts/            # Phase 12 automation, not yet written
├── config/
│   ├── projectivy/
│   └── retroarch/       # deployed settings once Phase 6 validation locks them in
└── state/               # local run state, not committed
```

`manifest/apps.yaml` currently records architecture as "unconfirmed" for
R-Shop, Seerr TV, Home on Fire, and Projectivy — none of their releases
publish a per-ABI split the way SmartTube's does, so each needs a real
`aapt dump badging` (or unzip `lib/`) check against the downloaded APK
before installing, given this device's confirmed 32-bit-only ABI. Not
assumed clean just because SmartTube's was.

## Staged plan and progress

Re-sequenced from the implementation plan's phase order into concrete
stages, given what's actually been learned on real hardware:

1. **Close out the stock baseline** — DONE. Fire OS updated, Jellyfin
   signed in and working, Silk confirmed, stock streaming apps skipped.
2. **Sideload the appliance shell (Projectivy + Home on Fire)** — DONE.
   Both installed, architecture verified before install (`unzip lib/`
   inspection, not assumed), `WRITE_SECURE_SETTINGS` granted, accessibility
   service confirmed enabled via `adb shell settings get`, Projectivy set
   as Home-button target, launch-on-boot/wake enabled. Known open item,
   not blocking: the escape-back-to-Amazon-Home gesture isn't confirmed
   working (may be double-press, not long-press) — deferred to Stage 10.
3. **Sideload Tailscale opportunistically** — DONE. Installed from the
   IzzyOnDroid/F-Droid archive mirror (no official direct download and not
   Appstore-visible on this device), architecture verified, launched
   successfully. Full login/network-mode validation deferred to Stage 9.
4. **Media/discovery clients** — DONE. SmartTube (`armeabi-v7a`, package
   `org.smarttube.stable`) and Seerr TV (Vermino, package `com.seerr.tv`)
   both installed, architecture-verified, launched cleanly.
5. **RetroArch baseline** — IN PROGRESS, remote support abandoned
   (2026-09-20). Real, root-caused RetroArch 1.22.2 regressions were
   found and worked around for a while (remote OK-button, then a
   controller port-reassignment bug once a real gamepad was added), but
   the port bug's fix didn't actually hold up under real testing — see
   "RetroArch: gamepad-only, remote support abandoned" below for the
   full story. Final decision: vanilla RetroArch ("RetroArch (32-bit)"),
   gamepad-only, no remote support attempted. Still remaining: apply
   [fire_tv_emulation_design.md](../../design-notes/fire_tv_emulation_design.md)'s
   settings, point at the confirmed `DF3B-5BC7` USB volume, run the
   per-system validation set.
6. **R-Shop integration** — DONE for browsing. Installed, architecture-
   verified, given a real home-screen tile, two real platform-level bugs
   found and worked around (no rebuild, no root) — see "R-Shop bugs and
   workarounds" below. `services/file-sharing` is deployed and R-Shop's
   config now points a real `smb` provider at it (`192.168.68.55`, share
   `romsets`, path `genesis`) instead of the earlier local-only
   placeholder — confirmed end-to-end via screenshot: "100 Games", every
   card tagged `SMB`, real titles (Aladdin, Castlevania - Bloodlines,
   Beyond Oasis, ...) matching the curated Genesis library tier exactly.
   One real config-schema gap hit and fixed along the way: R-Shop's actual
   game-loading path reads the **legacy** `system.providers` list
   (`if (systemConfig.providers.isEmpty) → treat as local-only`), not the
   newer `sources`/`manual_mappings` v3 fields — those only get synced
   into `providers` by the app's own runtime `SourcesNotifier` rebuild,
   which never runs for a config written directly to disk. Fixed by
   writing both: a direct legacy `providers` entry (what's actually read)
   plus the v3 `sources` entry (for the in-app Sources screen/future-
   proofing). Box art is currently blank — R-Shop has no artwork source
   configured yet (a separate concern from ScreenScraper's own downloaded
   media in `curate`'s cache, not wired to R-Shop), not yet addressed.
   Confirm/menu navigation confirmed working with a real gamepad
   (8BitDo Pro 2, see Stage 8) — the `gameButtonA`/`gameButtonStart` gap
   this was waiting on is resolved. Still remaining: install/cache/remove
   flows themselves are unverified with real button presses beyond
   navigation; the direct-launch handoff into RetroArch is untouched.
7. **Save sync** (Syncthing-Fork) — not yet started.
8. **Controllers** — IN PROGRESS. 8BitDo Pro 2 paired via Amazon's
   Bluetooth settings, confirmed working for R-Shop navigation and (as a
   plain gamepad, no custom config) RetroArch. Resolved R-Shop's
   remaining confirm/menu gap as anticipated. Hit a real Android-TV-level
   controller port-reassignment bug when used alongside the Fire TV
   remote in RetroArch specifically — see "RetroArch: gamepad-only,
   remote support abandoned" below; resolved by not using the remote
   with RetroArch at all, not by fixing the underlying bug. Hotkey
   mapping still not started.
9. **Travel validation** — actually exercise the Tailscale path installed
   in Stage 3 — not yet started.
10. **Final polish + acceptance pass** — Projectivy launcher cleanup,
    resolve the Stage 2 escape-gesture item, run the plan's full
    Acceptance Tests checklist — not yet started.

Next up: Stage 6's real library browsing is confirmed working end-to-end
now (SMB deployed, real 100-title Genesis library, R-Shop pointed at it
correctly) — remaining work there is install/cache/remove validation with
real button presses, not infrastructure. Stage 5's per-system validation
set is still open — likely next real step is that, or picking up Stage 7/8
in the meantime.
