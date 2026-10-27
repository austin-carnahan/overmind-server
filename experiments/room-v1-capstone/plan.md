# Room Decorating V1 — Capstone Execution Plan

**Status:** Ready for Buckminster handoff · **Reference scene:** `bedroom-v1.xcf` · **Date:** 2026-10-26

> **Updated 2026-10-26 (pre-experiment skill pass):** Claude Code runs the capstone first, as an
> exploratory run that may evolve the shared skills; Buckminster then replays a representative subset
> with a frozen skill revision. Storage, run records and the comparison protocol: [README.md](README.md).
> Where this plan says "Buckminster", read "the agent running the experiment". Run folders hold metadata
> only; XCFs and images stay in DesignStudio storage (README, "Where things live").

## 1. Purpose and scope

Run a small, repeatable **13-experiment GIMP playground** to discover what Buckminster can already accomplish with GIMP, Cerebrate, existing recipes, and visual judgment **before** freezing a room-editing skill. Build a useful collection of example edits, observations, and failure cases—not a framework or a polished benchmark harness.

**Primary outcome:** demonstrate a believable decorating workflow: recolor surfaces; reshape, duplicate, and move existing objects; import outside furniture and patterns; preserve occlusion and editable groups; and attempt a modest camera-view shift. The final deliverable is an editable `.xcf`, clean and annotated images, and short experiment-linked notes.

**Working principles**

- **GIMP is the scene authority.** Its document, groups, masks, and transforms are the persistent editable representation. Do not add a second scene graph, model registry, or rendering engine.
- **Use existing tools first.** Try GIMP PDB / MCP primitives, `overmind-place-on-floor`, `overmind-import-artifact`, GIMP↔Cerebrate artifact URLs, segmentation, and blending before inventing helpers. Check actual tool signatures before using them; example names here are conceptual unless already deployed.
- **Agent judgment is allowed.** Source selection, perspective approximation, boundary cleanup, and visual quality are partly subjective. Record where judgment mattered.
- **Keep runs isolated.** Never overwrite the reference `bedroom-v1.xcf`; make a working copy for each experiment or explicitly named multi-test sequence. Retain pristine imported objects and original photo layers.
- **Small experiments, bounded effort.** One primary method, at most one or two meaningful alternatives if needed; avoid broad parameter sweeps, new model conversions, production restarts, and infrastructure additions.
- **Not every result must succeed.** A visible limitation with a good before/after and explanation is valuable evidence. E13 is explicitly a challenge, not a beta gate.

## 2. Preflight: collect a compact asset pack

Obtain real assets **before running the external-content tests**. Aim for **8–12 carefully selected images**, plus a small palette, rather than a large scrape. Keep original downloaded files unmodified; derivative cutouts live in run output folders.

| Asset type | Suggested initial set | Used by | Selection notes |
|---|---|---|---|
| Nightstands | 2 product/catalog images: one fairly symmetric, one asymmetric | E04–E07, E09–E12 | Three-quarter view; visible top and feet; preferably product dimensions; one compatible with the existing lamp |
| Chair / accent furniture | 2 images: clean product shot + furnished-room photograph | E10–E12 | Clear silhouette, feet visible; the room photo intentionally tests hard extraction |
| Window dressing | 1–2 curtains/shades or drapery photographs | E06, E08 | Prefer a straight-on or compatible oblique view; preserve fabric folds |
| Fabric / material | 2–3 distinct patterns or seamless textures (e.g., linen, botanical, stripe) | E03 | Enough resolution for plausible repeated pattern; note approximate motif scale |
| Wall art | 1 flat image of a frame/art print | E08 | Rectangular planar geometry, rights recorded |
| Paint colors | 3–4 named swatches: two sage greens, one mustard/ochre, one neutral control | E01, E02 | Record color source and RGB/HEX as **screen approximations**, not promises of physical paint appearance |

**Suggested starting sources (verify each individual asset and its rights):**

- Furniture and room photos: [Pexels](https://www.pexels.com/) or [Unsplash](https://unsplash.com/); product/catalog photographs are also useful *for an internal visual experiment*, but check the site's and rights-holder's usage terms before reuse or redistribution.
- Repeatable, openly licensed texture studies: [Poly Haven](https://polyhaven.com/textures) (CC0 textures); licensed fabric swatches or user-provided textile photographs can test more realistic patterns.
- Real paint references: [Clary Sage SW 6178](https://www.sherwin-williams.com/en-us/color/color-family/green-paint-colors/SW6178-clary-sage), [Evergreen Fog SW 9130](https://www.sherwin-williams.com/en-us/color/color-family/green-paint-colors/sw9130), and [Goldenrod SW 6677](https://www.sherwin-williams.com/en-us/color/color-family/yellow-paint-colors/SW6677-goldenrod). Add a neutral control chosen from the existing scene.

**Record for each asset:** stable `asset_id`, original local file, source page URL, creator/vendor, license/permission note, pixel size, optional physical dimensions, SHA-256, and which experiments use it. Never depend on an expiring hotlink during a run. For redistribution, use assets with appropriate rights or keep third-party originals out of the published package.

## 3. Minimal working directory and records

Suggested home inside the existing Overmind workspace (adapt to current repo conventions; do not reorganize the project):

```text
experiments/room-v1-capstone/
  plan.md                 # this document
  experiments.yaml        # stable experiment IDs, prompts, assets, success checks
  assets/
    manifest.yaml         # provenance + local paths
    files/                # downloaded originals, usually ignored by Git
  runs/
    2026-10-26_E01_wall-sage/
      run.yaml            # status, inputs, operations, outputs, observations
      notes.md            # concise human/agent field notes
      working.xcf         # disposable editable document
      before.png
      after-clean.png
      after-annotated.png
      optional/           # intermediate comparisons when genuinely useful
```

Version small Markdown/YAML metadata; Git-ignore large photographs, XCFs, generated PNGs, and temporary downloads unless the project already has an intentional binary-asset policy. Use stable **E01–E13** identifiers so later runs can be compared. A second attempt gets a new `run/` folder, not an overwrite. A run should preserve input asset versions, source XCF and tool/model choices; software commit IDs are useful if readily available.

**`experiments.yaml` example** (the table in §5 defines all 13 IDs; this shows the lean format):

```yaml
suite: room-v1-capstone
scene: bedroom-v1.xcf
experiments:
  - id: E01
    name: Wall recoloring
    prompt: "Repaint the back wall Clary Sage, preserving its lighting."
    assets: [paint_clary_sage]
    check: [clean_boundaries, preserved_texture, editable_result]
  - id: E11
    name: External furniture import
    prompt: "Bring the catalog chair into the room by the window."
    assets: [chair_catalog]
    check: [clean_cutout, plausible_scale, floor_contact, reusable_group]
```

**`assets/manifest.yaml` example:**

```yaml
assets:
  chair_catalog:
    file: files/chair-catalog.jpg
    source_page: "https://example.org/original-asset-page" # replace with real URL
    license_note: "verify and record usage rights"
    sha256: "TO_BE_COMPUTED"
    size_px: [1600, 2000]  # measured, not assumed
    physical_dimensions_cm: null
  paint_clary_sage:
    type: paint_color
    name: "Sherwin-Williams Clary Sage SW 6178"
    source_page: "https://www.sherwin-williams.com/en-us/color/color-family/green-paint-colors/SW6178-clary-sage"
    hex_approx: null        # set from a verified reference / sampled swatch
```

**`run.yaml` example:**

```yaml
experiment: E11
run_id: 2026-10-26_E11_chair-catalog
status: partial             # not_started | running | pass | partial | fail | blocked
scene_input: bedroom-v1.xcf
assets: [chair_catalog]
agent: Buckminster
methods: [segment_region, overmind-import-artifact, overmind-place-on-floor]
models: ["SAM 2.1"]        # actual variant used, if applicable
outputs:
  xcf: working.xcf
  clean: after-clean.png
  annotated: after-annotated.png
observations:
  worked: "Mask and placement were reusable."
  failed: "Lighting mismatch on the chair's left edge."
  follow_up: "Try existing GIMP exposure adjustment."
```

**`notes.md` format:** four short sections—**Attempt / Observed / What helped or failed / Reusable rule or open question**—plus optional image references. Include key settings/anchors/transforms when they actually affect repeatability. Don't transcribe the full tool log; metadata can store essential operations and model variants.

## 4. Live experiment overlay and exports

The agent should be enjoyable to watch in GIMP. During a run, display a small, legible **upper-left, canvas-anchored status panel**, with a title and one short changing activity line. The panel is **instrumentation, not room content**.

Example on-screen text:

```text
ROOM V1  /  E11 — External furniture import
Segmenting blue chair · Cerebrate / SAM 2.1
```

Other useful status messages:

```text
E01 — Wall recoloring     Applying sage paint · GIMP masked color layer
E04 — Simulated rotation  Mirroring cabinet half · GIMP transform
E11 — Furniture import    Placing chair at floor anchor · overmind-place-on-floor
E13 — Camera shift        Warping floor plane · GIMP perspective transform
E13 — Camera shift        Repairing newly exposed wall · Cerebrate seamless_blend
```

**Implementation preference (keep this tiny):**

1. **Try native GIMP text layers first:** create an `EXPERIMENT HUD (exclude from inference/export)` group at the top of the document, with a dark translucent backing and editable title/status text. Update on **meaningful phases**, not every microscopic operation. Test through the existing GIMP MCP/PDB before building a helper.
2. If updating native text proves awkward, add one small GIMP-side `set_experiment_status(title, action)` operation—or generate an annotated preview externally as fallback. **Do not build a separate dashboard, video service, or event bus.**
3. On each run, produce **both** `after-clean.png` (HUD hidden) and `after-annotated.png` (HUD shown). Keep the HUD above the scene but **exclude it** from all snapshots sent to Cerebrate, clean exports, masks, geometry measurements, and scene composites. Otherwise the title itself could be detected as image content.
4. A canvas-anchored panel stays in the image's upper-left; it is **not** a sticky viewport overlay when panning/zooming. Use fit-to-canvas while observing or recording. A true viewport HUD is unnecessary for this capstone.
5. The XCF should preserve the HUD as an independently toggleable group. Avoid injecting status text into the actual pixel layers or corrupting scene selection/mask state; if overlay updating disrupts painting, disable it and use annotated snapshots instead.

The final annotated screenshot should show the **experiment name plus the final action/result**, while the clean render is the actual design comparison. Use one concise line of descriptive activity, not a scrolling console.

## 5. The 13 experiments

All experiments use a copy of the bedroom document. Primary success is a **visually inspectable, editable result with a traceable procedure**, not an automatic numeric score. Unless noted, test with existing tools first; record the number of manual corrections and whether another attempt would be easier.

### Appearance

**E01 — Wall recoloring.** Change the back wall to muted sage (e.g., Clary Sage or Evergreen Fog), then try a darker or mustard/ochre alternative. Use the wall mask and non-destructive color/blend layers. **Inspect:** boundaries at window/baseboard/furniture, preserved paint texture and light/shadow gradients. **Capture:** two color variants and the chosen method.

**E02 — Furniture recoloring.** Change bed upholstery or pillows without changing their geometry. Try masked adjustment/blend layers before synthetic replacement. **Inspect:** folds, highlights, seams, and object edges; whether subsequent floor placement preserves edits. **Capture:** original vs recolored version and layer structure.

**E03 — Material / pattern replacement.** Replace the bedspread or pillow fabric with a patterned textile **while preserving folds, volume, highlights and shadows**. Test pattern scaling, masked overlay, perspective/displacement or luminance-based shading using existing GIMP facilities. One pattern is enough for the initial run. **Inspect:** whether print stretches believably over folds, seams and curved edges; whether highlights survive. A flat-looking texture is a useful failure.

### Geometry and viewpoint of objects

**E04 — Basic mirroring.** Mirror the existing nightstand to the opposite wall or duplicate it into a left/right pair. Use its pristine copy and group-level transform. **Inspect:** lighting asymmetry, perspective, lamp attachment, and depth stacking. Record when a flip is merely a plausible approximation.

**E05 — Simulated ~90° furniture rotation.** Choose a fairly symmetric nightstand, box-like ottoman, or cabinet. Try **(A) mirror + warp**, **(B) split an object/face, mirror a half, recombine**, and optionally **(C) rearrange planar front/side/top faces**. Attempt only modest manual reconstruction of newly exposed areas. **Inspect:** seams, fake geometry, perspective consistency, material continuity; compare methods. This is an exploratory approximation, **not actual 3D rotation**.

**E06 — Perspective warping of a planar object.** Shift the apparent viewpoint of a rectangular tabletop, cabinet face, curtain panel, or framed print using GIMP perspective/matrix transforms. **Inspect:** whether vanishing direction and image edges match the room. Distinguish plane warping from inventing a new side of a solid object.

### Composition

**E07 — Object duplication.** Duplicate the existing nightstand or lamp into another editable group, flip if useful, and place it on the opposite side of the bed. **Inspect:** pristine-copy reuse, object naming, independent future movement, occlusion and shadow. No resegmentation should be required once the source is clean.

**E08 — Wall-mounted decoration.** Import one rectangular art print and hang it on a wall, projecting its corners onto that wall's perspective. As an optional second quick variant, try mounting a new curtain/dressing in the window using its frame as a perspective guide. **Inspect:** apparent angle and size, crisp boundaries, believable wall contact/shadow or curtain hang. Keep the imported item independently editable.

**E09 — Object overlap / ordering.** Move rug, bed, nightstand or chair so their silhouettes cross. Try front/back swaps and one combined multi-group move through `gimp_edit_batch` if supported. **Inspect:** ordering, protected stationary pixels, reversible edits, group structure, whether depth-based restacking makes the right choice.

**E10 — Partial concealment.** Place a chair partly **behind** the nightstand; then bring it **in front**, without flattening either. Test a difficult edge (legs, lamp cord, armrest) where a simple whole-group order may be insufficient. **Inspect:** accurate masks, contact/occlusion boundary, whether sub-layer or local masks are needed rather than inventing a universal occlusion engine.

### External assets

**E11 — External furniture import (primary gate).** Import a clean catalog chair *or* replacement nightstand, segment/cut it out, keep pristine pixels, create a named editable group, establish a floor anchor and initial real-world scale (product dimensions or manual calibration), then use `overmind-place-on-floor`. **Inspect:** clean matte, coherent camera angle, believable size, depth ordering, lighting correction and contact shadow. **Critical follow-up:** move it again without having to re-extract it. For a nightstand replacement, see if the existing lamp can transfer to and remain attached to the new support.

**E12 — Difficult extraction from an ordinary room photo.** Import a chair/nightstand from a furnished interior, not a clean product background. Try one strong single-model segmentation prompt first, with candidate masks / positive-negative points if available; use another model or union only as fallback. **Inspect:** occluded legs, background fringe, cast shadows baked into the cutout, and whether the extracted object is credible in the bedroom. Record model variant and prompt, not just the final image.

### Challenge: camera viewpoint

**E13 — Modest camera shift / scene reprojection (not a beta gate).** Attempt a *nearby viewpoint* of the room—not just moving furniture within a static photograph. Keep the intended motion explicit (e.g., lateral camera shift / orbit around a point of interest); do not conflate it with a simple image rotation. The resulting scene is approximate and may expose unseen surfaces.

- **Tier 1:** ~10–15° — aim for one plausible altered view.
- **Tier 2:** ~20–30° — increase exposed/unseen geometry; inspect where it starts breaking.
- **Tier 3:** ~30–35° — stretch target; **optional ~45°** if the earlier tiers are instructive and stable.

Try in order: **(A) surface-first warp** of walls/floor/baseboards → **(B) reproject/reposition 2.5D object groups** using anchors and approximate depth → **(C) selective reconstruction/inpainting** only where genuinely new surfaces are exposed. Save a render at each tier, note which surface or object fails first, and stop early if the remaining work would amount to building a 3D renderer. **Inspect:** room coherence, visible faces, seams, occlusion, floor continuity, shadows. This is a deliberate “flex” experiment, with no expectation of perfect geometry or a new required skill.

## 6. Run sequence and decision rules

**Phase 0 — Prepare (once).** Confirm GIMP/bridge/Cerebrate readiness without production disruption; preserve a known-good source XCF and model/tool version notes. Gather the compact asset pack and fill the manifest. Make a scratch XCF, prove that the live title/status panel is visible, then demonstrate a clean export with it excluded. Verify that overlays cannot leak into inference snapshots.

**Phase 1 — Calibrate the recording format.** Do **E01 (wall)** and **E11 (clean furniture)** early, perhaps E04 (mirror) as a short third pilot. Confirm that a typical run produces `run.yaml`, short notes, a working XCF, and clean/annotated PNGs. Adjust the template once if obviously necessary, then keep it stable.

**Phase 2 — Exercise the playground.** Run the remaining appearance, geometry, composition and external-asset tests. Reuse clean extracted objects and downloaded assets where useful; keep the per-experiment run folders independent. Run **E13 last**, when the surface and object manipulations have had a workout.

**Each experiment:**

1. Copy the reference/baseline document and pin input asset IDs.
2. Mark `running`; display the experiment name and first activity line.
3. Make one credible attempt with existing tools. Let Buckminster inspect intermediate GIMP renders and adjust.
4. If necessary, try one alternate approach; record why the first failed. Do not silently substitute a new model or tool.
5. Save editable XCF, clean/annotated renders, status (`pass`, `partial`, `fail`, or `blocked`), and four short field-note sections.
6. Restore/close scratch state before the next run; keep reference document intact.

**Stop / escalate only when justified:** If a missing primitive makes multiple experiments painful, note it and propose the smallest helper rather than implementing a framework. Before any risky Pixel compilation, MLServer restart, disruptive GIMP restart, large download, or new outside service, request explicit approval. New GIMP pixel-processing code gets isolated/headless testing first. Preserve operation IDs and avoid duplicate effects on retry.

## 7. Evaluation and handoff

Use a small, human-readable outcome vocabulary:

- **Pass:** convincing for the intended approximation, editable, repeatable from documented tools.
- **Partial:** useful result but conspicuous visual defects, manual patching, or fragile steps.
- **Fail:** attempted approach visibly fails, with enough evidence to explain why.
- **Blocked:** external dependency or missing capability prevents a meaningful attempt.

For each run, record at most **three observations**: best technique, main failure, and next potential improvement. Track rough time or number of tool calls only when it's informative—do not optimize a leaderboard. Specific geometry measurements, parameters, and model candidates belong in notes when they explain a result.

**Capstone exit:** all 13 experiments have an attempted run or a clear `blocked` reason; E11's imported object remains reusable; key edits remain editable as native GIMP groups; labeled and clean render pairs exist; the README/plan links to results. E13 can fail spectacularly and still count as a completed experiment.

**Afterward:** create a one-page digest: techniques that worked unchanged, techniques requiring agent judgment, truly missing deterministic primitives, and limitations that belong in the future Buckminster skill. **Only then** consolidate the skill and take the same workflows to a second room.

---

**Useful external references:** [GIMP 3 text layers](https://docs.gimp.org/3.0/en/gimp-image-text-management.html) · [Pexels license](https://www.pexels.com/legal-pages/license/) · [Unsplash license](https://unsplash.com/license) · [Poly Haven CC0 license](https://polyhaven.com/license). Check individual asset terms and the current GIMP MCP tool contracts during execution.
