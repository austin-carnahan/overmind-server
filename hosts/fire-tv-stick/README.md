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
| LAN IP (at capture time) | `192.168.68.62` — DHCP, not yet reserved; confirm before relying on it long-term |
| ADB | Reachable over `192.168.68.62:5555`, authorized |

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

## RetroArch OK-button fix

**Symptom:** the Fire TV remote's physical OK/Center button did nothing in
RetroArch's menu (Settings, XMB) — D-pad and the Back key worked fine, in
every combination of Menu Swap OK/Cancel and Unified Menu Controls
settings. This was real and reproducible, not user error.

**Root cause (confirmed via RetroArch's own GitHub history, not
speculation):** RetroArch 1.22.2 shipped a regression. A fix for a
different bug ("Enter key not working in menus", PR
[#18405](https://github.com/libretro/RetroArch/pull/18405), merged
2025-11-16, first released in 1.22.2) added a side effect to
`input/drivers/android_input.c`: any press reporting Android keycode
`AKEYCODE_DPAD_CENTER` (23) — exactly what this remote's OK button
sends — gets silently relabeled internally as `AKEYCODE_ENTER` (66)
*before* it reaches the button-state array RetroArch's menu and RetroPad
system both read. The remote's autoconfig binds `input_b_btn = "23"`,
which checks a slot that can now never be set, since every real press
lands in slot 66 instead. This affects any Android device whose confirm
button reports keycode 23 (TV remotes, CEC remotes) — it is not specific
to this remote being autoconfigured as `input_device_type = "remote"`
(verified by removing that field entirely via a repackaged APK; no
change in behavior, ruling out that theory before finding the real one).

**The fix (two config values, no root, no core APK change):**

```ini
input_player1_b_btn = "66"           # bind Center to where it actually lands now
menu_swap_ok_cancel_buttons = "true" # make that slot mean "confirm", not "cancel"
```

These live in `config/retro_fix2.cfg` on the device's accessible storage
(`/storage/emulated/0/RetroArch/config/`, not committed here — device
state). A normal tap on RetroArch's own icon has no way to tell it to
load a non-default config file, so a plain launch would still hit the
bug. The fix is delivered via a small trampoline app instead — see
`retroarch-launcher-app/` below.

Also set in this file (2026-09-20): `rgui_browser_directory` — was
`"default"` (unset), now `/storage/DF3B-5BC7/roms`, the same shared parent
R-Shop downloads into (see "Local storage layout" under the R-Shop section
below) — so RetroArch's own Load Content file browser starts at the same
tree instead of the device's generic root.

**Filed upstream:** [libretro/RetroArch#19593](https://github.com/libretro/RetroArch/issues/19593)
— no existing issue covered this exact regression (confirmed via GitHub
search before filing). Includes a suggested minimal patch (gate the
`DPAD_CENTER → ENTER` rewrite on `AINPUT_SOURCE_DPAD`, verified this
remote reports `Sources: 0x00000301` = `SOURCE_KEYBOARD | SOURCE_DPAD`,
distinguishing it from a plain external keyboard), not submitted as a
PR since there's no build/test environment here to validate it beyond
the empirical device-level check.

**Ruled out along the way** (kept here so this isn't re-litigated):
Menu Swap / Unified Menu Controls toggles alone (they only affect the
Android system Back key's role, a completely separate code path from
the joypad button system Center lives in); redirecting RetroArch's
"Configuration files" directory; regenerating the autoconfig profile via
"Save Controller Profile"; removing `input_device_type = "remote"` from
the bundled autoconfig (required a repackaged, re-signed APK to test —
useful for ruling out the wrong theory, not the actual fix).

## RetroArch controller port reassignment (8BitDo Pro 2)

**Symptom (2026-09-20):** with a real gamepad (8BitDo Pro 2) paired
alongside the Fire TV remote, using the remote after the gamepad caused
RetroArch to reassign ports — "Fire Stick Remote configured in port 1",
"8BitDo Controller configured in port 2" — and the gamepad then produced
no input at all (port 2 has no bindings; every custom bind in
`retro_fix2.cfg` is `input_player1_*`, for the remote fix above).

**Two things ruled out first, in order, each made things worse or did
nothing:**

1. Suspected the OK-button fix's global `menu_swap_ok_cancel_buttons =
   "true"` was inverting the gamepad's physical East button (RetroArch's
   RetroPad A/B naming follows SNES layout, so on an Xbox-style pad
   physical East = RetroPad A — a well-known point of confusion) from
   confirm to cancel. Rebinding the remote's fix from
   `input_player1_b_btn` to `input_player1_a_btn` and turning the swap
   off did NOT fix the port-reassignment bug (unrelated mechanism) and
   broke the remote's physical Back key as a side effect — reverted.
2. Suspected `input_autodetect_enable` (governs automatic port
   assignment on device connect/activity). Disabling it broke every
   input device entirely, including the remote — reverted immediately.

**Actual root cause, confirmed via a real GitHub issue matching this
exact symptom
([libretro/RetroArch#16873](https://github.com/libretro/RetroArch/issues/16873)):**
a known Android TV bug where reconnecting/re-activating an input device
reports a changed OS-level device identity, which RetroArch reads as a
brand-new controller rather than the same one — incrementing its port
instead of reusing the original.

**The fix:** `android_input_disconnect_workaround = "true"` in
`retro_fix2.cfg` (was `"false"`, RetroArch's own default) — a real,
purpose-built RetroArch setting for exactly this bug, confirmed via
RetroArch's own source
(`settings/settings_def_input_android_workaround.h`) and the linked
issue thread, not a guess.

**Known limitation, by RetroArch's own setting description:** "Impedes 2
players with identical controllers." The workaround almost certainly
identifies "is this a reconnect of the same controller" by device
name/vendor/product ID rather than the OS-level identity (since that's
exactly what the underlying bug corrupts) — which two identical
controllers share, so a second identical 8BitDo Pro 2 added for local
multiplayer would likely get misidentified as a reconnect of the first.
**Deliberately left enabled for now** (single gamepad + remote); revisit
when a second identical controller is actually added — likely needs to
be turned back off in favor of a different per-session port-assignment
approach at that point, not yet investigated.

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

**What's still open, deliberately unfixed:** once past onboarding,
confirm/menu are bound to real gamepad buttons
(`LogicalKeyboardKey.gameButtonA` / `gameButtonStart` in
`lib/core/widgets/console_focusable.dart` and `lib/core/input/app_actions.dart`)
which this remote cannot send -- it sends `LogicalKeyboardKey.select`
(Android `DPAD_CENTER`) instead, which isn't in R-Shop's accepted-keys
list. Same root-cause family as the RetroArch `DPAD_CENTER` regression
above, and the fix would be similarly small (add `select` to the accepted
keys) -- but deliberately not patched, since Stage 8's Bluetooth
controller will send `gameButtonA`/`gameButtonStart` natively and makes
this moot. Revisit only if a real controller still doesn't work; the fix
would need a real Flutter rebuild (isolated SDK setup documented in
`retroarch-launcher-app/README.md`'s spirit, not yet written up for
R-Shop specifically since it wasn't needed here).

## `retroarch-launcher-app/`

A minimal hand-built Android app (no Gradle — compiled directly with
`javac`/`d8`/`aapt2` from the Android SDK build-tools, source in
`retroarch-launcher-app/src/`) with a single trampoline Activity: on
launch it starts RetroArch's `RetroActivityFuture` directly with
`-e CONFIGFILE /storage/emulated/0/RetroArch/config/retro_fix2.cfg`,
then finishes immediately. It shows up as its own launcher tile,
**"RetroArch (Fixed)"**, self-signed (debug-equivalent key, see
`retroarch-launcher-app/debug.keystore` — gitignored, regenerate with
`keytool` if lost, self-signing doesn't need to match anything).
This is the tile to actually launch RetroArch from going forward — the
plain "RetroArch (32-bit)" tile still exists but launches without the
fix. Rebuild steps are in `retroarch-launcher-app/README.md`.

**Missing home-row icon, fixed (2026-09-20):** the trampoline showed no
tile image at all, while the real RetroArch app did. Root cause, confirmed
by pulling and comparing both APKs with `aapt2 dump badging`: Android
TV's home-row tile reads `android:banner`, a dedicated landscape image —
real RetroArch ships a proper 320×180 banner (`res/O5.png`) separate from
its icon; the trampoline reused the same 192×192 **square** icon for both
`android:icon` and `android:banner`, which the launcher silently declines
to render as a banner. Fixed by adding a real 320×180
`res/mipmap/ic_banner.png` (generated from the existing flat-color
placeholder icon — there's no real logo here, just a correctly-shaped
version of the same placeholder) and pointing `android:banner` at it
instead of reusing `ic_launcher`. Confirmed via `aapt2 dump badging` that
the rebuilt APK resolves `banner='res/mipmap/ic_banner.png'` distinct from
`icon='res/mipmap/ic_launcher.png'`, matching the real app's pattern.
Installed as an in-place upgrade (`adb install -r`, same `debug.keystore`,
no uninstall needed).

**Real assets swapped in, and a separate launcher-cache gap found
(2026-09-20):** the flat-color placeholder banner/icon were replaced with
the real RetroArch banner and mascot icon, extracted directly from the
user's own installed RetroArch APK (`res/O5.png`, a real 320×180
banner) — legitimate reuse, since this trampoline only ever launches that
same app. A square icon was cropped from the same banner (just the alien
mascot, avoiding the wordmark) for `android:icon`. Rebuilt, `versionCode`
bumped 1→3, reinstalled — `aapt2 dump badging` confirms both resources
resolve correctly in the installed APK. **But Projectivy (the launcher)
still shows the old placeholder tile**, surviving a force-stop, a full
reinstall, and a `versionCode` bump — its icon cache is keyed on
something else entirely, or simply doesn't invalidate on package update.
The only known fix is `adb shell pm clear com.spocky.projengmenu`, which
would also reset Projectivy's custom categories/layout, not just its icon
cache — left alone per user decision (2026-09-20): the app-level fix is
correct and verified via `aapt2`, this is purely a stale-display issue in
Projectivy itself. Revisit if Projectivy's cache ever gets cleared for
another reason, or if a narrower "rescan/refresh apps" option is found in
its own settings.

R-Shop's own trampoline (`rshop-launcher-app/`) had the exact same
square-icon-as-banner issue. Rather than fix it, the trampoline was
removed entirely (2026-09-20): it existed purely for a home-row tile (no
special launch args, unlike this one), and the plain `R-Shop` icon works
identically otherwise, so a second launcher wasn't worth maintaining just
for that. R-Shop now launches from its own icon in Projectivy's app list
(not the home row, since R-Shop's own manifest lacks `LEANBACK_LAUNCHER`
— see bug (1) below). Revisit only if a home-row tile for R-Shop
specifically becomes worth building again.

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
5. **RetroArch baseline** — IN PROGRESS. Hit and resolved a real blocker
   first: the Fire TV remote's physical OK/Center button did nothing at
   all in RetroArch's menu. Root-caused to a genuine RetroArch 1.22.2
   regression (not a config mistake, not a "remote"-device-class
   limitation) — see "RetroArch OK-button fix" below for the full
   writeup. Fixed via a custom config + a small trampoline launcher app.
   Still remaining: apply
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
   Still remaining: install/cache/remove and the confirm-button gamepad
   gap (see below) are unverified with real button presses; the
   direct-launch handoff into RetroArch is untouched.
7. **Save sync** (Syncthing-Fork) — not yet started.
8. **Controllers** — pairing, hotkey mapping — not yet started. Also the
   answer to R-Shop's remaining open item (confirm/menu need real
   `gameButtonA`/`gameButtonStart`, which this remote can't send but any
   Bluetooth controller will) — deliberately deferred to here rather than
   patched, see "R-Shop bugs and workarounds" below.
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
