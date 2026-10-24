"""Split each prepared YOLOE ONNX at the head: backbone + neck (images ->
the feature maps the head consumes) for the Edge TPU, and the head (feature
maps -> boxes, score, cls, coef, protos) for the CPU/GPU. Checks that the two
halves chained reproduce the whole model exactly.  usage: <yoloe dir>"""
import sys
import numpy as np, onnx, onnx.utils, onnxruntime as ort
Y = sys.argv[1]
for v in ("yoloe-v8s-seg-pf", "yoloe-11s-seg-pf"):
    src = f"{Y}/{v}-reduced.onnx"; m = onnx.load(src); g = m.graph
    head_idx = max(int(n.name.split("/")[1].split(".")[1]) for n in g.node if n.name.startswith("/model."))
    pre = f"/model.{head_idx}/"
    head_nodes = [n for n in g.node if n.name.startswith(pre) or not n.name.startswith("/model.")]
    produced_in_head = {o for n in head_nodes for o in n.output}
    inits = {i.name for i in g.initializer}
    cut = sorted({i for n in head_nodes for i in n.input if i and i not in produced_in_head and i not in inits and i != "images"})
    onnx.utils.extract_model(src, f"{Y}/{v}-backbone.onnx", ["images"], cut)
    onnx.utils.extract_model(src, f"{Y}/{v}-head.onnx", cut, [o.name for o in g.output])
    b = ort.InferenceSession(f"{Y}/{v}-backbone.onnx"); h = ort.InferenceSession(f"{Y}/{v}-head.onnx"); full = ort.InferenceSession(src)
    x = np.load(f"{Y}/in0.npz")["images"]
    feats = dict(zip(cut, b.run(None, {"images": x})))
    o_h = h.run(None, feats); o_f = full.run(None, {"images": x})
    print(f"{v}: head = {pre} ({len([n for n in g.node if n.name.startswith(pre)])} nodes); cut tensors "
          f"{[(c.split('/')[-2] if '/' in c else c, list(f.shape)) for c, f in feats.items()]}; "
          f"chained vs whole max diff {max(float(np.abs(a.astype(np.float64) - c).max()) for a, c in zip(o_h, o_f)):.1e}", flush=True)
