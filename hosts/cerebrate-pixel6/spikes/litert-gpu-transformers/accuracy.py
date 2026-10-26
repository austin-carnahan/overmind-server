"""Device outputs vs the unmodified PyTorch DINOv2 reference: numeric errors
plus a task-level check (CLS-embedding similarity ranking across images)."""
import sys
import numpy as np
D = sys.argv[1]
ref = np.load(f"{D}/reference.npy").astype(np.float64)           # [8, 257, 384]
def cos(a, b): return float(a.ravel() @ b.ravel() / (np.linalg.norm(a) * np.linalg.norm(b)))
def cls_sims(x):
    c = x[:, 0, :]; c = c / np.linalg.norm(c, axis=1, keepdims=True)
    return c @ c.T
ref_s = cls_sims(ref); n = len(ref)
ref_rank = [list(np.argsort(-ref_s[i])[1:]) for i in range(n)]
print(f"{'config':15} {'cosine(min)':>11} {'tok-cos min':>11} {'max abs':>9} {'mean abs':>9} {'rel L2':>9} {'NN match':>9} {'rank match':>10} {'sim maxdiff':>11}")
for c in ("cpu-req", "gpu-req-fp32", "gpu-host-fp32", "gpu-req-fp16"):
    got = np.stack([np.fromfile(f"{D}/pulled/out-{c}/{i}.bin", np.float32).reshape(257, 384) for i in range(n)]).astype(np.float64)
    d = np.abs(got - ref)
    tok = (got * ref).sum(-1) / (np.linalg.norm(got, axis=-1) * np.linalg.norm(ref, axis=-1))
    rel = np.linalg.norm(got - ref) / np.linalg.norm(ref)
    s = cls_sims(got)
    nn = sum(int(np.argsort(-s[i])[1] == ref_rank[i][0]) for i in range(n))
    rank = sum(int(list(np.argsort(-s[i])[1:]) == ref_rank[i]) for i in range(n))
    print(f"{c:15} {min(cos(got[i], ref[i]) for i in range(n)):11.6f} {tok.min():11.6f} {d.max():9.3g} {d.mean():9.3g} {rel:9.3g} {nn:>6}/{n} {rank:>7}/{n} {np.abs(s - ref_s).max():11.3g}")
