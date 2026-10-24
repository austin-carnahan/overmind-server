"""Probe outputs (device, every model/mode run) vs the fp32 references:
relative L2 and worst-element error, int8 outputs dequantized.  usage: <probe dir>"""
import sys, json, glob, os
import numpy as np
P = sys.argv[1]; meta = json.load(open(f"{P}/meta.json"))
print(f"{'run':24} {'rel L2':>9} {'cosine':>9} {'max abs':>9}")
for d in sorted(glob.glob(f"{P}/out/out-*")):
    run = os.path.basename(d)[4:]; model, mode = run.rsplit("-", 1); m = meta.get(model)
    f = f"{d}/0_o0.bin"
    if not m or not os.path.exists(f): continue
    base = model.split("-")[0]; ref = np.load(f"{P}/{base}-ref.npy").ravel()
    if m["out"] == "int8":
        s, z = m["out_q"]; a = (np.fromfile(f, np.int8).astype(np.float32) - z) * s
    else:
        a = np.fromfile(f, np.float32)
    if a.size != ref.size: continue
    print(f"{run:24} {np.linalg.norm(a - ref) / np.linalg.norm(ref):9.2e} {a @ ref / (np.linalg.norm(a) * np.linalg.norm(ref)):9.6f} {np.abs(a - ref).max():9.3g}")
