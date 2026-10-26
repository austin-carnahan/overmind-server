"""Published DINOv2 patch tokens [1024, 384] vs the original timm model:
numeric errors plus a task-level check (image similarity ranking from
mean-pooled patch features)."""
import sys
import numpy as np
D = sys.argv[1]; configs = sys.argv[2:]
ref = np.load(f"{D}/reference.npy").astype(np.float64); n = len(ref)
def sims(x):
    c = x.mean(1); c = c / np.linalg.norm(c, axis=1, keepdims=True); return c @ c.T
rs = sims(ref); rank = [list(np.argsort(-rs[i])[1:]) for i in range(n)]
print(f"{'config':18} {'img cos min':>11} {'tok cos min':>11} {'max abs':>8} {'rel L2':>8} {'NN':>5} {'rank':>5} {'sim maxdiff':>11}")
for c in configs:
    g = np.stack([np.fromfile(f"{D}/pulled/out-{c}/{i}_o0.bin", np.float32).reshape(1024, 384) for i in range(n)]).astype(np.float64)
    tok = (g * ref).sum(-1) / (np.linalg.norm(g, axis=-1) * np.linalg.norm(ref, axis=-1))
    img = min(float(g[i].ravel() @ ref[i].ravel() / (np.linalg.norm(g[i]) * np.linalg.norm(ref[i]))) for i in range(n))
    s = sims(g)
    nn = sum(int(np.argsort(-s[i])[1] == rank[i][0]) for i in range(n)); rk = sum(int(list(np.argsort(-s[i])[1:]) == rank[i]) for i in range(n))
    print(f"{c:18} {img:11.6f} {tok.min():11.6f} {np.abs(g - ref).max():8.3g} {np.linalg.norm(g - ref) / np.linalg.norm(ref):8.3g} {nn:>3}/{n} {rk:>3}/{n} {np.abs(s - rs).max():11.3g}")
