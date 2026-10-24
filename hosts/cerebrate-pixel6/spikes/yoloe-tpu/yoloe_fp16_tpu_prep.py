"""YOLOE-v8s backbone for the Edge TPU at fp32 with fp16 relaxation, in
three growing fragments, with the G1 max-pool correction.
- Max-pool correction: the Edge TPU pads SAME max-pooling with zeros. Each
  MaxPool's input must be *proved* bounded below: a SiLU (Mul(t, Sigmoid(t)),
  global minimum -0.278464542761074) or a MaxPool over a proved input (a
  max-pool can't go below its input's minimum); anything else is refused.
  Then MaxPool(x) -> MaxPool(x + c) - c with c = 0.28 > 0.27847, so every
  value the TPU compares is positive and its zero padding never wins. Exact
  up to float rounding; checked against the unmodified ONNX.
- Fragments of the corrected backbone partition: F1 = model.7-9 (P4 40x40x256
  -> SPPF output 20x20x512), F2 = model.0-9 (image -> P3/P4/P5), F3 = the full
  backbone + neck partition (image -> the head's three inputs).
- onnx2tf float32 TFLite (NHWC) per fragment; device inputs (NHWC float32)
  and references from the *unmodified* fp32 ONNX for three photos.
usage: <yoloe dir> <out dir>"""
import sys, os, subprocess, json
import numpy as np, onnx, onnx.utils, onnxruntime as ort
from onnx import helper, TensorProto
Y, OUT = sys.argv[1], sys.argv[2]; v = "yoloe-v8s-seg-pf"; C = 0.28; SILU_MIN = -0.278464542761074
src = f"{Y}/{v}-backbone.onnx"; m = onnx.load(src); g = m.graph
prod = {o: n for n in g.node for o in n.output}
def bounded(t):
    p = prod.get(t)
    if p is None: return False
    if p.op_type == "MaxPool": return bounded(p.input[0])
    if p.op_type == "Mul" and len(p.input) == 2:
        for a, b in ((p.input[0], p.input[1]), (p.input[1], p.input[0])):
            s = prod.get(b)
            if s is not None and s.op_type == "Sigmoid" and s.input[0] == a: return True
    return False
proved = {n.name: bounded(n.input[0]) for n in g.node if n.op_type == "MaxPool"}   # prove all before rewriting
for name, ok in proved.items():
    if not ok: raise SystemExit(f"refusing: {name}'s input is not provably bounded below")
g.initializer.append(helper.make_tensor("mp_shift", TensorProto.FLOAT, [], [C]))
new = []; fixed = 0
for n in g.node:
    if n.op_type != "MaxPool":
        new.append(n); continue
    a, b = n.name + "_shift_in", n.name + "_shift_out"
    new.append(helper.make_node("Add", [n.input[0], "mp_shift"], [a], name=n.name + "_add"))
    out = n.output[0]; n.input[0] = a; n.output[0] = b; new.append(n)
    new.append(helper.make_node("Sub", [b, "mp_shift"], [out], name=n.name + "_sub")); fixed += 1
del g.node[:]; g.node.extend(new); onnx.checker.check_model(m)
fixed_path = f"{OUT}/{v}-backbone-mpfix.onnx"; onnx.save(m, fixed_path)
print(f"max-pool correction: {fixed} MaxPool nodes rewritten (inputs proved >= {SILU_MIN:.6f}; shift {C})")
ref_sess = ort.InferenceSession(src); fix_sess = ort.InferenceSession(fixed_path)
x0 = np.load(f"{Y}/in0.npz")["images"]
d = max(float(np.abs(a - b).max()) for a, b in zip(ref_sess.run(None, {"images": x0}), fix_sess.run(None, {"images": x0})))
print(f"corrected vs unmodified backbone (desktop fp32): max abs diff {d:.1e}")
P4, P5, P3 = "/model.6/cv2/act/Mul_output_0", "/model.9/cv2/act/Mul_output_0", "/model.4/cv2/act/Mul_output_0"
frags = {"F1": ([P4], [P5]), "F2": (["images"], [P3, P4, P5]), "F3": (["images"], [o.name for o in g.output])}
# references: the unmodified model's intermediate tensors
inter = onnx.load(src); have = {o.name for o in inter.graph.output}
for t in (P3, P4, P5):
    if t not in have: inter.graph.output.append(helper.make_tensor_value_info(t, TensorProto.FLOAT, None))
onnx.save(inter, f"{OUT}/inter.onnx"); IS = ort.InferenceSession(f"{OUT}/inter.onnx"); names = [o.name for o in IS.get_outputs()]
meta = {}
for f, (ins, outs) in frags.items():
    fd = f"{OUT}/{f}"; os.makedirs(fd, exist_ok=True)
    onnx.utils.extract_model(fixed_path, f"{fd}/{f}.onnx", ins, outs)
    r = subprocess.run(["onnx2tf", "-i", f"{fd}/{f}.onnx", "-o", fd, "-n"], cwd=fd, capture_output=True, text=True)
    tfl = f"{fd}/{f}_float32.tflite"
    if not os.path.exists(tfl): print(r.stdout[-2000:], r.stderr[-2000:]); raise SystemExit(f"{f}: onnx2tf failed")
    from ai_edge_litert.interpreter import Interpreter, OpResolverType
    it = Interpreter(model_path=tfl, experimental_op_resolver_type=OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES); it.allocate_tensors()
    nops = len(it._get_ops_details()); idt = it.get_input_details(); odt = it.get_output_details()
    lines = []
    for i in range(3):
        x = np.load(f"{Y}/in{i}.npz")["images"]; vals = dict(zip(names, IS.run(None, {"images": x})))
        inp = x if ins == ["images"] else vals[ins[0]]
        inp.transpose(0, 2, 3, 1).astype(np.float32).tofile(f"{fd}/in{i}.bin"); lines.append(f"/data/local/tmp/yoloe/fp16tpu/{f}/in{i}.bin")
        np.savez(f"{fd}/ref{i}.npz", **{t.split("/")[1]: vals[t].transpose(0, 2, 3, 1) for t in outs})
        it.set_tensor(idt[0]["index"], inp.transpose(0, 2, 3, 1).astype(np.float32)); it.invoke()
        if i == 0:
            got = {tuple(it.get_tensor(o["index"]).shape): it.get_tensor(o["index"]) for o in odt}
            worst = max(float(np.abs(got[tuple(vals[t].transpose(0, 2, 3, 1).shape)] - vals[t].transpose(0, 2, 3, 1)).max()) for t in outs)
    open(f"{fd}/inputs.txt", "w").write("\n".join(lines) + "\n")
    meta[f] = {"ops": nops, "MB": round(os.path.getsize(tfl) / 1e6, 1), "in": list(map(int, idt[0]["shape"])), "outs": [list(map(int, o["shape"])) for o in odt],
               "desktop_fp32_tflite_vs_unmodified_onnx_maxabs": worst}
    print(f, meta[f], flush=True)
json.dump(meta, open(f"{OUT}/meta.json", "w"), indent=1)
