"""Export the original EdgeSAM-3x image encoder (bicubic, as trained) to ONNX
and prepare it for the Edge TPU: the one bicubic Resize (fuse_stage3, 32x32
-> 64x64) becomes the exact construction in bicubic_x2.py, with replicate
padding written as Slice + Concat (ONNX Pad's edge mode has no NNAPI
counterpart) with explicit indices (onnx2tf turned the open-ended slice
x[-1:INT64_MAX] into an empty one). Stage 1 (graph equivalence): both ONNX graphs vs the PyTorch
encoder on the eight photos' encoder inputs.
usage: edgesam_export.py <dl-edgesam dir> <out dir (with in*.npz, ref*.npz)>"""
import sys
import numpy as np, torch, onnx, onnxruntime as ort
from onnx import helper, numpy_helper, TensorProto
from edgesam_common import load_edgesam
from bicubic_x2 import phase_kernels_2d
D, OUT = sys.argv[1:3]
sam, _ = load_edgesam(D, "bicubic")
raw = f"{OUT}/edgesam_encoder_bicubic.onnx"
torch.onnx.export(sam.image_encoder, torch.zeros(1, 3, 1024, 1024), raw, opset_version=17,
                  input_names=["image"], output_names=["image_embeddings"], dynamo=False)

m = onnx.load(raw); g = m.graph
rs = [n for n in g.node if n.op_type == "Resize"]
assert len(rs) == 1, [n.name for n in rs]
rs = rs[0]
mode = next(a.s.decode() for a in rs.attribute if a.name == "mode")
assert mode == "cubic", mode
shapes = {v.name: [d.dim_value for d in v.type.tensor_type.shape.dim] for v in onnx.shape_inference.infer_shapes(m).graph.value_info}
_, C, H, Wd = shapes[rs.input[0]]
assert (C, H, Wd) == (256, 32, 32), shapes[rs.input[0]]
init = []
def const(name, arr, dt=TensorProto.INT64):
    init.append(numpy_helper.from_array(np.asarray(arr, dtype=np.int64 if dt == TensorProto.INT64 else np.float32), name)); return name
nodes = []; x = rs.input[0]
def sl(src, start, end, axis, name):
    nodes.append(helper.make_node("Slice", [src, const(f"{name}_s", [start]), const(f"{name}_e", [end]), const(f"{name}_a", [axis])], [name], name=name)); return name
for axis in (2, 3):          # replicate-pad 2 on each side, rows then columns
    size = H if axis == 2 else Wd
    lo = sl(x, 0, 1, axis, f"bicubic_lo{axis}"); hi = sl(x, size - 1, size, axis, f"bicubic_hi{axis}")
    out = f"bicubic_pad{axis}"
    nodes.append(helper.make_node("Concat", [lo, lo, x, hi, hi], [out], axis=axis, name=out)); x = out
phases = []
for k, ker in enumerate(phase_kernels_2d()):
    w = const(f"bicubic_w{k}", np.broadcast_to(ker, (C, 1, 5, 5)).astype(np.float32), TensorProto.FLOAT)
    o = f"bicubic_phase{k}"
    nodes.append(helper.make_node("Conv", [x, w], [o], group=C, kernel_shape=[5, 5], name=o)); phases.append(o)
nodes.append(helper.make_node("Concat", phases, ["bicubic_phases"], axis=1, name="bicubic_phases"))
nodes.append(helper.make_node("DepthToSpace", ["bicubic_phases"], [rs.output[0]], blocksize=2, mode="DCR", name="bicubic_d2s"))
idx = list(g.node).index(rs); g.node.remove(rs)
for k, n in enumerate(nodes): g.node.insert(idx + k, n)
g.initializer.extend(init)
onnx.checker.check_model(m)
prep = f"{OUT}/edgesam_encoder_tpu.onnx"; onnx.save(m, prep)

s_raw, s_prep = ort.InferenceSession(raw), ort.InferenceSession(prep)
worst = {"raw": 0.0, "prep": 0.0}
for i in range(8):
    x_in = np.load(f"{OUT}/in{i}.npz")["image"]; ref = np.load(f"{OUT}/ref{i}.npz")["emb"]
    for name, s in (("raw", s_raw), ("prep", s_prep)):
        worst[name] = max(worst[name], float(np.abs(s.run(None, {"image": x_in})[0] - ref).max()))
print(f"stage 1 (8 photos, max |diff| vs PyTorch, embeddings ~|1|): exported ONNX {worst['raw']:.1e}, "
      f"TPU-prepared ONNX {worst['prep']:.1e}")
print("prepared ops:", sorted({n.op_type for n in g.node}))
