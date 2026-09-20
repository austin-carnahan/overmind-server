# Fire TV Stick 4K Max — Implementation Plan

**Device:** Amazon Fire TV Stick 4K Max, 2nd generation (AFTKRT)  
**OS:** Fire OS 8 / Android 11 base  
**Purpose:** Living-room + travel media and retro-gaming appliance  
**Provisioning host:** Mac laptop with Android `platform-tools` / ADB  
**Local game storage:** Existing 128 GB USB flash drive  
**Canonical services/data:** Overmind home server

## 1. Goal

Turn the stock Fire TV Stick 4K Max into a polished, reproducible thin client for:

- home media playback through Jellyfin;
- media discovery and requests through Seerr;
- ad-reduced/ad-free YouTube through SmartTube;
- ordinary web access through Silk;
- commercial streaming apps;
- retro-game browsing, local caching, and emulation;
- save synchronization;
- secure access to Overmind while traveling;
- future game streaming through Moonlight.

The Fire Stick should remain **replaceable and non-canonical**. Media, ROMs, saves, metadata, and automation belong on Overmind. The Fire Stick keeps only apps, configuration, and a local working/cache set of ROMs.

## 2. Guiding decisions

1. **Keep Fire OS intact.** Do not root the device and do not aggressively disable Amazon system packages.
2. **Projectivy is the visible home UI.**
3. **Home on Fire redirects Home/wake to Projectivy** while retaining Amazon Home as a recovery path.
4. **Jellyfin replaces Kodi.**
5. **Seerr is the discovery/request surface**; the Seerr server runs on Overmind, while the Fire Stick gets a TV-friendly client.
6. **SmartTube handles YouTube.** Silk remains the general-purpose browser and fallback web-app host.
7. **RetroArch remains the primary emulator/gameplay frontend.**
8. **R-Shop is the ROM library/cache manager**, not a second emulator frontend.
9. **The 128 GB USB drive is a disposable local ROM cache**, not the canonical library.
10. **Save data is synchronized separately from ROMs.**
11. **Detailed RetroArch tuning comes from the existing RetroArch configuration notes.** This implementation plan should not silently replace those settings with new guesses.
12. **Prefer reproducible ADB provisioning over one-off manual tweaks**, but leave logins/account authorization and normal Appstore installs as human-driven steps.

## 3. Important platform constraint

The Fire TV Stick 4K Max 2nd gen uses a 64-bit-capable Cortex-A55 CPU but exposes a **32-bit Android application ABI**. When choosing APKs with architecture-specific releases, use:

- `armeabi-v7a`, or
- a compatible `universal` APK.

Do **not** install ARM64-only (`arm64-v8a`) APKs.

## 4. Physical/provisioning topology

Do not treat the Fire Stick like a phone that must be connected to the laptop by USB for ADB.

Normal provisioning topology:

```text
Mac laptop
   │
   │ Wi-Fi / LAN
   │ ADB :5555
   ▼
Fire TV Stick 4K Max
   │
   ├── HDMI → TV/display
   ├── power
   └── USB/OTG → 128 GB ROM cache
```

ADB runs over the local network. The Fire Stick remains powered and connected to a display so prompts can be approved with the remote.

## 5. Target software stack

| Layer | Software | Install path | Role |
|---|---|---|---|
| Base OS | Fire OS 8 | Stock | Underlying platform |
| Launcher | Projectivy Launcher | Sideload / ADB | Primary visible home screen |
| Home redirect | Home on Fire | Sideload / ADB | Redirect Home/wake to Projectivy |
| Home media | Jellyfin for Android TV / Fire TV | Amazon Appstore | Watch media hosted by Overmind |
| Media discovery | Seerr TV client | Sideload / ADB | Browse/request media from Seerr |
| YouTube | SmartTube | Sideload / ADB | TV-native YouTube client |
| General web | Silk | Stock | Browser and fallback web UI |
| Streaming | Netflix, Prime Video, etc. | Normal Fire TV path | Commercial services |
| Retro gaming | RetroArch | Sideload / ADB | Primary emulator/gameplay frontend |
| ROM management | R-Shop | Project build / sideload | Browse/install/remove local cached ROMs |
| Higher-end emulation | Standalone Flycast where justified | Sideload / ADB | Dreamcast path if superior to RA core |
| Save sync | Syncthing-style Android client | Sideload / ADB | Sync saves with Overmind |
| Remote network | Tailscale | Amazon Appstore | Reach Overmind while traveling |
| Future streaming | Moonlight | Normal/sideload as appropriate | Stream games from future Overmind compute node |

## 6. Projectivy layout

Initial launcher organization:

```text
WATCH
├── Jellyfin
├── SmartTube
├── Netflix
├── Prime Video
└── other streaming apps

DISCOVER
└── Seerr

PLAY
├── R-Shop
├── RetroArch
└── Moonlight            [later]

WEB & UTILITIES
├── Silk
└── Tailscale
```

Keep this small. The goal is a console/appliance interface, not an Android app drawer with every installed package exposed.

---

# Implementation phases

## Phase 0 — Baseline Fire OS setup

### Human/manual steps

1. Complete normal Fire TV first-run setup.
2. Join the home Wi-Fi network.
3. Sign into the intended Amazon account.
4. Apply available Fire OS updates.
5. Configure display/audio/equipment control normally.
6. Confirm the Fire TV remote works normally.
7. Install ordinary Appstore applications:
   - Jellyfin;
   - Tailscale;
   - Netflix / Prime / other desired commercial services.
8. Confirm Silk is present and functional.

### Record before modification

From Fire OS:

- device IP address;
- Fire OS version;
- available internal storage;
- MAC address;
- 128 GB USB presence.

Do not begin launcher replacement or emulator configuration until the stock device is known-good.

## Phase 1 — Enable developer access and establish ADB

On Fire TV:

1. Open **Settings → My Fire TV / Device & Software → About**.
2. If Developer Options is hidden, select the device/build entry repeatedly until developer mode is enabled.
3. Enable **ADB Debugging**.
4. Allow installation from unknown sources for the mechanism being used, if Fire OS requests it.
5. Note the Fire TV IP address under **About → Network**.

On the Mac:

```bash
adb version
adb connect <FIRE_TV_IP>:5555
adb devices
```

Approve the debugging authorization prompt on the television.

Expected:

```text
<FIRE_TV_IP>:5555    device
```

### Capture a device baseline

```bash
adb shell getprop ro.product.model
adb shell getprop ro.product.cpu.abilist
adb shell getprop ro.build.version.release
adb shell getprop ro.build.version.sdk
adb shell pm list packages
adb shell df -h
adb shell ls -la /storage
adb shell sm list-volumes all
```

Save the results into the provisioning repository for future comparison.

### Security rule

ADB debugging should be enabled during provisioning and troubleshooting, but it does not need to remain exposed indefinitely. Once the device is stable, disable ADB debugging unless ongoing agent management requires it.

## Phase 2 — Inventory and prepare the 128 GB USB ROM cache

The USB drive is already provisioned for this Fire Stick. **Do not reformat it as the first step.**

Use ADB to discover the actual Fire OS mount path:

```bash
adb shell sm list-volumes all
adb shell df -h
adb shell ls -la /storage
adb shell cat /proc/mounts
```

Store the resolved mount path as a provisioning variable, for example:

```text
ROM_DRIVE=/storage/<actual-volume-id>
```

Do not hard-code a guessed UUID in scripts.

### Verify read/write access

Create and remove a harmless probe file:

```bash
adb shell "touch '$ROM_DRIVE/.overmind-write-test'"
adb shell "ls -l '$ROM_DRIVE/.overmind-write-test'"
adb shell "rm '$ROM_DRIVE/.overmind-write-test'"
```

### Desired storage layout

```text
<USB_ROOT>/
├── roms/
│   ├── nes/
│   ├── snes/
│   ├── genesis/
│   ├── psx/
│   ├── n64/
│   └── dreamcast/
├── bios/
├── staging/
├── saves/
└── metadata/
```

Notes:

- `roms/` is the installed/local playable cache.
- `staging/` is where R-Shop or manual transfers can land content before promotion.
- `bios/` contains only BIOS files required by configured emulators.
- `saves/` may be used as the local save-sync root if Android permissions and emulator behavior are reliable.
- `metadata/` is optional local cache data.
- The USB drive may contain other travel files, but the ROM hierarchy should remain predictable.

### Canonical-storage rule

Never treat the USB copy as authoritative.

```text
Overmind ROM library
      │
      ├── canonical files
      ├── validation / organization
      └── metadata
              │
              ▼
         R-Shop / sync
              │
              ▼
       Fire Stick USB cache
```

Deleting a game from the Fire Stick must mean **remove local cache**, not delete from Overmind.

## Phase 3 — Build the provisioning workspace on the Mac

Suggested repository layout:

```text
fire-tv/
├── README.md
├── manifest/
│   └── apps.yaml
├── apks/
│   └── .gitkeep
├── scripts/
│   ├── 00-discover.sh
│   ├── 10-install-apks.sh
│   ├── 20-launcher.sh
│   ├── 30-storage.sh
│   ├── 40-retroarch.sh
│   └── 90-verify.sh
├── config/
│   ├── projectivy/
│   └── retroarch/
└── state/
    └── .gitignore
```

### Manifest goals

For each sideloaded application, record:

- application name;
- upstream project;
- package name;
- version;
- download artifact name;
- architecture;
- checksum when upstream publishes one;
- installation source;
- whether update is manual, in-app, or Appstore-managed.

The provisioning agent should download only from official project sources.

## Phase 4 — Sideload the base appliance UI

### 4.1 Projectivy Launcher

Install the current compatible Projectivy APK:

```bash
adb install -r <projectivy.apk>
```

Verify the package exists and launch it once.

Configure Projectivy manually or through supported Android intents/settings where reliable.

Initial goals:

- minimal launcher layout;
- no unnecessary channels;
- categories matching the target UI;
- no attempt to uninstall Amazon Home.

### 4.2 Home on Fire

Install:

```bash
adb install -r home-on-fire.apk
```

Grant the one-time secure-settings permission used by Home on Fire on Fire OS builds where the Accessibility page is restricted:

```bash
adb shell pm grant \
  io.github.toolicious.homeonfire \
  android.permission.WRITE_SECURE_SETTINGS
```

Launch:

```bash
adb shell am start \
  -n io.github.toolicious.homeonfire/.MainActivity
```

On the TV:

1. Enable the Home on Fire accessibility service.
2. Select **Projectivy** as the target.
3. Enable launch on boot/wake if desired.
4. Test short-press Home.
5. Test the documented escape path back to Amazon Home.

### Recovery principle

Amazon Home stays installed and functional.

If Projectivy or Home on Fire breaks after an update, the failure mode should be:

> fall back to Amazon Home

—not a broken Fire TV.

Do not run aggressive debloat/launcher-removal scripts as part of the baseline build.

## Phase 5 — Media and discovery clients

### 5.1 Jellyfin

Install Jellyfin through the Amazon Appstore.

Configure it against the Overmind Jellyfin server once that service is available.

Preferred local endpoint:

```text
jellyfin.home.arpa
```

Use the current LAN address temporarily if local DNS is not yet configured.

Validate:

- sign-in;
- library browsing;
- direct playback;
- subtitles;
- audio/video format handling;
- resume state;
- remote-control navigation.

### 5.2 Seerr

Use a TV-focused Android/Fire TV client rather than launching the raw Seerr web UI in Silk.

Current preferred approach:

- sideload a Fire-TV-compatible **Seerr TV** client;
- point it at the Seerr service on Overmind;
- validate D-pad navigation and login;
- expose it as **Seerr** in Projectivy under `DISCOVER`.

Preferred local endpoint:

```text
seerr.home.arpa
```

Silk remains the fallback if the TV client stops working.

### 5.3 SmartTube

Install only from the official SmartTube project/release channel.

Because this Fire Stick exposes a 32-bit ABI, choose:

- `armeabi-v7a`, or
- `universal`.

Do not choose an ARM64-only APK.

Configure:

- account pairing if desired;
- SponsorBlock behavior;
- playback quality;
- preferred codec/quality behavior only after validating stability;
- remote shortcuts only if they improve the living-room experience.

Place SmartTube under `WATCH`.

### 5.4 Silk

Keep Silk stock.

Use it for:

- arbitrary web access;
- web-only local tools;
- emergency access to Seerr or other self-hosted UIs;
- services where installing another wrapper is not justified.

## Phase 6 — RetroArch and emulator layer

### 6.1 Install

Install a current **32-bit-compatible** RetroArch Android build.

```bash
adb install -r <retroarch-32bit-or-universal.apk>
```

Launch it once before pushing configuration so the application initializes its data directories.

### 6.2 Storage mapping

Point RetroArch content browsing/playlists at the discovered USB ROM root rather than internal Fire Stick storage.

Do not guess storage paths. Validate that RetroArch can:

1. browse the USB path;
2. load a small known-good ROM;
3. retain permission after reboot.

### 6.3 Configuration source of truth

Apply the existing RetroArch tuning/configuration note as the authoritative source.

Known baseline decisions already established include:

- Rewind **OFF**;
- Run-Ahead **OFF**;
- avoid heavy shaders;
- performance-first presentation;
- PS1: SwanStation-oriented setup;
- N64: ParaLLEl / Mupen64Plus-Next-oriented setup;
- N64 target roughly 480p where stable, 240p fallback;
- Dreamcast: standalone Flycast is acceptable/preferred when it materially outperforms the RetroArch path;
- Flycast: Vulkan + threaded rendering where validated;
- frame skip only when needed;
- RetroArch threaded video initially OFF;
- conservative audio latency around the previously selected baseline, raising it only for crackling.

**Do not reinterpret these bullets as a replacement for the detailed prior configuration.** The agent should import/reproduce the existing settings and then run validation games.

### 6.4 Core/emulator validation matrix

Use a small, known-good test set for:

- NES;
- SNES;
- Genesis/Mega Drive;
- PS1;
- N64;
- Dreamcast.

For each system record:

```text
ROM
emulator/core
renderer
resolution/internal scale
audio behavior
controller behavior
frame pacing
known issue
pass/fail
```

Avoid tuning dozens of games before the baseline configuration is proven.

## Phase 7 — R-Shop integration

R-Shop's job is:

1. browse the canonical Overmind ROM library;
2. display useful metadata/art;
3. show whether a title is already cached locally;
4. install a selected title to the Fire Stick USB cache;
5. remove local cached copies;
6. hand off the selected local game to RetroArch or the appropriate standalone emulator.

R-Shop is **not** responsible for emulation.

### Explicit integration task

The direct-launch handoff is a first-class implementation item:

```text
R-Shop selection
      │
      ▼
resolve local ROM path
      │
      ▼
choose emulator/core
      │
      ▼
Android intent / launch helper
      │
      ▼
RetroArch or standalone emulator
```

Acceptance criteria:

- selecting an installed title launches it without manual file browsing;
- non-installed titles offer install/cache first;
- uninstall removes only the local cached copy;
- unavailable Overmind connectivity does not break already-installed games.

## Phase 8 — Save synchronization

Use a Syncthing-style Android client to synchronize **save data**, not the ROM library.

Desired direction:

```text
Fire Stick saves
      ⇅
Overmind save store
```

Suggested server namespace:

```text
/saves/austin/
```

Sync:

- SRAM / battery saves;
- memory-card saves;
- optionally save states after compatibility testing.

Do **not** sync:

- ROM libraries;
- caches;
- emulator thumbnails;
- volatile application data.

### Validate carefully

Test:

1. create save on Fire Stick;
2. confirm it reaches Overmind;
3. reboot Fire Stick;
4. confirm save persists and reloads;
5. modify from another client only as a controlled test;
6. verify conflict behavior.

Avoid playing the same game simultaneously on two devices when both can write the same save.

## Phase 9 — Tailscale / travel behavior

Tailscale can be installed from the Amazon Appstore on supported pre-Vega Fire TV devices.

Use it to make Overmind services reachable while traveling.

Validate two modes:

### Home

```text
Fire Stick → home LAN → Overmind
```

Prefer direct local connectivity.

### Travel

```text
Fire Stick → hotel/friend Wi-Fi → Tailscale → Overmind
```

Test:

- Jellyfin;
- Seerr;
- ROM-management connectivity if desired;
- save synchronization.

Do not make Tailscale a requirement for ordinary home operation.

## Phase 10 — Controllers

Pair the intended Bluetooth gamepads.

Validate:

- reliable reconnect after sleep/reboot;
- player 1 / player 2 ordering;
- Fire remote still works alongside controllers;
- RetroArch menu hotkey;
- quit-game hotkey;
- save/load-state hotkeys if retained;
- no accidental Home/Back conflicts;
- controller profiles persist after reboot.

Controller setup should be captured in the RetroArch configuration/rebuild notes rather than relying on memory.

## Phase 11 — Projectivy final polish

After all apps work independently:

1. hide unnecessary apps/categories;
2. order the launcher:
   - Watch
   - Discover
   - Play
   - Web & Utilities;
3. expose only useful end-user surfaces;
4. verify Projectivy starts after reboot/wake;
5. verify Home redirects correctly;
6. verify Amazon Home recovery path still works;
7. ensure no setup/debug utilities dominate the living-room UI.

The result should feel like an appliance, not a developer device.

## Phase 12 — Agent automation

The coding agent should make the setup **repeatable and idempotent**.

Good automation targets:

- ADB discovery/status;
- device-property capture;
- APK download/version manifest;
- APK install/update using `adb install -r`;
- Home on Fire permission grant;
- USB-volume discovery;
- storage directory creation;
- RetroArch configuration deployment;
- ROM test-set deployment;
- package/version verification;
- post-reboot health checks.

Poor automation targets:

- Amazon account login;
- streaming-service passwords;
- Jellyfin/Seerr authentication where QR/manual login is easier;
- brittle coordinate-based remote-control UI automation;
- destructive Fire OS debloating.

### Suggested verification script

`90-verify.sh` should report at least:

```text
[ ] Fire TV reachable over ADB
[ ] expected Fire OS / model
[ ] 32-bit ABI confirmed
[ ] USB storage mounted and writable
[ ] Projectivy installed
[ ] Home on Fire installed
[ ] SmartTube installed
[ ] Seerr TV installed
[ ] RetroArch installed
[ ] R-Shop installed
[ ] save-sync client installed
[ ] Jellyfin present
[ ] Tailscale present
[ ] Projectivy launch test passes
[ ] RetroArch sees USB ROM path
```

The script should report failures rather than silently trying destructive remediation.

---

# Acceptance tests

The Fire Stick setup is complete when all of the following are true.

## Appliance/UI

- Boot/wake lands in Projectivy.
- Home normally returns to Projectivy.
- Amazon Home remains reachable as recovery.
- Watch / Discover / Play / Utilities layout is usable entirely with the remote.

## Media

- Jellyfin plays a known movie/show from Overmind.
- Seerr can browse and submit a request.
- SmartTube plays YouTube content with the intended blocking/preferences.
- Silk can reach an arbitrary local web service.

## Gaming

- USB drive survives reboot and remains accessible.
- R-Shop sees the canonical library when Overmind is reachable.
- R-Shop can cache and remove a game without altering the canonical copy.
- RetroArch launches locally cached ROMs.
- Representative NES/SNES/Genesis/PS1/N64 titles pass.
- Dreamcast path is validated separately.
- Controller reconnect and hotkeys work.
- Save synchronization survives a reboot.

## Travel

- Fire Stick joins an arbitrary Wi-Fi network.
- Tailscale can reach Overmind.
- Jellyfin works through the remote connection at a reasonable bitrate.
- Cached games remain playable with **no** Overmind connectivity.

## Recovery

- Disabling Home on Fire restores stock Amazon Home behavior.
- Removing Projectivy does not brick navigation.
- Removing the USB drive does not prevent the Fire Stick from booting.
- The provisioning repository is sufficient to reconstruct the customized setup.

---

# Deferred work

Do not block the initial build on:

- Moonlight/Sunshine game streaming;
- perfect R-Shop → RetroArch direct launch if a simple first-pass launcher is not ready;
- full automation of account logins;
- replacing Fire OS;
- exhaustive emulator tuning for every game;
- syncing the entire ROM library to the stick;
- aggressive Fire OS debloating.

The first goal is a stable, pleasant appliance with a reproducible baseline.

---

# Reference implementation notes

Current platform facts checked during preparation of this plan:

- Amazon documents Fire TV ADB connections over the device IP on port `5555`.
- Amazon lists the Fire TV Stick 4K Max 2nd gen as Fire OS 8 / Android 11 with a **32-bit ABI** and support for external storage.
- Jellyfin for Android TV is officially available for Fire TV through the Amazon Appstore.
- Tailscale officially supports compatible Fire TV devices and distributes through the Amazon Appstore.
- Home on Fire currently supports Fire OS 8 and documents the one-time `WRITE_SECURE_SETTINGS` ADB grant.
- SmartTube supports Android-based Fire TV devices from this generation and publishes 32-bit/universal builds.
- Seerr TV community clients exist specifically to provide D-pad-friendly Android TV / Fire TV access to a Seerr server.

Useful upstream references:

- Amazon Fire TV ADB/install docs: https://developer.amazon.com/docs/fire-tv/installing-and-running-your-app.html
- Amazon Fire TV device specs: https://developer.amazon.com/docs/device-specs/device-specifications-fire-tv-streaming-media-player.html
- Home on Fire: https://github.com/toolicious/home-on-fire
- Projectivy Launcher: https://github.com/fraee/Projectivy-Launcher
- SmartTube: https://github.com/yuliskov/SmartTube
- Seerr TV (Fire-TV-friendly wrapper): https://github.com/Vermino/seerr-tv
- SeerrTV (native TV-oriented alternative): https://github.com/devmesh-git/seerrtv
- Jellyfin clients: https://jellyfin.org/clients/
- Tailscale on Amazon Fire: https://tailscale.com/docs/install/amazon-fire
