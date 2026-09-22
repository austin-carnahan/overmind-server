# Fire TV Stick 4K Max Emulation Optimization Design

## Purpose

This document defines a safe, measurable progression for maximizing the CPU, GPU, and memory available to emulators on the Fire TV Stick 4K Max. It assumes the normal interface is replaced visually by Projectivy Launcher and that a launcher-selection or Home-button utility keeps Projectivy in front of Amazon's stock interface.

The goal is not to display the largest possible free-RAM number. Android intentionally uses spare RAM for cached processes and can reclaim that memory. The useful goals are:

- Reduce active background CPU work, wakeups, and service contention.
- Reduce nonessential resident memory before launching an emulator.
- Avoid low-memory kills, thermal throttling, and frame-pacing disruption.
- Preserve Bluetooth, input, networking, storage, audio, ADB access, and a working Home interface.
- Keep every persistent change reversible.

## Hardware Constraint

The Fire TV Stick 4K Max second generation, model `AFTKRT`, has a four-core Cortex-A55 CPU up to 2.0 GHz, a GE9215 GPU up to 850 MHz, 2 GB of LPDDR4 RAM, Fire OS 8, Android API level 30, and a 32-bit application ABI. These limits make N64 and Dreamcast emulation a resource-management problem, but they also set a ceiling: optimization can remove contention but cannot turn the stick into a substantially larger emulation device.

Confirm the actual device rather than assuming the generation:

```bash
adb shell getprop ro.product.model
adb shell getprop ro.product.device
adb shell getprop ro.build.version.release
adb shell getprop ro.build.version.sdk
adb shell getprop | sort > fire-tv-getprop.txt
```

If the device is the first-generation 4K Max or another model, retain the workflow but establish new baselines and expectations.

## Core Design Principle

Every optimization must demonstrate a benefit in the emulator workload. A change is retained only when it improves at least one of these without creating a regression:

- Emulator output FPS relative to the core-requested FPS.
- Low-percentile frame time or time below the acceptable speed threshold.
- Audio underrun or blocking behavior.
- Emulator proportional set size and available system memory under load.
- Background CPU consumption while the emulator is running.
- Frequency or severity of low-memory kills, crashes, and ANRs.
- Thermal stability during a repeatable soak test.
- Cold-launch and controller behavior.

A higher `MemFree` value by itself is not a sufficient result.

## Safety Model

### Protected Capabilities

Do not disable, uninstall, or restrict any package until its role is known. Protect packages and services responsible for:

- Android and Fire OS framework functions.
- System UI and settings.
- Package management and permissions.
- Bluetooth and controller input.
- Audio, display, Vulkan, and storage access.
- Network connectivity and ADB.
- The active Home interface and its fallback.
- Projectivy and the utility that routes Home to Projectivy.
- RetroArch, Flycast, file access, and ROM storage.

### Change Policy

- Inventory before changing anything.
- Use an allowlist of packages approved for intervention; do not use broad name matching.
- Change one layer at a time.
- Save the exact command and inverse command for every persistent change.
- Validate Home, Settings, Bluetooth, network, ADB, reboot, and emulator launch after each package-level change.
- Prefer `force-stop`, then reversible background restriction, then user-level disablement.
- Do not uninstall system packages or use root-dependent modifications in the initial design.
- Do not disable Amazon's stock launcher until an alternate Home activity survives reboot and ADB recovery has been proven.

## Baseline Inventory

Before optimizing, create a device snapshot:

```bash
adb devices -l
adb shell am get-current-user
adb shell pm list packages -3 -f > packages-third-party.txt
adb shell pm list packages -s -f > packages-system.txt
adb shell pm list packages -e > packages-enabled.txt
adb shell pm list packages -d > packages-disabled.txt
adb shell dumpsys meminfo > meminfo-system.txt
adb shell dumpsys cpuinfo > cpuinfo-system.txt
adb shell dumpsys activity processes > activity-processes.txt
adb shell dumpsys activity services > activity-services.txt
adb shell dumpsys window > window-state.txt
```

Also identify the current Home implementation and foreground activity. Exact output varies by Fire OS build, so the agent should record the commands that work on this device:

```bash
adb shell cmd package resolve-activity --brief \
  -a android.intent.action.MAIN \
  -c android.intent.category.HOME
adb shell dumpsys activity activities
```

Record the package names and memory footprint of:

- Projectivy Launcher.
- The Home-selection or launcher-management utility.
- Amazon's stock launcher.
- RetroArch and standalone Flycast.
- Browsers, media players, VPN clients, downloaders, file managers, and other sideloaded utilities.
- Any package maintaining a foreground service, accessibility service, overlay, VPN, or media session.

The agent must discover package names from the device. Package names in internet debloat lists are not authoritative for this Fire OS build.

## Measurement Protocol

Use the automated emulator validation design as the workload harness. Select at least:

- One known-good N64 game.
- One demanding N64 game.
- One known-good Dreamcast game.
- One demanding Dreamcast game.

For every optimization stage:

1. Reboot the Fire Stick.
2. Wait a fixed stabilization interval, initially 90 seconds.
3. Capture idle system memory, per-process memory, and CPU activity.
4. Launch the same emulator profile and game scenario.
5. Warm up for the same interval.
6. Collect RetroArch internal statistics, logs, system memory, CPU, and visual evidence.
7. Run the same scenario duration.
8. Repeat at least three times before attributing a small improvement to the change.
9. Run Home, Settings, Bluetooth, network, ADB, suspend/resume, and reboot checks.

Use Fire TV System X-Ray for CPU and memory context. Use RetroArch's internal statistics as the authority for core-requested FPS, output FPS, and audio underrun or blocking.

## Optimization Progression

### Stage 0 Establish the Untouched Baseline

Measure the current stack exactly as used:

- Amazon stock launcher present.
- Projectivy running through its current override mechanism.
- Home-selection utility active.
- Normal Projectivy appearance and wallpaper settings.
- Normal collection of installed applications.
- Normal Fire TV output resolution.

This stage establishes whether there is an actual resource problem and which processes remain active during emulation. Android may already reclaim cached launcher processes effectively after RetroArch or Flycast enters the foreground.

### Stage 1 Reduce Projectivy Presentation Cost

Projectivy itself can display animated or video wallpapers and load optional visual sources. For an emulation-focused profile:

- Use a static, local wallpaper or a flat background.
- Disable animated GIF and video wallpapers.
- Disable wallpaper plugins and network-fed backgrounds.
- Disable unused channels, recommendations, and decorative content.
- Reduce or disable interface animation where Projectivy exposes the setting.
- Avoid large custom artwork collections in the launcher view.
- Keep only the emulator, library manager, and a small set of utility shortcuts on the primary screen.

Measure Projectivy's idle proportional set size and CPU before and after. This should be treated as a low-risk cleanup, not assumed to produce a large emulation improvement.

### Stage 2 Eliminate Redundant Launcher Work

The current arrangement may include three active components: Amazon's launcher, Projectivy, and a Home-selection or accessibility utility. Determine whether all three remain resident after the emulator starts.

Test these configurations in order:

1. Current launcher stack.
2. Projectivy with its own launcher override, without a redundant selector if Projectivy can reliably handle Home on this build.
3. Projectivy as the resolved Home activity through the launcher-management method already in use.
4. Only after successful reboot and recovery testing, an advanced profile in which the stock launcher is disabled for the current user.

Do not assume that disabling the visible Amazon Home screen frees all Amazon background services. Do not assume that an accessibility-based override replaces the stock launcher process; measure both.

For every variation, test:

- Cold boot reaches a usable Home screen.
- Home from RetroArch and Flycast returns predictably.
- Settings remain reachable.
- Projectivy starts after update, restart, and wake.
- ADB reconnects without navigating the Home screen.
- The alternate launcher does not enter a relaunch loop.

If making Projectivy the true default Home activity is unreliable on the installed Fire OS build, keep the small launcher-management service. Reliability is worth more than reclaiming a few megabytes.

### Stage 3 Create an Emulation Session Preparation Script

Implement a host-side script on Overmind or the development laptop. It should use a reviewed package allowlist to force-stop nonessential third-party applications before launching an emulator.

Likely candidates include recently used browsers, streaming clients, file managers, download clients, stores, VPN clients not needed for gameplay, and other user-installed applications. Discover and approve the exact packages on the device.

Conceptual operation:

```bash
adb shell am force-stop APPROVED_PACKAGE_1
adb shell am force-stop APPROVED_PACKAGE_2
adb shell am force-stop APPROVED_PACKAGE_3
```

The script should then:

1. Verify the protected package list is still enabled.
2. Stop only approved nonessential packages.
3. Confirm no unwanted media playback or VPN foreground service remains active.
4. Capture a prelaunch memory and CPU snapshot.
5. Launch RetroArch or Flycast directly.
6. Capture the postlaunch snapshot and begin the game test.

`am force-stop` is preferred at this stage because it is temporary. The application can be launched normally later, and no persistent package state is changed.

Do not force-stop Projectivy or the Home-selection utility during the first implementation. Test their real cost before deciding whether stopping them during gameplay is safe or useful.

### Stage 4 Restrict Verified Background Offenders

If a third-party package repeatedly restarts or consumes CPU in the background, test a reversible Android background-operation restriction:

```bash
adb shell cmd appops set PACKAGE_NAME RUN_IN_BACKGROUND ignore
```

Rollback:

```bash
adb shell cmd appops set PACKAGE_NAME RUN_IN_BACKGROUND allow
```

Use this only for reviewed third-party applications that do not need notifications, media playback, synchronization, launcher integration, or a foreground service. Validate the command and resulting state on the installed Fire OS build.

Do not rely primarily on Android App Standby buckets. Android documents their resource restrictions as applying while a device is on battery power, whereas Fire TV is continuously powered. Fire OS may add its own behavior, but any benefit must be demonstrated experimentally.

### Stage 4A Amazon Service Attribution and Temporary Containment

Added 2026-09-22, before Stage 4 is generalized to any specific package.
Real Stage 0/3 measurement already found a genuine phenomenon worth
isolating properly rather than acting on immediately: launching RetroArch
(even a lightweight Genesis workload) correlated with several Amazon
system services growing or appearing that weren't resident at idle —
`com.amazon.firebat` roughly doubling (96MB to 179MB), `com.amazon.tv.ftvambient`
appearing at 120MB having been absent, plus `com.amazon.venezia`,
`com.amazon.hedwig`, and `com.amazon.aca` all appearing.

**This is confirmed correlation, not yet isolated causation.** Before
restricting any of these packages, establish whether they:

- Launch after any foreground-app transition, not specifically RetroArch.
- Launch specifically with RetroArch.
- Were scheduled to wake independently, coincidentally overlapping.
- Remain resident or settle back down on their own.
- Consume active CPU, or merely occupy reclaimable memory.
- Cause actual zRAM traffic, major faults, or emulator degradation, as
  opposed to just occupying a memory number that looks concerning but
  costs nothing in practice.

Active zRAM at idle is evidence of constrained memory, not necessarily a
performance problem. Repeated swap-in/swap-out activity while playing is
the stronger sign of actually harmful pressure — that's the signal this
stage is really hunting for, not the raw resident-memory numbers alone.

#### Attribution trials

Run three repeated trials, each starting from the same clean state after
reboot:

| Trial | Action | Purpose |
| --- | --- | --- |
| Control | Remain on Projectivy for five minutes | Measure ordinary delayed Amazon startup with no app launch at all |
| Generic app | Launch a lightweight non-emulator app | Determine whether *any* app launch triggers the burst, or if it's RetroArch-specific |
| RetroArch | Launch the same Genesis workload used in Stage 0/3 testing | Measure emulator-specific behavior against the other two trials |

Capture at fixed timestamps: idle (pre-trial baseline), immediately before
the trial's action, and 15, 30, 60, 120, and 300 seconds afterward.

Use PSS plus system-pressure measurements at each timestamp, not memory
alone:

```bash
adb -s "$DEV" shell dumpsys meminfo
adb -s "$DEV" shell dumpsys cpuinfo
adb -s "$DEV" shell cat /proc/meminfo
adb -s "$DEV" shell cat /proc/vmstat
adb -s "$DEV" shell dumpsys activity processes
```

Specifically track, per timestamp: `MemAvailable`, zRAM occupancy,
`pswpin`/`pswpout` (from `/proc/vmstat`), major page faults, per-process
PSS for the suspect packages, sustained CPU usage, and (RetroArch trial
only) RetroArch FPS and audio underruns.

#### Temporary containment test

Do not disable these packages yet — `am force-stop` only, matching Stage
3's temporary-only posture. After RetroArch is fully launched in its
trial, force-stop one suspect at a time and observe:

```bash
adb -s "$DEV" shell am force-stop PACKAGE_NAME
```

- Does it remain stopped, or does Fire OS immediately restart it?
- How much `MemAvailable` returns?
- Does zRAM activity decline?
- Does RetroArch performance (FPS, audio underrun) actually improve?
- Which Fire TV capability breaks, if any?

Suggested order, from safest/most-understood to least:

1. `com.amazon.tv.ftvambient`
2. `com.amazon.venezia`
3. `com.amazon.hedwig`
4. `com.amazon.aca`
5. `com.amazon.firebat`

Leave `firebat` last: its role is the least identified of the five, and
its unusually large growth could mean it's tightly integrated with
application lifecycle handling generally, not something narrowly
RetroArch-related. For `ftvambient` specifically, first test disabling or
extending the screensaver through normal Fire TV Settings rather than a
package intervention — that's the safer lever, and it may prevent the
service from starting at all without touching `am force-stop` at all.

#### Launcher finding, tested separately

Stage 2's Home-resolution finding (Amazon's stock launcher, not
Projectivy, is the actual resolved Home activity) means Projectivy is
currently an interception layer on top of the system's true launcher, not
a replacement for it. That plausibly leaves three things resident at
once: Amazon Home, Projectivy, and the Home-routing utility. This makes
Stage 2 more important than its original ordering implied — but it must
be tested independently from the Stage 4A Amazon-service-burst trials
above, in its own separate trial run, or a result can't be attributed to
either intervention specifically.

#### Sequencing

1. Attribute the Amazon service burst (the three trials above).
2. Test temporary post-launch force-stops, one suspect at a time.
3. Measure actual memory-pressure and emulator effects, not just whether
   a number went down.
4. Optimize the launcher stack (Stage 2) independently, in its own trial.
5. Promote only proven force-stops into the Stage 3 session-preparation
   script.
6. Consider persistent restrictions (Stage 5) only after multiple
   successful reboot-and-regression tests of the temporary version.

The most promising eventual workflow, pending this stage's real evidence:
launch RetroArch, wait for Amazon's launch-triggered services to settle,
force-stop a vetted subset, then begin the benchmark or actual game
session. That's substantially safer than permanent system-package
debloating, and it's exactly what Stage 3's session-preparation script is
already structured to become once these packages are vetted.

### Stage 5 Disable Optional Packages for the Current User

Only packages that remain active after force-stop or background restriction and that have a measured cost should advance to this stage.

Disable a reviewed package for the current Fire TV user:

```bash
USER_ID="$(adb shell am get-current-user | tr -d '\r')"
adb shell pm disable --user "$USER_ID" PACKAGE_NAME
```

Rollback:

```bash
adb shell pm enable --user "$USER_ID" PACKAGE_NAME
```

Before each disable operation, record:

- Package name and human-readable application.
- Whether it is a system or third-party package.
- Why it is considered optional.
- Observed CPU and memory cost.
- Dependencies and integrations.
- Exact rollback command.
- Validation result after reboot.

Start with optional user-installed applications, not Amazon system components. Package disablement should remain a short allowlist, not a copied debloat catalogue.

### Stage 6 Test Display Pipeline Simplification

Compare Fire TV output at 4K and 1080p60 using the same emulator workload. N64 and Dreamcast internal resolution is controlled by the emulator; sending the final Android display at 4K may create additional composition or scaling work without improving the emulated image enough to matter.

Test, rather than assume, whether an emulation-mode output profile benefits from:

- 1080p60 output instead of 4K.
- Standard dynamic range instead of forced HDR processing.
- Disabled interface overlays during the authoritative performance run.

Keep the lower-output profile only if it improves frame pacing, thermal behavior, or reliability. Do not confuse TV output resolution with the emulator's internal render resolution.

### Stage 7 Address Thermal Sustainability

Amazon documents that critically high temperature can trigger CPU throttling. A short benchmark can therefore overstate sustained emulator performance.

For the test environment:

- Use the supplied or equivalently capable power adapter rather than marginal TV USB power.
- Use the HDMI extension lead if it moves the stick away from a hot TV enclosure.
- Keep the stick exposed to room airflow.
- Do not place it inside an enclosed cabinet or against another heat-producing device.
- Compare the first five minutes with a 30- to 60-minute soak.

Consider passive heatsinking or active airflow only after the software stages identify a repeatable thermal decline. Any physical modification should be tested for HDMI, Wi-Fi, Bluetooth, and enclosure safety.

### Stage 8 Advanced Stock Launcher Disablement

This is an optional experiment, not the default recommendation. It is appropriate only if measurement shows that the stock launcher remains materially active during emulation and the Projectivy path has already survived repeated reboot and recovery tests.

Requirements before attempting it:

- The exact stock launcher package has been identified from the device.
- Projectivy resolves as a valid Home activity or the selected launcher manager has a proven recovery path.
- ADB reconnects automatically after reboot.
- The enable command has been tested on a harmless package.
- The package state snapshot is stored off-device.
- No one depends on Amazon Home, recommendations, profiles, or launcher-only settings.

If disabling the stock launcher saves little CPU or memory under emulator load, revert it. Avoiding an extra Home layer is aesthetically useful, but it is not automatically a meaningful performance optimization.

## Emulation Mode Profiles

### Daily Profile

- Projectivy with a static background.
- Existing reliable Home-routing mechanism.
- No persistent system-package changes.
- Temporary force-stop of approved third-party apps.
- Emulator launched directly by the session script.
- Normal streaming and Fire TV functionality restored simply by opening those apps or rebooting.

This should be the target profile unless measurements justify more aggressive changes.

### Lean Profile

- Projectivy visual reductions.
- Redundant launcher utility removed if Projectivy alone is reliable.
- Background operations restricted for measured third-party offenders.
- Optional user-installed packages disabled.
- 1080p60 output if it demonstrably helps.

### Experimental Profile

- Stock launcher disabled for the current user.
- Minimal persistent background package set.
- Dedicated rollback script and ADB recovery procedure.

This profile should be used for comparison before becoming a household default.

## Session Script Design

The host-side `emulation-mode` command should support:

```text
emulation-mode inspect
emulation-mode prepare
emulation-mode launch --system n64 --game GAME_ID
emulation-mode collect --run RUN_ID
emulation-mode restore
emulation-mode validate
```

### Inspect

- Confirm device identity and Fire OS build.
- Resolve the current user and Home activity.
- Inventory enabled and disabled packages.
- List active foreground services, accessibility services, media sessions, and VPNs.
- Capture memory and CPU baselines.

### Prepare

- Validate the protected-package allowlist.
- Force-stop only approved packages.
- Confirm controller, ROM storage, network, and emulator availability.
- Refuse to continue if the active Home or ADB recovery assumptions have changed.

### Launch

- Start the selected emulator and content directly.
- Apply the selected global profile and per-game override.
- Hand off to the automated emulator validation workflow.

### Collect

- Save emulator statistics, logs, process memory, system memory, CPU information, screenshots, and optional recordings.
- Record the optimization profile and package-state hash with the run.

### Restore

- Stop the emulator cleanly.
- Re-enable only temporary restrictions created by the session, if any.
- Return to Projectivy.
- Confirm normal Home, network, Bluetooth, audio, and streaming behavior.

### Validate

- Test Home and Back navigation.
- Open Settings.
- Confirm ADB access.
- Confirm controller reconnection.
- Verify Projectivy after reboot and wake.
- Report any disabled package not present in the approved state file.

## Result Schema

Each optimization experiment should record:

```yaml
device_model: AFTKRT
fire_os_build: discovered-at-runtime
profile: daily-v1
package_state_hash: sha256-placeholder
launcher:
  projectivy_enabled: true
  projectivy_override_mode: discovered-at-runtime
  selector_package: discovered-at-runtime
  stock_launcher_enabled: true
display:
  output_mode: 1080p60
idle:
  mem_available_kb: 0
  background_cpu_percent: 0
workload:
  game_id: n64.example-game.usa
  emulator_profile: n64-480p-baseline
  video_fps_median: 0
  video_fps_low_percentile: 0
  audio_underrun_percent: 0
  emulator_pss_kb: 0
  thermal_degradation_detected: false
validation:
  home: pass
  settings: pass
  bluetooth: pass
  network: pass
  adb_after_reboot: pass
decision: keep-or-revert
```

## Acceptance Criteria

The Daily Profile is complete when:

- The preparation script is allowlist-based and idempotent.
- No protected package is modified.
- Projectivy, Home, Settings, Bluetooth, networking, storage, audio, and ADB work after preparation and reboot.
- Emulator validation artifacts identify the active optimization profile.
- At least one N64 and one Dreamcast workload show no regression across three runs.
- Every persistent change has an automated or documented inverse.
- A normal reboot restores a usable household device.

An aggressive change is promoted only when it produces a repeatable workload benefit large enough to justify the added recovery risk.

## Recommended Initial Implementation

Begin with Stages 0 through 3:

1. Inventory the actual launcher stack and running processes.
2. Establish four repeatable emulator workloads.
3. Simplify Projectivy to a static, low-motion interface.
4. Build an allowlisted script that force-stops nonessential third-party apps and launches the emulator.
5. Measure whether the stock launcher and Home-selection utility remain materially active during gameplay.

Do not disable Amazon system packages in the first pass. The initial data will show whether package-level debloating is even worth the operational complexity.

## Primary References

- [Fire TV Streaming Media Player Specifications](https://developer.amazon.com/docs/device-specs/device-specifications-fire-tv-streaming-media-player.html)
- [Fire TV System X-Ray](https://developer.amazon.com/docs/fire-tv/system-xray.html)
- [Fire TV Developer Tools Menu](https://developer.amazon.com/docs/fire-tv/developer-tools.html)
- [Fire TV Multimedia Application Requirements](https://developer.amazon.com/docs/fire-tv/multimedia-app-requirements.html)
- [Android Debug Bridge](https://developer.android.com/tools/adb)
- [Android Background Work Restrictions](https://developer.android.com/develop/background-work/background-tasks/bg-work-restrictions)
- [Android App Standby Buckets](https://developer.android.com/topic/performance/appstandby)
- [Android Multi-User Package Controls](https://source.android.com/docs/devices/admin/multi-user-testing)
- [Projectivy Launcher Source Repository](https://github.com/spocky/miproja1)
