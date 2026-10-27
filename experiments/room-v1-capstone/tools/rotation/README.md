# Simulated 90° rotation (E05) — reference implementation

Claude Code-side helpers (Python, NumPy; environment-dependent: not available to an MCP-only agent).

- `camera.py` — a single-view camera from two vanishing points of perpendicular floor directions (e.g. two
  walls' baselines) and the image centre: focal length, orientation, floor back-projection, heights. The
  bedroom's baseboard lines are built in; `configure()` re-derives it for another photo.
- `box.py` — an axis-aligned box on the floor rotated 90° about its vertical axis: for each face visible after
  rotation, the source face (or its opposite, mirrored, when the source face was hidden), the image quads and
  the homography (sign-normalised: GIMP clips points with w < 0).
- `rotate_lib.py` — builds the rotated object in GIMP through the MCP tools: per face duplicate → mask to the
  source quad → `gimp-item-transform-matrix` → clip to the target quad; the top; sprites (pillows, a lamp)
  re-anchored in 3D; a contact shadow from the rotated footprint.

A candidate primitive if this becomes routine: a GIMP procedure that warps a layer from a source quad to a
target quad (computing the homography itself), so an agent needs only corner coordinates.

- `scene.py` — the bedroom as five planes (floor, ceiling, three walls) with their image polygons.
- `render.py` — E13's 2.5D ray-caster: a new camera (orbit about a pivot) casts a ray per pixel into the planes,
  box furniture and upright billboards; colour from the original photo where that surface point was visible,
  a hole elsewhere; one RGBA layer per element for GIMP. `render.py <out> <theta> <A|B|C> <room texture> <photo.npy> <masks.npz> [step]`.
