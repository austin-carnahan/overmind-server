# Model field notes

How the Cerebrate models behave on real work, as opposed to how they
validated. Our recipes (which model for which step) are assumptions until
these notes say otherwise.

**How to use this file**
- Add an entry whenever a test or a real task shows something: what was tried,
  on what input, what happened. Include near-misses and things that went
  well.
- When there's a cheap chance, try a variation (another model, prompt,
  threshold or window) and record both results. Ideas wait in **Try next**.
- Inputs are referred to by name:
  - **hotel-room.jpg**: the design-studio smoke-test project's source.
  - **bedroom.jpg**: 4000×3000 phone photo,
    `~/DesignStudio/workspaces/spike-a/` on the Mac.

## Current recipes (procedures: the [`interior-scene-editing`](../.claude/skills/interior-scene-editing/SKILL.md) skill; call contracts: [`cerebrate-gimp.md`](../services/design-studio/buckminster/cerebrate-gimp.md))

| Step | Recipe today | Evidence |
| --- | --- | --- |
| Find objects, no prompt | RF-DETR (`fixed-class-segmentation`) | clean labels and masks on the hotel room. Only 80 classes: no "lamp" |
| Find a named object | OWLv2 boxes → EdgeSAM | "a wicker lamp" → the lamp exactly (0.67), bed and pillows right; EfficientSAM3 missed or mislabelled (below) |
| Precise mask from a box | EdgeSAM (`box-refinement`) for simple objects; for whole objects with parts, **SAM 2.1 (`@quality`, `candidates=true`), the candidate that covers the object** | bed: SAM 2.1 candidate 1 = bed + pillows 99.3% / 97.8% (below); EdgeSAM: the comforter and skirt, not the pillows |
| Remove an object | inpaint with the 512 window, grow 7 px | small objects only. Lamp: clean wall, but its base smear and cast shadow stay. A bed-sized hole fails (below) |
| Rebuild a large hole | surfaces copied along their own geometry + `seamless_blend` | the bed's footprint: convincing (below); the geometry is manual so far |
| Mask → GIMP | corner-traced polygons, eps 1 px | IoU 0.998 median, 0.990 min |

## Observations

### Detection and labels
- **2026-10-26, hotel-room.jpg (sample run).**
  - RF-DETR gave the cleanest results: suitcase 0.91, bottle 0.80, bed 0.78.
  - The YOLOE and SAM label descriptions read oddly.
- **2026-10-26, bedroom.jpg.** The wicker lamp was named wrong by every
  detector:
  - RF-DETR: "vase" (0.51).
  - YOLOE prompt-free: "ornament" (0.43). YOLOE's own "lamp" (0.63) was the
    ceiling fan's light.
  - YOLOE found 21 things to RF-DETR's 2, including scene labels ("living
    space" ×3, "home interior", "dressing room", "server room") whose masks
    are large regions, not objects.

  **Takeaway:** name layers from the request or what the agent sees, not from
  the label.
- **2026-10-26, bedroom.jpg.** OWLv2 was refused by the capacity rule. It
  needs 1,924 MB plus the 1,000 MB reserve, and the phone had 1,974 MB free.
  It worked earlier the same day, so it depends on the phone's load.

### Text-prompted segmentation (EfficientSAM3)
- **2026-10-26, bedroom.jpg, full 4000×3000.** It OOM-killed MLServer.
  - **The first guess was the masks.** The hook upsamples all kept masks to
    full resolution as float32. The MCP scaled photos over 2048 px down as a
    workaround.
  - **Measured later the same day:** most of it was the host-side **resize to
    1008 (+832 MB)**, plus about 140 MB per mask. OWLv2's preprocessing was
    worse still: +1.6 GB and 14.5 s at 12 MP.
  - **The fix is in the hooks:** about 240 MB for the whole EfficientSAM3
    hook, with bit-identical outputs. The MCP's scaling was removed. See
    `hosts/cerebrate-pixel6/mlserver/README.md`, "Phone photos".
- **2026-10-26, bedroom.jpg at full 12 MP, after the hook fix: the threshold
  experiment.**

  | Prompt | Default 0.5 | Threshold 0.3 |
  | --- | --- | --- |
  | "lamp" (presence 0.74) | nothing | 0.38 and 0.41, both the **ceiling fan** |
  | "pillow" (presence 0.92) | nothing | one pillow (0.45), plus **the whole bed** twice (0.45, 0.32) |
  | "wicker lamp" (presence 0.19) | nothing | nothing |

  Same photo, **OWLv2**: "a wicker lamp" 0.67 with exactly the lamp's box;
  "a bed" 0.58; two pillows at 0.40.

  **Conclusion:** lowering EfficientSAM3's threshold finds the wrong things.
  OWLv2 → EdgeSAM is the named-object recipe. Each EfficientSAM3 run took
  about 21 s for 3 prompts; OWLv2 took 14 s at 12 MP.
- **2026-10-26, bedroom.jpg at 2048, prompts "wicker lamp", "lamp", "table
  lamp", "vase".** No instances returned. The presence scores were 0.18,
  **0.73**, 0.19 and 0.11, so it believed a lamp was there but no instance
  cleared `score × presence > 0.5`. 13.3 s for 4 prompts.

### Box → mask (EdgeSAM, SAM 2.1)
- **2026-10-26, bedroom.jpg.** EdgeSAM on RF-DETR's boxes:
  - bed 0.89 and the lamp gave good outlines;
  - the bed's mask **clipped the far pillow** and left a small detached
    fragment, visible once cut out to a layer.

  4.5–4.9 s per call, at full resolution, with no memory trouble.

- **2026-10-26, bedroom.jpg, Buckminster's first run (EdgeSAM on RF-DETR's
  bed box, twice with identical results).** The bed mask covered the comforter
  and skirt but left out most of both pillows and a strip under the right
  edge. Cut out, the bed had holes and its pillows stayed behind as ghosts.
  The bed box *included* the pillows, so EdgeSAM chose one part.

  **Recipe gap:** check that a mask covers the whole object, and add its parts
  (pillow boxes, or `@quality`) when it doesn't.

- **2026-10-26, bedroom.jpg, Experiment 1: one model, better prompts.**
  Scored against the accepted bed (cutout plus recovered pixels, pillows
  separate): coverage, pinholes, and spill into the rug, the nightstand and
  elsewhere. Stage `09`.

  | Mask | Bed body | Pillows | Spill |
  | --- | --- | --- | --- |
  | EdgeSAM, Buckminster's box | 96.9% | 31.5% | none |
  | EdgeSAM, RF-DETR or YOLOE box | 96.9% | 68–70% | none |
  | **SAM 2.1, candidate 0** (highest predicted score, 0.96) | 94–97% | 13–56% | none |
  | **SAM 2.1, candidate 1** (0.94–0.95) | **99.0–99.7%** | **97–98%** | 33–300 px into the rug; 360–1,600 px of dark under-comforter shadow by the nightstand |
  | SAM 2.1, candidate 2 | about 53% | about 1% | |
  | Two-model union | 99.2% | 95.7% | none, but it needed a hand-added pocket |

  Candidate 0 is a sub-part (the bed without pillows), candidate 1 the whole
  bed, candidate 2 another part.
  - **Box choice matters less than candidate choice.** A padded box added
    spill. With holes filled it covered the hand-added pocket fully, but
    spilled 300 px into the rug.
  - **Cost:** 15.9 s for three boxes with candidates; no extra model run.
  - **Conclusion:** pick the candidate by coverage of the object, not by
    predicted score. Fill enclosed holes, subtract stationary neighbours,
    segment parts that need their own layers separately. The two-model union
    becomes the fallback.

- **2026-10-27, bedroom.jpg, the ceiling fan (SAM 2.1, one box, candidates).** Candidate 1 (score 0.88) was the
  whole fan: blades with their motion blur, motor, the light shades (with small holes in the bright glass, which
  can be ignored). The other candidates were the motor, or a fan with a smeared halo. The pull chains weren't
  included; draw them as thin polygons.

### Inpainting (MI-GAN)
- **2026-10-27, bedroom.jpg, E13 v3.**
  - **The ceiling fan** (grown 12 px, an 887×780 patch; blades, light shades, motor, chains): a clean ceiling
    with the fan's cast shadow kept. The chains had to be masked from the motor down; a first, shorter chain
    mask left a pale stroke and a bluish blob under the light cluster.
  - **The nightstand's ghost on a plain wall** (380×350): clean. A plane-shifted copy of the wall there showed as
    a darker rectangle, because the window light changes along the wall.
- **2026-10-26, completing a hidden part of an object** (the bed skirt behind
  the rug): it filled the gap with floor. MI-GAN removes objects; it doesn't
  complete them. Continue the object's own visible texture instead (see
  "Large holes").
- **2026-10-26, hotel-room.jpg (sample run).** Fine one object at a time.
  Needed the mask grown about 7 px, or the fill picks up the object's edge.
- **2026-10-26, bedroom.jpg, the lamp.**
  - **Whole photo** squashed to 512: a blurred ghost, 23 s, a 15 MB PNG.
  - **512 window** around the mask: a clean wall and continued shadow, 2.5 s
    warm or 18 s cold, an 18.5 KB patch.
  - **Residue:** a small smear where the lamp's base sat on the nightstand,
    and a faint vertical shadow streak. The grown mask doesn't cover the
    contact shadow.

- **2026-10-26, bedroom.jpg, two 28 px discs on the comforter (patch
  placement test).**
  - A full-photo inpaint took about 17 s. 15 s of that was the adapter growing
    the 12 MP mask (PIL MaxFilter), fixed with `cv2.dilate`.
  - Fills of small round regions on fabric look plausible at 512 window
    scale.

- **2026-10-26, bedroom.jpg, Buckminster's first run.**
  - **The bed's footprint (976×545 patch, mask 309k px).** It filled with an
    orange-tinted smear and dark blocks, the wood floor's colour pulled up
    into the wall and baseboard. The window was about 1950 px, so the model
    saw the hole 3.8× reduced. MI-GAN (512 px, small and medium holes) can't
    fill an object-sized hole of room structure.
  - **The lamp, grown about 11 px vs 7.** The same smear on the nightstand top
    and the same vertical streak. The streak is the lamp's **cast shadow** on
    the wall, which no object mask includes, so growing the mask doesn't
    help.

### Large holes: surface-aware reconstruction (GIMP geometry + OpenCV blend), no model

**2026-10-26, bedroom.jpg, the bed's footprint (stages in
`~/DesignStudio/workspaces/bedroom/footprint-experiment/`).** MI-GAN's fill
was a smear (stage 01). Rebuilding the hidden wall, baseboards and floor from
the room's own pixels worked. Mean difference from the prototype: 1.8 levels
(stage 07).

1. **Footprint.** The bed's mask, plus both pillows (OWLv2 → EdgeSAM),
   grown 22 px for the skirt's fringe, plus the bed's contact shadow (up to
   30 px further down, not under the rug). The blend's edge must land on
   clean surface, or it drags dark or light pixels in.
2. **Geometry from the photo.**
   - **Baseboards:** tracing each one's edges column by column (a midpoint
     brightness threshold) gave lines with 0.4–0.5 px residuals. The two
     baseboards' top edges met at x = 1691, the wall corner as seen.
   - **Vanishing points:** each baseboard's top and bottom edges give one.
     Together they give the floor's vanishing line, nearly horizontal.
3. **Walls and baseboards: copies shifted along each surface's own line**
   (a layer move).
   - **Sources matter:** pick ones clear of the floor vent, and not
     window-lit wall for low wall.
   - **Seams:** both baseboards run into the corner without one.
4. **Floor: a perspective-correct move on the floor plane,** one
   `gimp-item-transform-matrix` from the affine rectification.
   - **Board direction:** the boards run parallel to the back wall, and
     copying along them is blocked by the wall, rug, nightstand and stool.
   - **Two sources:** a search over moves that keep every source pixel on
     real, visible floor found that no single move works. Two pieces did:
     93.5% and 6.5%. The main piece covers the whole floor; the second is
     feathered on top. Masking the main piece to its own area left the
     original bed showing through the feather.
5. **Blend:** Poisson, `seamless_blend` (OpenCV), with the destination the
   original photo, not the composite.
   - **Uniform per-piece levels** made a green-yellow cast (stage 04),
     because light varies across each surface.
   - **GIMP's GEGL seamless clone** takes about 100 s, single-threaded, and
     can't run as a filter. A crash in it, from uninitialised GEGL, froze
     GIMP twice.
6. **Timing.** About 24 s of GIMP geometry (6 pieces) and a 12 s blend loop:
   publish ×2 (6.7 s), blend 3.5 s (2.1 s computing), import 1.7 s.

**Fixes on the experiment document (2026-10-26, stages 08a–08f).**
- **Rug.** The footprint's 22 px growth had covered an 11% strip of the rug.
  The rug became its own object in front (EdgeSAM rug mask, from OWLv2
  "a sheepskin rug"), and now matches the photo (mean difference 0.04). Any
  object that stays in place and overlaps the footprint has to be protected
  like this.
- **Pillows.** The bed cutout held only the pillows' edges, so after the move
  their holes showed the rebuilt wall. Each pillow is now its own layer in
  the Bed group, from its own EdgeSAM mask (0.98 / 0.95).
  - **Alignment needed no new tool.** The group's move is the cutout's
    position now minus its mask's bounding box. Shifted by it, the pillows
    are pixel-identical to the cutout where both have pixels.
- **Missing bed pixels: recover, don't generate.** Mask candidates against
  the gaps in the cutout:

  | Candidate | Result |
  | --- | --- |
  | SAM 2.1 (`@quality`, 0.96) alone | added 130 px |
  | EdgeSAM from the RF-DETR box (a different box) | most pillow interiors, the pinholes, part of the shadow band, and the skirt's fringe |
  | Their union, enclosed holes filled | 56% of the gaps |
  | Closing (20 px) | would have recovered all the gaps |

  The union left one 2,087 px shadow pocket, under the comforter's right end.
  It was added by hand after checking it's the bed's shadowed side.
  - **Total:** 9,586 real photo pixels.
  - **Closing rejected:** a broad closing wasn't needed.
- **Hidden skirt.** The skirt hidden behind the rug becomes visible once the
  bed moves: 3,766 px, the bed's convex outline inside the rug.
  - **MI-GAN filled it with floor:** an object-removal model completes the
    background, not the object. Its layer is kept, hidden.
  - **What worked:** continuing the visible skirt, a copy shifted 60 px along
    its own lower edge. The region is grown 5 px into the skirt's edge,
    because the bed and rug masks left a sliver between them.
  - **Lesson:** the reconstruction idea (copy along the surface's own
    geometry) applies to objects too.

**Limits:**
- A small light speck by the rug's left tip, probably skirt fringe left
  inside the rug margin.
- The recovered shadow pocket's right end is blocky, a straight edge from the
  correction.
- The continued skirt's lower edge follows the convex outline, so it's
  straighter than the real fringe.
- Anything truly hidden (an outlet behind the bed) can't come back.
- The geometry was done by hand, as an operator. It isn't automated or in
  Buckminster's recipe yet.

**2026-10-26, Experiment 2: protect what stays, then rebuild (prototype
`exp2/proto6.py`, then `bedroom-v1.xcf`).** The goal was "good enough, and
learn why", not a perfect plate. Lessons, in the order they bit:

- **Protection map first.**
  - **Three classes:**
    - known foreground: rug, nightstand and stool masks, protected;
    - structural surface;
    - an uncertain band, within 10 px of both.
  - **The footprint** is the bed and its parts, grown and with its contact
    shadow, minus protected. Its overlap with protected objects went from 11%
    of the rug to zero.
- **Sources exclude stationary objects' shadows too,** not just the objects:
  each protected mask smeared 50 px down. Without this, the floor search
  copied the nightstand's shadow into the corner (a dark dab).
- **The blend destination along a protected edge must be the surface, not the
  object.** In a 15 px band inside the protected object next to the
  footprint, the destination gets the main floor move's texture, and the
  result is clipped to the footprint. Otherwise Poisson pulls the floor
  toward the rug's white (a haze along its edge).
- **Bound the surface by everything the lines don't describe.** The
  baseboard lines know nothing about doorframes or a side wall. A secondary
  floor piece was copied from the right wall (a grey wedge at the rug tip),
  so valid sources are now cut at both doorframes.
- **Blend a secondary piece against its floor neighbours only.** A
  per-piece Poisson blend, with the surrounding composite as destination,
  read the still-unfilled original (the bed's white sheet) at its edge, and
  produced a white band along the baseboard. Fix: the destination is the
  neighbouring floor where there is one, and the piece's own pixels
  elsewhere. In GIMP, the simpler feather (Phase C) is used instead. It's
  fine once each piece's sources are valid.
- **Accepted, not chased:** a soft dark band along the footprint's bottom
  edge. The main floor source there is about 20 levels darker than the
  floor around it, and the global blend corrects only half of that at the
  bounding box's bottom row. A brighter source or a second move would fix
  it; it isn't worth a rule.

**`bedroom-v1.xcf`, built in GIMP from the photo with agent operations
(script `exp2/v1_build.py`; stages in
`~/DesignStudio/workspaces/bedroom/bedroom-v1/`).**
- **Layers:**
  - Rug: its own group, in front;
  - Bed: the SAM 2.1 body plus two pillow layers;
  - Room: "Behind the bed (rebuilt)", with Walls / Baseboard / Floor pieces
    and the blended layer, over "Room (original)";
  - the original photograph, hidden.
- **The blend destination** was a temporary group at the bottom: the photo,
  plus the band layer. It was removed after the import, and the canvas
  never changed.
- **Protected pixels unchanged:**
  - away from the footprint's edge, nothing outside it differs from GIMP's
    own decode of the photo;
  - 1,104 px differ, all within 2 px of the edge: the polygon selection's
    antialiasing, 209 of them on the rug and nightstand.
  - (PIL and GIMP decode the JPEG up to 3 levels apart on 286k px: compare
    against GIMP's layer, not PIL's decode.)
- **Timing:** 21 s for the surfaces (7 pieces), 13 s for the objects, 6 s for
  the destination. The blend loop took 16 s: publish ×2 (6.7 s), blend 7.8 s,
  import 1.7 s.
- **Uncertain band, new lesson:** along the rug's top edge, its mask keeps a
  thin grey sliver of the bed skirt. Hidden while the bed sits there, it
  will show once the bed moves (Experiment 3). Where a protected object
  meets a moving one, the protected mask's edge needs a trim, and the
  uncertain band is exactly where to look.

**2026-10-26, Experiment 3: moving objects (bedroom-v1; scripts `exp3_a/b/b2/c.py`;
stages 05–07).**
- **Seam between a protected object and a moving one.** The rug's mask held
  1,087 px of the bed skirt. They were dark (V < 140), while the fleece's
  core is V ≥ 164, so one threshold near the bed found them.
  - **Fix:** trim them from the rug (`gimp-drawable-edit-clear`), add the
    main floor move under them, and re-run the blend loop with the footprint
    extended by the trim (18.6 s).
  - **Check:** nothing outside the new footprint changed (0 px beyond the
    2 px edge).
- **Single move.** One `layer move` on the Bed group, 0.1 s. It carries the
  body, both pillows, two continued-skirt layers and the shadow.
- **Hidden parts of the moving object** are continued along the object's own
  edge (copy, shift, mask), as in the experiment document:
  - behind the rug: offset (−120, +24);
  - under the comforter's right end, where the nightstand sat in the photo:
    (−110, +33).
  - **Choose the offset by match, not coverage.** Full source coverage
    allowed many offsets. The first choice pulled comforter fabric into the
    recess. Ranking by the mean difference on the 5 px overlap with the real
    bed fixed it: 54 vs 71 levels.
- **Contact shadow: recovered from the photo, not painted.** On the floor
  around the bed (footprint − bed, floor surface only):
  1. photo ÷ clean plate, as a group with the clean plate in Divide mode
     over the photo copy, merged (`gimp-group-layer-merge`);
  2. `gimp-drawable-desaturate` (luminance);
  3. `gegl:gaussian-blur` (6 px);
  4. set to Multiply, at the bottom of the Bed group.

  It takes 8 s, all native GIMP operations. With the bed in place it
  reproduces the photo (mean difference −0.7, |diff| 7.4 from the blur).
  - **Luminance only.** Per-channel ratios gave a yellow cast, because the
    blend brightened the clean plate's blue more.
  - **The group must be pass-through.** `overmind-make-object-group` made a
    Normal group, which keeps a Multiply child from reaching the room; it
    was switched by hand.
  - **Limit:** the shadow is the one from the bed's old spot. It grounds the
    skirt, but carries a dark patch from the nightstand's shadow at the right
    end.
- **Multi-object move.** One `gimp_edit_batch` of four `layer move` steps
  (Bed, Rug, Nightstand, Lamp), each moved exactly (−120, +40), with one undo
  group.
  - **The lamp is its own object** (SAM 2.1 candidate 0, again coverage
    without spill). A supported object must be in the batch, or it stays
    behind.
  - **A stationary object can't move until its own footprint is rebuilt.**
    The nightstand, lamp and rug left copies of themselves behind (stage 07).
    The skill must tell movable objects (footprint rebuilt) from fixed ones.
    Seen in GIMP, it looks like "the originals weren't removed and the moved
    copies sit on top of them". That's right: an object group is a copy, and
    only the bed's original was replaced by rebuilt surfaces.
  - **Undo:** one Ctrl+Z in GIMP reverted all four moves (checked by the
    user).

**2026-10-26, Experiment 4: perspective-aware placement
(`overmind-place-on-floor`; script `exp4_place.py`; stages 08–10).** No model:
the floor horizon is the line through the two baseboard vanishing points
from the reconstruction. It runs from y = 900 at x = 0 to y = 1048 at
x = 4000, a 2° roll.
- **Results**, one bed (pristine floor anchor (1186, 2038)), three
  placements:

  | Placement | Scale | Floor anchor lands | Members off their scaled offsets |
  | --- | --- | --- | --- |
  | Original depth (photo spot) | 0.99 | exactly | ≤ 0.4 px |
  | Closer | 1.40 | within 0.5 px | ≤ 0.9 px |
  | Farther | 0.78 | exactly | ≤ 0.6 px |

  Farther, the mattress top comes out level with the nightstand top at the
  same depth: plausible. Closer, it reads as nearer, not just bigger.
- **The horizon's tilt is the weak part.** At the photo spot (a 300 px
  sideways move), the 2° horizon gives 0.99:
  - with 0.99: mean |diff| from the photo's bed 18.5;
  - unscaled: 1.2.

  The tilt comes from two vanishing points far outside the frame (x = −1212
  and 3875), so small line-fit errors swing it. Next refinement: fit it from
  more lines (window sills, floorboards), or check the camera roll against
  verticals. That's before a floor homography, which would inherit the same
  vanishing points.
- **Depth order has to follow placement.** The rug stayed in front of the
  bed placed nearer the camera. Placement now restacks the group among its
  sibling object groups by floor-anchor depth: in front of clearly farther
  ones, behind clearly nearer ones.
  - **Ties keep the existing order.** "Clearly" means more than 5%. Lowest
    points at about the same depth say little: at its photo spot the bed's
    corner is 1.5% nearer than the rug's front edge, yet the rug is in
    front.
- **Supported objects.** The lamp's anchor is its base on the nightstand,
  read as a far floor point. Its depth should be its support's: the
  relationships brainstorm ("supported by").
- **Plug-in details:**
  - the pristine copy lives in a hidden "Placement originals (hidden)"
    group;
  - GIMP renames copies ("#1"), so live members get their names back and the
    pristine members are suffixed "(pristine)";
  - a scaled group refuses photo-offset patches, since only an unscaled
    group maps by a translation;
  - a repeated placement gives identical pixels;
  - headless tests first, then installed.
- **Not covered:** the viewing angle. A uniformly scaled cutout keeps the
  side it showed in the photo, which is fine for moderate moves only.

### Depth (Depth Anything V2)
- **2026-10-26, hotel-room.jpg (sample run).** Very good. No issues seen.

### Not for photo work
- SmolLM2 gave absurd text on the hotel sample. Granite-Docling isn't needed
  for this lane (it's Doclet's).

### Mask → polygons (GIMP handoff)
- **2026-10-26, bedroom.jpg, 23 masks.**
  - Polygons through pixel *centres* lost half a pixel all round in GIMP.
    Polygons through pixel *corners* gave IoU 0.998 median, 0.990 min.
  - eps 1 px is about 4× smaller than RLE.
  - eps 2 and 4 px were smaller still, but the small masks lost fidelity:
    IoU down to 0.98 and 0.96.

### Agent workflow (Buckminster)
- **2026-10-26, first run** ("cut the bed out, move it 300 px left, remove
  the lamp").
  - **Followed the recipe:** hidden original, Room and Bed groups, grouped
    before moving, both patches placed with the context check and accepted,
    none forced.
  - **Fell back well:** text segmentation found nothing, and it switched to
    boxes then EdgeSAM.
  - **Judged its own result honestly:** it called the result a draft, not
    finished work.
  - **Friction:**
    - `file_fetch` refused the source path (its read policy covers only
      `~/DesignStudio/workspaces`);
    - `file_fetch` refused a 10.5 MB PNG preview (8 MB cap); a JPEG preview
      worked;
    - The "4 failed" are those two `file_fetch` refusals, each counted again
      for the code-mode block around it. The source refusal was
      `POLICY_DENIED: path does not match any allowReadPaths pattern`, on
      `…/workspaces/spike-a/bedroom.jpg`. Not needed: Cerebrate reads the
      store path.
    - How to inspect a run: `sudo python3 ~/buck-failures.py` on overmind
      reads a copy of `agents/buckminster/agent/openclaw-agent.sqlite`. The
      relevant tables are `transcript_events` and
      `trajectory_runtime_events`.

## Try next

Run these when a test touches the step anyway.

- **Remove with shadow:** growing the mask doesn't reach a cast shadow (11 px
  ≈ 7 px). Add the shadow's area to the mask, either as a box from the agent
  or by segmenting "shadow of the lamp", and compare.
- **Whole-object masks:** union the parts (bed + pillow boxes), or SAM 2.1
  `@quality`, vs. EdgeSAM's one-part answer.
- **Large holes:** answered for repetitive architecture by surface-aware
  reconstruction (above). LaMa stays on the research list for irregular
  textures; check its Fourier operations on the Pixel's GPU first.
- **Automate the footprint geometry:** baseboard tracing, vanishing points,
  floor-move search, as a tool or plug-in, once a second room confirms the
  procedure generalises.
- **Inpaint window:** a context factor of 3× instead of 2×, or a minimum of
  768 px, on small objects. Does more surrounding help or blur?
- **EfficientSAM3 threshold:** answered on 2026-10-26: 0.3 returns wrong
  objects (above). Revisit only with a stronger text-segmentation model.
- **Named objects:** OWLv2 → EdgeSAM vs. EfficientSAM3 vs. RF-DETR → EdgeSAM,
  on the same phrases, when the phone has the memory.
- **Box → mask quality:** answered on 2026-10-26 (Experiment 1). SAM 2.1's
  candidate 1 is the whole bed; pick candidates by coverage, not by score.
  Check on objects without parts whether candidate 0 is right for those, so
  the rule doesn't just favour bigger masks.
- **YOLOE scene labels:** filter out region-sized "scene" detections ("living
  space", "home interior") by area or label before an agent sees them?
- **Polygon tolerance:** eps relative to object size, e.g. 0.5 px under
  20k px², to tighten small objects.
