"""Host step on graph A's device outputs -> graph B input files, per config."""
import sys, os, glob
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rfdetr_host import host_step, NP_, NQ, NC, H
R, P = sys.argv[1], sys.argv[2]; configs = sys.argv[3:]
rp = np.fromfile(f"{P}/refpoint_embed.bin", np.float32).reshape(NQ, 4)
for c in configs:
    d = f"{R}/inputsB-{c}"; os.makedirs(d, exist_ok=True); lines = []
    for i in range(8):
        outs = {os.path.getsize(f) // 4: np.fromfile(f, np.float32) for f in glob.glob(f"{R}/pulledA/outA-{c}/{i}_o*.bin")}
        mem, refp = host_step(outs[NP_ * NC].reshape(NP_, NC), outs[NP_ * 4].reshape(NP_, 4), outs[NP_ * H].reshape(NP_, H), rp)
        mem.tofile(f"{d}/mem{i}.bin"); refp.tofile(f"{d}/ref{i}.bin")
        lines.append(f"/data/local/tmp/rfdetr/inputsB-{c}/mem{i}.bin,/data/local/tmp/rfdetr/inputsB-{c}/ref{i}.bin,/data/local/tmp/rfdetr/query_feat.bin")
    open(f"{d}/inputs.txt", "w").write("\n".join(lines) + "\n")
print("graph B inputs written for", configs)
