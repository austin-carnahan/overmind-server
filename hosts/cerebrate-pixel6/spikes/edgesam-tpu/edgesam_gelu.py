"""GELU for the Edge TPU. PyTorch's exact GELU exports as
x * 0.5 * (1 + Erf(x / sqrt 2)); onnx2tf turns Erf into FlexErf (a
TensorFlow fallback op) and NNAPI has neither GELU nor ERF. Two rewrites of
every GELU in the prepared encoder:
- erfpoly: GELU(x) = 0.5 * (x + |x| * erf(|x| / sqrt 2)), with erf on
  non-negative arguments from Abramowitz & Stegun 7.1.26
  (1 - (a1 t + ... + a5 t^5) exp(-u^2), t = 1 / (1 + p u); |error| <= 1.5e-7):
  near-exact; ops ABS, MUL, ADD, DIV, EXP, SUB (ABS/DIV/EXP not yet probed
  on this TPU).
- tanh: x * sigmoid(x * (c1 + c3 x^2)), c1 = 1.5957691, c3 = 0.044715 c1 --
  exactly the tanh approximation of GELU (|error| up to ~5e-4); ops MUL,
  ADD, LOGISTIC, all proven on this TPU. Written as one dependency chain on
  purpose: as c1 x + c3 x^3, onnx2tf emitted x^2, x^3 and the cubic term
  before the linear one, and in that order the TPU compiler runs past its
  deadline on 128x128x192 (compile_probes.py: same ops, linear term first,
  0.66 s). A chain leaves no order to choose.
The exporter folds GELU's 0.5 into the next convolution where it can, so a
chain may end at x * (1 + Erf(x / sqrt 2)) (= 2 GELU); the rewrite keeps
whichever scale the chain had. - fit: the same chain with minimax-refitted coefficients (c1 = 1.6003142,
  c3 = 0.0694018; |error| <= 2.7e-4 over all x; an x^4 term constrained
  non-negative -- a negative one flips the sign for |x| > ~12, and
  activations here reach several hundred -- fits to 0).
Each is checked against the PyTorch original: embeddings (stage 1) and the
132 box-prompted masks (task level).
usage: edgesam_gelu.py <dl-edgesam dir> <out dir> [variant ...]"""
import sys
import numpy as np, onnx, onnxruntime as ort
from onnx import helper, numpy_helper, TensorProto
from edgesam_common import load_edgesam, decode, mask_stats, summarize
D, OUT = sys.argv[1:3]
SRC = f"{OUT}/edgesam_encoder_tpu.onnx"
CHAIN = {"tanh": (1.5957691216057308, 1.5957691216057308 * 0.044715), "fit": (1.6003141569619084, 0.069401786842701)}
AS = dict(p=0.3275911, a1=0.254829592, a2=-0.284496736, a3=1.421413741, a4=-1.453152027, a5=1.061405429)


def gelu_chains(g):
    """(x, [nodes], y, scale) for every Div(x, sqrt2) -> Erf -> Add 1 -> Mul x
    [-> Mul 0.5]: y = scale * x * (1 + erf(x / sqrt 2))."""
    prod = {o: n for n in g.node for o in n.output}
    vals = {i.name: numpy_helper.to_array(i) for i in g.initializer}
    vals.update({n.output[0]: numpy_helper.to_array(n.attribute[0].t) for n in g.node if n.op_type == "Constant"})
    cons = {}
    for n in g.node:
        for i in n.input: cons.setdefault(i, []).append(n)
    out = []
    for e in (n for n in g.node if n.op_type == "Erf"):
        d = prod[e.input[0]]; a = cons[e.output[0]][0]; m1 = cons[a.output[0]][0]
        assert (d.op_type, a.op_type, m1.op_type) == ("Div", "Add", "Mul"), e.name
        assert np.isclose(vals[d.input[1]], np.sqrt(2)) and np.isclose(vals[next(i for i in a.input if i != e.output[0])], 1), e.name
        x = d.input[0]; assert x in m1.input, e.name
        nxt = cons.get(m1.output[0], [])
        if len(nxt) == 1 and nxt[0].op_type == "Mul" and any(np.isclose(vals.get(i, np.nan), 0.5) for i in nxt[0].input):
            out.append((x, [d, e, a, m1, nxt[0]], nxt[0].output[0], 0.5))
        else:
            out.append((x, [d, e, a, m1], m1.output[0], 1.0))
    return out


def rewrite(variant):
    m = onnx.load(SRC); g = m.graph
    consts = {}
    def c(v):
        name = f"gelu_c{len(consts)}"
        if v not in consts:
            consts[v] = name; g.initializer.append(numpy_helper.from_array(np.array(v, np.float32), name))
        return consts[v]
    chains = gelu_chains(g)
    for k, (x, old, y, scale) in enumerate(chains):
        p = f"gelu{k}_"; nodes = []
        def op(t, ins, name):
            nodes.append(helper.make_node(t, ins, [p + name], name=p + name)); return p + name
        if variant == "erfpoly":
            ax = op("Abs", [x], "abs"); u = op("Mul", [ax, c(1 / np.sqrt(2))], "u")
            t = op("Div", [c(1.0), op("Add", [op("Mul", [u, c(AS["p"])], "pu"), c(1.0)], "den")], "t")
            h = c(AS["a5"])
            for j, a in enumerate((AS["a4"], AS["a3"], AS["a2"], AS["a1"])):
                h = op("Add", [op("Mul", [t, h], f"h{j}m"), c(a)], f"h{j}")
            poly = op("Mul", [t, h], "poly")
            ex = op("Exp", [op("Mul", [op("Mul", [u, u], "uu"), c(-1.0)], "nuu")], "exp")
            erf = op("Sub", [c(1.0), op("Mul", [poly, ex], "pe")], "erf")
            s = op("Add", [x, op("Mul", [ax, erf], "axe")], "s")
            nodes.append(helper.make_node("Mul", [s, c(scale)], [y], name=p + "out"))
        else:
            c1, c3 = CHAIN[variant]
            u = op("Add", [op("Mul", [op("Mul", [x, x], "x2"), c(c3)], "c3x2"), c(c1)], "u")
            sig = op("Sigmoid", [op("Mul", [x, u], "in")], "sig")
            if scale == 0.5:
                nodes.append(helper.make_node("Mul", [x, sig], [y], name=p + "out"))
            else:
                nodes.append(helper.make_node("Mul", [op("Mul", [x, sig], "xsig"), c(2 * scale)], [y], name=p + "out"))
        idx = list(g.node).index(old[0])
        for n in old: g.node.remove(n)
        for j, n in enumerate(nodes): g.node.insert(idx + j, n)
    onnx.checker.check_model(m)
    path = f"{OUT}/edgesam_encoder_tpu_{variant}.onnx"; onnx.save(m, path)
    return path, f"{len(chains)} ({sum(ch[3] == 1.0 for ch in chains)} with the 0.5 folded away)", sorted({n.op_type for n in g.node})


sam, pred = load_edgesam(D, "bicubic")
for variant in sys.argv[3:] or ("erfpoly", "tanh", "fit"):
    path, n, ops = rewrite(variant)
    s = ort.InferenceSession(path); worst = 0.0; acc = ([], [], [])
    for i in range(8):
        ref = np.load(f"{OUT}/ref{i}.npz")
        emb = s.run(None, {"image": np.load(f"{OUT}/in{i}.npz")["image"]})[0]
        worst = max(worst, float(np.abs(emb - ref["emb"]).max()))
        masks, _ = decode(pred, emb, ref["boxes"], tuple(ref["original_size"]), tuple(ref["input_size"]))
        refm = np.unpackbits(ref["masks"], axis=-1)[..., :ref["mask_shape"][-1]].astype(bool)
        iou, fl = mask_stats(masks, refm)
        for lst, v in zip(acc, (iou, fl, refm.sum((1, 2)))): lst.append(v)
    print(f"{variant}: {n} GELUs rewritten; ops {ops}")
    print(f"  stage 1: embeddings max |diff| vs PyTorch {worst:.1e}")
    summarize(f"  task level ({variant}, desktop fp32)", *acc)
