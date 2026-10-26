"""Relative-depth outputs vs the original model. Each device map is aligned
to the reference by least-squares scale + shift (the model's output is
relative), then scored: AbsRel, delta<1.25, Spearman rank correlation, and
pairwise depth-order agreement on 200k random pixel pairs whose reference
depths differ by more than 1% of the image's range. Raw rel L2 (unaligned)
is reported too."""
import sys
import numpy as np
D = sys.argv[1]; configs = sys.argv[2:]
ref = np.load(f"{D}/reference.npy").astype(np.float64); n = len(ref)
rng = np.random.default_rng(0)
def rank(a):
    r = np.empty(a.size); r[np.argsort(a)] = np.arange(a.size); return r
print(f"{'config':20} {'raw relL2':>9} {'AbsRel max':>10} {'d<1.25 min':>10} {'Spearman min':>12} {'order agree min':>15}")
for c in configs:
    rels, absrel, d1, sp, order = [], [], [], [], []
    for i in range(n):
        g = np.fromfile(f"{D}/pulled/out-{c}/{i}_o0.bin", np.float32).astype(np.float64).reshape(ref[i].shape)
        r = ref[i]
        rels.append(np.linalg.norm(g - r) / np.linalg.norm(r))
        A = np.stack([g.ravel(), np.ones(g.size)], 1); a, b = np.linalg.lstsq(A, r.ravel(), rcond=None)[0]
        ga = a * g + b
        valid = r > 1e-3 * r.max()
        absrel.append(np.mean(np.abs(ga[valid] - r[valid]) / r[valid]))
        ratio = np.maximum(ga[valid] / r[valid], r[valid] / np.maximum(ga[valid], 1e-9)); d1.append(np.mean(ratio < 1.25))
        sp.append(np.corrcoef(rank(g.ravel()), rank(r.ravel()))[0, 1])
        i1, i2 = rng.integers(0, r.size, 200000), rng.integers(0, r.size, 200000)
        rv, gv = r.ravel(), g.ravel(); m = np.abs(rv[i1] - rv[i2]) > 0.01 * (rv.max() - rv.min())
        order.append(np.mean(np.sign(rv[i1][m] - rv[i2][m]) == np.sign(gv[i1][m] - gv[i2][m])))
    print(f"{c:20} {max(rels):9.3g} {max(absrel):10.4f} {min(d1):10.4f} {min(sp):12.6f} {min(order):15.5f}")
