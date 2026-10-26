"""Fragment outputs from the device (NHWC float32, matched by shape) vs the
unmodified fp32 ONNX references: per output, worst-photo relative L2 and
cosine, max abs; plus the 2-pixel border vs interior split (max-pool check).
usage: <fragment dir> <mode>..."""
import sys, glob, os
import numpy as np
FD, modes = sys.argv[1], sys.argv[2:]
for mode in modes:
    rows = {}
    for i in range(3):
        ref = np.load(f"{FD}/ref{i}.npz"); refs = {ref[k].shape: (k, ref[k]) for k in ref.files}
        for f in sorted(glob.glob(f"{FD}/out-{mode}/{i}_o*.bin")):
            a = np.fromfile(f, np.float32)
            k, r = next((kv for shp, kv in refs.items() if np.prod(shp) == a.size))
            a = a.reshape(r.shape); rel = np.linalg.norm(a - r) / np.linalg.norm(r); cos = float(a.ravel() @ r.ravel() / (np.linalg.norm(a) * np.linalg.norm(r)))
            H, W = r.shape[1:3]; yy, xx = np.meshgrid(np.arange(H), np.arange(W), indexing="ij")
            border = (np.minimum(yy, H - 1 - yy) < 2) | (np.minimum(xx, W - 1 - xx) < 2)
            e = np.abs(a - r); prev = rows.get(k, (0, 1, 0, 0, 0))
            rows[k] = (max(prev[0], rel), min(prev[1], cos), max(prev[2], e.max()), max(prev[3], e[0][border].max()), max(prev[4], e[0][~border].max()))
    for k, (rel, cos, mx, mb, mi) in rows.items():
        print(f"{os.path.basename(FD)} {mode:6} {k:8} rel L2 {rel:.2e}  cosine {cos:.6f}  max abs {mx:.3g} (border {mb:.3g}, interior {mi:.3g})")
