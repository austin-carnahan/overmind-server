"""MI-GAN 512 Places2 toward the Edge TPU: the original fp32 generator
(extracted from the author-hosted migan.onnx, tensor 222 -> 1299; see
published-litert-eval) with its input fixed at [1,4,512,512] and simplified
(onnxsim folds the shape-computing ops around the upsamplers), then checked
against the original on the eight evaluation inputs (graph equivalence).
usage: migan_prep.py <generator_fp32.onnx> <eval dir (inputs/*.bin, reference.npy)> <out dir>"""
import sys
import numpy as np, onnx, onnxruntime as ort
from onnxsim import simplify
SRC, EV, OUT = sys.argv[1:4]
m = onnx.load(SRC)
inp = m.graph.input[0]
for d, v in zip(inp.type.tensor_type.shape.dim, (1, 4, 512, 512)):
    d.ClearField("dim_param"); d.dim_value = v
ms, ok = simplify(m)
assert ok
onnx.save(ms, f"{OUT}/migan_gen_fixed.onnx")
import collections
print("simplified ops:", dict(collections.Counter(n.op_type for n in ms.graph.node).most_common()))
a, b = ort.InferenceSession(SRC), ort.InferenceSession(f"{OUT}/migan_gen_fixed.onnx")
ref = np.load(f"{EV}/reference.npy"); worst = 0.0
for i in range(8):
    x = np.fromfile(f"{EV}/inputs/{i}.bin", np.float32).reshape(1, 4, 512, 512)
    ya = a.run(None, {a.get_inputs()[0].name: x})[0]; yb = b.run(None, {b.get_inputs()[0].name: x})[0]
    worst = max(worst, float(np.abs(ya - yb).max()))
    assert np.abs(ya[0] - ref[i]).max() < 1e-4
np.save(f"{OUT}/calib_nchw.npy", np.stack([np.fromfile(f"{EV}/inputs/{i}.bin", np.float32).reshape(4, 512, 512) for i in range(8)]))
print(f"fixed+simplified vs original on 8 inputs: max |diff| {worst:.1e} (outputs in [-1, 1])")
