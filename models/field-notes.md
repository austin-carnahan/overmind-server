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

## Current recipes (Buckminster: [`cerebrate-gimp.md`](../services/design-studio/buckminster/cerebrate-gimp.md))

| Step | Recipe today | Evidence |
| --- | --- | --- |
| Find objects, no prompt | RF-DETR (`fixed-class-segmentation`) | clean labels and masks on the hotel room. Only 80 classes: no "lamp" |
| Find a named object | OWLv2 boxes → EdgeSAM | untested on real work; EfficientSAM3 missed the bedroom lamp (below) |
| Precise mask from a box | EdgeSAM (`box-refinement`) | lamp good. Bed: the comforter and skirt, **not the pillows** (twice) |
| Remove an object | inpaint with the 512 window, grow 7 px | small objects only. Lamp: clean wall, but its base smear and cast shadow stay. A bed-sized hole fails (below) |
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
- **2026-10-26, bedroom.jpg, full 4000×3000.** It OOM-killed MLServer: the
  hook upsamples all kept masks to full resolution as float32. The MCP now
  scales photos over 2048 px down first, and MLServer has survived since.
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

### Inpainting (MI-GAN)
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
- **Large holes** (a moved bed's footprint): a large-hole inpainter (e.g.
  LaMa) vs. MI-GAN; or several overlapping 512 windows; or leave the
  footprint to the user and say so.
- **Inpaint window:** a context factor of 3× instead of 2×, or a minimum of
  768 px, on small objects. Does more surrounding help or blur?
- **EfficientSAM3 threshold:** expose `threshold` (the hook supports it). Does
  0.3 recover the lamp, and at what false-positive cost?
- **Named objects:** OWLv2 → EdgeSAM vs. EfficientSAM3 vs. RF-DETR → EdgeSAM,
  on the same phrases, when the phone has the memory.
- **Box → mask quality:** SAM 2.1 (`box-refinement@quality`) vs. EdgeSAM on
  the bed with its pillows.
- **YOLOE scene labels:** filter out region-sized "scene" detections ("living
  space", "home interior") by area or label before an agent sees them?
- **Polygon tolerance:** eps relative to object size, e.g. 0.5 px under
  20k px², to tighten small objects.
