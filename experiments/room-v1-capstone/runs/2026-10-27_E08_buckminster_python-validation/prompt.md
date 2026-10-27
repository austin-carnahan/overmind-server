# Message to Buckminster (sent from the dashboard)

Validation run for the Room V1 capstone: redo E08's wall-art geometry with your own Python, then apply it in GIMP.
First read `runbooks/python.md`.

1. **Project folder:** create `/mnt/substrate/design-studio/projects/room-v1-capstone/e08-python-validation/` and
   keep your script, its inputs and its output there.

2. **Inputs** (write them to `inputs.json`):
   - **Document:** 4000×3000 px.
   - **The small window's trim on the back wall**, image corners in this order: top-left (2099, 935), top-right
     (2512, 895), bottom-right (2497, 1240), bottom-left (2099, 1232).
   - **Camera:** focal length 2393 px, principal point (2000, 1500).
   - **The print's placement**, in the trim's rectified units: v runs from 0 (top of the trim) to 1 (bottom); u is in
     the same units, so the trim is "ratio" wide.
     - u0 = 2.16, v0 = −0.04, width = 1.7;
     - the print's own aspect is 3927/2486 (width/height).

3. **Write and run a script** (with the environment's Python) that:
   1. finds the trim's two vanishing points (top/bottom edges, left/right edges);
   2. recovers its true width/height ratio by metric rectification (edge directions K⁻¹·v, the plane normal, the
      corners back-projected onto that plane);
   3. reports the angle between the two recovered edge directions as a check;
   4. rounds the ratio to 2 decimals;
   5. builds the homography from the rectified rectangle (0,0)…(ratio,1) to the four image corners;
   6. maps the print's corners (u0,v0), (u0+w,v0), (u0,v0+h), (u0+w,v0+h), with h = w ÷ the print's aspect;
   7. prints everything as JSON.

4. **Apply it in GIMP:**
   1. Open `/Users/dev/DesignStudio/workspaces/room-v1-capstone/runs/2026-10-27_E08_buckminster_python-validation/working.xcf`.
      It's a disposable copy; never open the reference bedroom document.
   2. Load `art-cutout.png` from the same folder as a layer at the top (`gimp-file-load-layer`, then
      `gimp-image-insert-layer`), and crop it to its content.
   3. Call `gimp-item-transform-perspective` with your corners: x0,y0 top-left; x1,y1 top-right; x2,y2
      bottom-left; x3,y3 bottom-right.
   4. Name the layer "Framed print (Buckminster, Python)".
   5. Save `working.xcf`, and export `result.jpg` (under 8 MB) into the same folder.

5. **Report:**
   - the script's path;
   - the measured ratio, the edge angle and the four corners;
   - the GIMP calls you made;
   - anything that got in the way.
