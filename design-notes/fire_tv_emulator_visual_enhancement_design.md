# Fire TV Emulator Visual Enhancement Design

**Status:** PROPOSED — see [status legend](README.md#status-legend); design
complete, none of its phases implemented yet. Depends on the
[N64/Dreamcast validation harness](n64_dreamcast_emulator_settings_handoff.md)
(also not yet built) and the
[emulation optimization work](fire_tv_4k_max_emulation_optimization_design.md)
(Stage 3 built/validated, Stage 4A in progress) for its automated
performance-gate testing — visual profiles here are meaningless without a
working pass/fail harness underneath them.

## Purpose

This document defines how to extract the strongest reasonable visual presentation from classic console games on the Fire TV Stick 4K Max while preserving full-speed emulation and game correctness. It covers screen filling, aspect ratio, scaling, shaders, widescreen rendering, internal resolution, texture treatment, geometry correction, and per-game enhancement experiments.

It is a companion to:

- The automated N64 and Dreamcast emulator validation design.
- The Fire TV emulation optimization design.

The enhancement system should use those tools to test aggressive visual profiles automatically and retain only settings that pass performance and visual validation.

## Design Goals

- Fill a modern 16:9 television attractively without blindly distorting original artwork.
- Apply strong pixel-art or CRT presentation to low-resolution cartridge systems.
- Use genuine widescreen rendering, patches, or cheats where they work correctly.
- Raise internal rendering resolution on 3D systems as far as the Fire Stick can sustain.
- Apply geometry, texture, color, and filtering improvements selectively.
- Generate per-core defaults and per-game overrides from measured results.
- Preserve stable output FPS, frame pacing, audio, input latency, and game behavior.

## Screen Filling Policy

Most cartridge-era console games were designed for approximately 4:3 CRT presentation. Game Boy and Game Boy Advance systems use still narrower native ratios. Stretching these images to 16:9 fills the panel but deforms circles, characters, movement, and pixel art. Full-screen presentation should therefore use the following priority order.

### Level 1 Native Widescreen

Use a game's built-in 16:9 mode when available. Configure RetroArch or the standalone emulator to match the game's output so it is not compressed back into 4:3.

This is the preferred solution because the game itself chooses the wider camera and layout.

### Level 2 Widescreen Patch Core or Cheat

Use a known-compatible ROM patch, widescreen-capable core, emulator cheat, or geometry expansion option. These methods can render additional scene content rather than stretching the existing frame.

Validate each game for:

- Objects disappearing at the original 4:3 boundary.
- Pop-in or missing geometry in the expanded view.
- Menus, HUDs, FMV, and pre-rendered backgrounds stretching incorrectly.
- Off-screen scripting becoming visible.
- Incorrect culling, clipping, shadows, or reflections.
- Performance loss from drawing a wider scene.

### Level 3 Safe Crop and Zoom

For games with nonessential overscan or letterboxing, crop only the area that was not intended to be visible and scale the remaining image. A modest zoom can reduce side bars, but it must not remove HUD elements, text, or gameplay space.

This should be a per-game override, not a global 16:9 setting.

### Level 4 Full-Screen Border or Ambient Fill

When a game cannot be expanded honestly, keep its image at the correct ratio and fill the remaining television area with:

- A platform-specific border.
- A restrained game-specific bezel.
- A blurred or color-matched ambient extension.
- A border shader that integrates integer scaling and scanline or pixel treatment.

This achieves a deliberate full-TV composition without black placeholders or distorted gameplay. RetroArch border shaders are designed to occupy the full display while preserving the core image and can support integer overscale and pixel anti-aliasing.

### Level 5 Stretch Only as an Explicit Preference

Raw 16:9 stretch may remain available as a user-selectable profile, but it should never be the generated default. It is not a graphical enhancement; it is geometric distortion.

## Enhancement Layers

Apply enhancements in this order so failures can be isolated.

1. Correct core, renderer, region, and timing.
2. Correct overscan and aspect ratio.
3. Integer or sharp scaling.
4. Color, gamma, and display-characteristic correction.
5. Lightweight shader or border composition.
6. Genuine widescreen option, patch, or cheat.
7. Higher internal resolution for 3D rendering.
8. Geometry correction, anti-aliasing, texture filtering, and anisotropic filtering.
9. HD texture packs or replacement artwork.

Only change one layer at a time during a tuning experiment.

## Output Resolution Strategy

The Fire TV Stick can drive a 4K television, but rendering the final RetroArch shader chain at 4K may consume GPU headroom that would produce a better result elsewhere. The system should compare two output modes:

- 1080p60 for stronger shaders and stable high-resolution 3D rendering.
- 4K60 for light shader chains or direct pixel scaling when it remains full speed.

The emulator's internal resolution and the Fire TV's display-output resolution are separate. A PS1 game can render internally at 2x or 3x and still be presented through a 1080p Android display mode. The test harness should select the combination with the best measured output, not the largest numbers.

## Shared RetroArch Profiles

### Accurate CRT

Purpose: reproduce the blending, scanlines, and softer transitions expected from a CRT.

- Correct core-provided or CRT-corrected aspect ratio.
- Crop only genuine overscan.
- Integer scaling or integer overscale.
- Lightweight CRT shader initially.
- Optional modest curvature only if it does not obscure the border.
- Platform or game border to fill the remaining 16:9 area.

Begin with lightweight shader families designed for lower-power hardware. Treat complex multi-pass masks, bloom, halation, and CRT-Royale-class presets as experiments at 1080p before attempting them at 4K.

### Crisp Pixel

Purpose: produce clean modern pixel art without CRT simulation.

- Integer scaling where practical.
- Nearest-neighbor or sharp bilinear scaling.
- Pixel anti-aliasing only to handle noninteger remainder pixels.
- Correct platform palette or color correction.
- No texture blur.
- Border or ambient fill outside the original viewport.

### Smoothed Pixel Art

Purpose: create a deliberately remastered appearance.

- Test ScaleFX, xBR-family, SABR, or similar edge-aware upscaling presets available in the installed RetroArch shader package.
- Keep this separate from the accurate profile.
- Validate text, checkerboard patterns, transparency tricks, thin lines, and rapidly changing animation.
- Reject presets that invent unstable edges or shimmer in motion.

### Widescreen Enhanced

Purpose: use real expanded rendering where supported.

- Enable the game, patch, core, or emulator widescreen mechanism.
- Set frontend aspect ratio to the matching 16:9 output.
- Add higher internal resolution only after widescreen correctness passes.
- Use a per-game override.
- Fall back to the correct-ratio border profile on failure.

## Nintendo Entertainment System

### Recommended Baseline

- Primary enhancement core: Mesen when it remains full speed.
- Performance fallback: FCEUmm or Nestopia UE.
- Aspect: NTSC or 4:3 presentation, not raw 16:9 stretching.
- Crop per-game edge garbage using the core's horizontal and vertical overscan controls.
- Choose a deliberate palette such as PVM-style, original-hardware, NES Classic, or a validated custom palette.
- Default visual profiles: Accurate CRT and Crisp Pixel.
- Fill the television with a restrained NES border or ambient shader.

Mesen exposes filters, custom palettes, overscan controls, CPU overclock options, and HDNes-format HD packs. HD packs should be treated as game-specific assets with their own version and licensing record.

### Experiments

- Mesen versus FCEUmm performance with the same shader.
- Blargg composite, S-Video, and RGB filters versus an external RetroArch CRT shader.
- Lightweight CRT at 4K versus stronger CRT at 1080p.
- Per-game HD packs, beginning with one well-documented title.
- Low or medium emulated CPU overclock for games with original hardware slowdown; retain only when game logic remains correct.

The Mesen `16:9` aspect option stretches the image and should not be confused with real widescreen rendering.

## Super Nintendo Entertainment System

### Recommended Baseline

- Default core: current Snes9x.
- Crop overscan where it removes unused or glitch-prone edge rows.
- Use Accurate CRT or Crisp Pixel for the standard library.
- Preserve 4:3 gameplay inside a full-screen border composition.

### Enhanced Mode 7 and Widescreen

Use bsnes-hd beta as a per-game enhancement core for compatible titles. It can provide:

- HD Mode 7 rendering at higher scale.
- Perspective correction.
- Supersampling.
- Widescreen and ultrawide scene expansion.

The core can use widescreen while leaving HD Mode 7 at 1x, so geometry expansion and high-resolution rendering should be tested separately. On the Fire Stick, begin with widescreen plus 1x Mode 7, then raise Mode 7 scale one step at a time.

### Experiments

- Snes9x baseline against bsnes-hd beta at 1x.
- Widescreen correctness without HD scaling.
- HD Mode 7 at 2x, then higher only if the automated workload passes.
- Supersampling as a separate toggle.
- Game-specific widescreen patches or setting files.

Return incompatible games to Snes9x rather than weakening the global SNES profile.

## Sega Genesis Mega Drive and Sega CD

### Recommended Baseline

- Default core: Genesis Plus GX.
- Set RetroArch to Core Provided aspect ratio.
- Use the core's NTSC or PAL pixel-aspect behavior rather than arbitrary 16:9 stretching.
- Hide overscan borders unless a game requires them.
- Use Accurate CRT or Crisp Pixel with a Genesis-specific border.

### Widescreen Experiment

Genesis Plus GX Wide is referenced by the Libretro border-shader documentation as a widescreen-producing core. Treat it as an experimental alternate core whose Android availability, performance, accuracy, and save compatibility must be verified on the installed RetroArch build.

Test for sprite and tile behavior outside the original viewport. Many Genesis games were never designed to update or populate the expanded area correctly.

### Experiments

- Standard Genesis Plus GX versus the Wide variant for a curated game list.
- NTSC composite blending for games that use dithering as transparency or extra color.
- Crisp RGB presentation for games that do not depend on composite blending.
- Per-game borders derived from box-art color rather than large decorative bezels.

## Game Boy Game Boy Color and Game Boy Advance

These systems cannot fill 16:9 without severe crop or distortion. The default should preserve their native geometry and make the rest of the television intentional.

### Recommended Baseline

- Game Boy and Game Boy Color: SameBoy or Gambatte.
- Game Boy Advance: mGBA.
- Use integer scaling.
- Apply appropriate color correction.
- Test LCD-grid and mild ghosting shaders as optional authentic profiles.
- Use a handheld-frame, neutral border, or ambient color fill.

The GBA's approximately 3:2 viewport can be made larger than a 4:3 console image on a 16:9 screen, but it still requires side treatment unless stretched or cropped.

### Experiments

- Corrected versus vivid color profiles.
- LCD response or interframe blending for games that rely on flicker or transparency.
- Crisp integer scale versus an edge-aware upscale profile.
- Simple full-screen ambient fill generated from the game's current frame.

## Other 8-bit 16-bit and Arcade Systems

Apply the same classification rather than inventing one global setting:

- Home-console 4:3 systems: correct pixel aspect plus CRT or crisp profile and full-screen border.
- Handheld systems: native ratio plus handheld or ambient frame.
- Vertical arcade games: preserve the vertical playfield and use cabinet or neutral side treatment.
- Horizontal arcade games: use the machine's correct aspect, crop only actual overscan, and test shader cost per core.
- Games with native or engine-port widescreen support: use it directly.

Arcade games are especially sensitive to orientation, unusual refresh rates, and non-square pixels. Generate overrides from metadata and core output rather than forcing 4:3 or 16:9 globally.

## Sony PlayStation

PlayStation is the strongest target for modernized 3D rendering on this device, but 2D games and games with pre-rendered backgrounds should use different profiles.

### Default 3D Profile

- Core: SwanStation.
- Renderer: Vulkan where stable.
- Internal resolution: begin at 2x; test 3x and higher only through the automated ladder.
- Geometry correction: test PGXP-style geometry or vertex correction features exposed by the installed core.
- Texture correction or perspective-correct texturing: enable experimentally.
- Texture filtering: test per game; nearest or three-point-like treatment may preserve artwork better than aggressive bilinear smoothing.
- Widescreen hack: per-game only.
- Frontend aspect ratio: 16:9 only when the game or core hack is actually producing widescreen geometry.

### 2D and Pre-rendered Profile

- Keep native or modest internal resolution.
- Use correct aspect ratio.
- Prefer CRT, sharp scaling, or mild texture filtering.
- Do not expect internal-resolution increases to improve pre-rendered backgrounds or sprites.
- Avoid widescreen hacks that separate 3D characters from 4:3 background art.

### Experiments

- Native, 2x, and 3x internal resolution.
- Geometry correction on and off.
- Perspective texture correction on and off.
- Nearest, bilinear, and other available texture-filter modes.
- Widescreen hack with culling correction where available.
- 1080p versus 4K Fire TV output.

If SwanStation enhancement options or performance are insufficient for a specific title, compare Beetle PSX HW as an experimental alternate. Do not replace the established SwanStation default globally without measured evidence.

## Nintendo 64

N64 enhancements have a higher compatibility and performance cost than cartridge-era shaders or PS1 upscaling. Continue using the previously defined ParaLLEl and Mupen64Plus-Next comparison.

### Recommended Ladder

- Correct and full-speed core at approximately 480p.
- Raise Mupen64Plus-Next 4:3 resolution to 640x480 and then 960x720 when stable.
- Use a game's own widescreen setting first.
- Test `16:9 adjusted` or game-specific widescreen patches only as overrides.
- Keep framebuffer emulation enabled unless performance testing proves it is the blocker; disabling it removes effects and can affect aspect and resolution behavior.
- Compare accurate N64 three-point filtering with sharper texture modes.
- Test 2x MSAA only after resolution and widescreen are stable.
- Defer high-resolution texture packs until a title passes without them.

### Experiments

- ParaLLEl versus Mupen64Plus-Next at matched output quality.
- 640x480 versus 960x720.
- Native 16:9 game modes versus emulator-adjusted widescreen.
- Three-point, standard bilinear, and sharp filtering.
- 2x MSAA.
- One curated high-resolution texture pack on a known-good game.

Do not combine a new core, widescreen, higher resolution, MSAA, and a texture pack in one experiment.

## Sega Dreamcast

Dreamcast often supports 480p and some games have native or patchable widescreen behavior, but the Fire Stick may have less spare headroom than it does for PlayStation.

### Recommended Ladder

- Use the previously selected RetroArch Flycast or standalone Flycast path.
- Renderer: Vulkan.
- Begin at 640x480 internal resolution.
- Test 1280x960 as the primary enhanced resolution.
- Use native widescreen settings first.
- Test Flycast widescreen cheats per game.
- Test the PowerVR2 post-processing filter separately.
- Add texture filtering or anisotropic filtering only after the resolution target passes.
- Keep frame skip off unless the title already requires it under the performance design.

### Experiments

- RetroArch Flycast versus standalone Flycast at identical resolution.
- 640x480 versus 1280x960.
- Widescreen cheat correctness and performance.
- PowerVR2 post-processing filter.
- Texture filtering and anisotropic filtering where exposed.
- 1080p versus 4K Fire TV output.

Widescreen failures should fall back to a correct 4:3 image inside a Dreamcast or ambient border, not raw stretch.

## HD Texture Packs and Replacement Assets

Treat texture and artwork packs as versioned game modifications rather than ordinary emulator settings.

Each pack record should include:

- Game title, region, and ROM or disc hash.
- Emulator and core version.
- Pack name, source, version, and license.
- Installed size and runtime memory impact.
- Required renderer and settings.
- Screenshot comparison and known defects.
- Performance result on the Fire Stick.

Do not sync the entire canonical texture-pack library to the Fire Stick. Install only approved packs for locally available games.

## Automated Enhancement Experiment

Extend the existing per-game test manifest with an enhancement matrix:

```yaml
game_id: psx.example-game.usa
baseline_profile: psx-swanstation-2x-4x3
experiments:
  - id: resolution-3x
    change:
      internal_resolution: 3x
  - id: pgxp
    parent: resolution-3x
    change:
      geometry_correction: enabled
  - id: widescreen
    parent: pgxp
    change:
      widescreen_hack: enabled
      frontend_aspect: 16:9
```

For each experiment:

1. Start from a known passing parent profile.
2. Change one enhancement layer.
3. Run the same save-state or save-file fixture and input sequence.
4. Capture emulator statistics without screen recording.
5. Capture screenshots and a diagnostic clip in a second run.
6. Compare performance against the parent.
7. Run visual checks targeted to the changed feature.
8. Keep, reject, or send the result for manual review.

## Visual Comparison Tests

The evaluator should inspect:

- Correct aspect ratio and round geometry.
- HUD placement and text readability.
- Additional widescreen scene content versus stretched pixels.
- Pop-in, culling, clipping, and missing geometry.
- Sprite and tile garbage outside the original viewport.
- Shimmering or unstable edge-aware upscaling.
- Broken transparency or dithering.
- Texture seams and perspective warping.
- Pre-rendered background alignment.
- Overscan glitches and cropped gameplay information.
- Shader banding, moire, mask instability, and excessive darkness.
- Border alignment and absence of black gaps.

Store matched baseline and candidate screenshots at the same test checkpoint.

## Performance Gate

An enhancement passes only when:

- Actual output FPS remains close to core-requested FPS.
- Frame pacing does not regress beyond the selected policy threshold.
- Audio underrun and blocking do not become sustained.
- The emulator does not crash, hang, or trigger an ANR.
- The visual feature works in gameplay, menus, FMV, and representative effects.
- No severe geometry, texture, or aspect-ratio defect appears.
- Thermal soak does not reveal delayed performance loss.

If two profiles pass, prefer the visually stronger profile unless its margin is so small that normal background variation can break it.

## Profile Storage

Maintain three levels of configuration:

- Global RetroArch settings: renderer, synchronization, output behavior, and shared directories.
- Core overrides: the passing default visual profile for a platform.
- Game overrides: widescreen, resolution, shader, patch, texture pack, or compatibility exceptions.

Keep borders, shaders, patches, textures, and override files versioned with manifests. The generated compatibility report should show both performance status and visual-enhancement status.

## Recommended Initial Rollout

### Phase 1 Cartridge Baselines

- Build Accurate CRT and Crisp Pixel profiles at 1080p.
- Create one restrained 16:9 border composition for NES, SNES, Genesis, GB/GBC, and GBA.
- Validate Mesen, Snes9x, Genesis Plus GX, SameBoy or Gambatte, and mGBA.
- Compare the strongest lightweight shader that passes against a more demanding preset.

### Phase 2 Cartridge Widescreen Experiments

- Test bsnes-hd beta on a small Mode 7 and widescreen set.
- Verify whether Genesis Plus GX Wide is available and stable on the Fire Stick build.
- Test one Mesen HD pack.
- Keep all results per game.

### Phase 3 PlayStation Enhancement

- Establish SwanStation 2x as the reference.
- Test 3x resolution, geometry correction, texture correction, and widescreen independently.
- Split 3D and pre-rendered or 2D titles into separate profiles.

### Phase 4 N64 and Dreamcast

- Reuse the automated core-comparison fixtures.
- Add one enhancement at a time after the base game passes.
- Promote 720p-class N64 or 1280x960 Dreamcast profiles only where measured.

### Phase 5 Asset Packs

- Add curated HD packs only for high-priority games.
- Track provenance, version, storage, and runtime cost.
- Avoid making texture packs a dependency of the base library.

## Decisions to Resolve Experimentally

- Whether 1080p output with stronger shaders looks better than light shaders at 4K.
- The strongest CRT shader family the Fire Stick can sustain for each 2D core.
- Whether border shaders or static overlay artwork have the lower runtime cost.
- Whether bsnes-hd beta performs adequately on the installed 32-bit Android build.
- Whether Genesis Plus GX Wide is available and stable.
- The best SwanStation internal-resolution ceiling.
- Which PS1 geometry and widescreen options are exposed by the installed core version.
- The best N64 resolution, filter, and MSAA combination by core.
- Whether standalone Flycast provides better enhanced rendering than the RetroArch core.
- Which systems can use a shared shader profile without platform-specific artifacts.

## Primary References

- [RetroArch CRT Shaders](https://docs.libretro.com/shader/crt/)
- [RetroArch Border Shaders](https://docs.libretro.com/shader/border/)
- [RetroArch Scaling and Aspect Controls](https://docs.libretro.com/guides/xmb-menu-map/)
- [Mesen Core](https://docs.libretro.com/library/mesen/)
- [Snes9x Core](https://docs.libretro.com/library/snes9x/)
- [bsnes-hd beta Overview](https://www.libretro.com/index.php/bsnes-hd-beta-core-pushing-the-limits-of-the-snes-widescreen-and-ultrawide-support/)
- [Genesis Plus GX Core](https://docs.libretro.com/library/genesis_plus_gx/)
- [SameBoy Core](https://docs.libretro.com/library/sameboy/)
- [mGBA Core](https://docs.libretro.com/library/mgba/)
- [SwanStation Core](https://github.com/libretro/swanstation)
- [Beetle PSX HW Core Options](https://docs.libretro.com/library/beetle_psx_hw/)
- [Mupen64Plus-Next Core Options](https://docs.libretro.com/library/mupen64plus/)
- [Flycast Core Options](https://docs.libretro.com/library/flycast/)
