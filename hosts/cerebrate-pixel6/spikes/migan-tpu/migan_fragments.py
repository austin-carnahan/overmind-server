"""Growing fragments of the MI-GAN generator for the guarded Edge TPU sequence
(as edgesam-tpu): each from the input to a stage boundary, onnx2tf to float32
TFLite (NHWC, static shape), checked on the desktop against the original's
tensor at the same point; device inputs (raw NHWC float32) and references.
F1 -> encoder.b512 (19 nodes), F2 -> the whole encoder (137), F3 -> the
synthesis b128 RGB output (292), F4 -> the generator output (348).
usage: migan_fragments.py <out dir (migan_gen_fixed.onnx)> <eval dir (inputs/*.bin)> <onnx2tf sample .npy> [fragment ...]"""
import sys, os, shutil, subprocess, json
import numpy as np, onnx, onnxruntime as ort
from onnx import helper, TensorProto
OUT, EV, SAMPLE = sys.argv[1:4]
SRC = f"{OUT}/migan_gen_fixed.onnx"
FRAGS = {"F1": ("260", [0, 1]), "F2": ("518", [0, 1]), "F3": ("1088", [0, 1]), "F4": ("1299", list(range(8)))}
if len(sys.argv) > 4:
    FRAGS = {k: v for k, v in FRAGS.items() if k in sys.argv[4:]}
inter = onnx.load(SRC)
for t, _ in FRAGS.values():
    if t not in {o.name for o in inter.graph.output}:
        inter.graph.output.append(helper.make_tensor_value_info(t, TensorProto.FLOAT, None))
onnx.save(inter, f"{OUT}/inter.onnx")
so = ort.SessionOptions(); so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL   # fusions would hide intermediate outputs (Conv+Add)
IS = ort.InferenceSession(f"{OUT}/inter.onnx", so); names = [o.name for o in IS.get_outputs()]
X = {i: np.fromfile(f"{EV}/inputs/{i}.bin", np.float32).reshape(1, 4, 512, 512) for i in range(8)}
R = {i: dict(zip(names, IS.run(None, {"222": X[i]}))) for i in range(8)}
from ai_edge_litert.interpreter import Interpreter, OpResolverType
for f, (out_t, photos) in FRAGS.items():
    fd = f"{OUT}/fp16tpu/{f}"; os.makedirs(fd, exist_ok=True); shutil.copy(SAMPLE, fd)
    onnx.utils.extract_model(SRC, f"{fd}/{f}.onnx", ["222"], [out_t])
    r = subprocess.run(["onnx2tf", "-i", f"{fd}/{f}.onnx", "-o", fd, "-n", "-b", "1", "-ois", "222:1,4,512,512"], cwd=fd, capture_output=True, text=True)
    tfl = f"{fd}/{f}_float32.tflite"
    if not os.path.exists(tfl): print(r.stdout[-1500:], r.stderr[-1500:]); raise SystemExit(f"{f}: onnx2tf failed")
    it = Interpreter(model_path=tfl, experimental_op_resolver_type=OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES); it.allocate_tensors()
    ops = {}
    for d in it._get_ops_details(): ops[d["op_name"]] = ops.get(d["op_name"], 0) + 1
    lines, worst = [], 0.0
    for i in photos:
        x = np.ascontiguousarray(X[i].transpose(0, 2, 3, 1)); ref = R[i][out_t].transpose(0, 2, 3, 1)
        x.tofile(f"{fd}/in{i}.bin"); lines.append(f"/data/local/tmp/migan-tpu/fp16tpu/{f}/in{i}.bin"); np.save(f"{fd}/ref{i}.npy", ref)
        if i < 2:
            it.set_tensor(it.get_input_details()[0]["index"], x); it.invoke()
            worst = max(worst, float(np.abs(it.get_tensor(it.get_output_details()[0]["index"]) - ref).max()))
    open(f"{fd}/inputs.txt", "w").write("\n".join(lines) + "\n")
    print(f, {"ops": sum(ops.values()), "MB": round(os.path.getsize(tfl) / 1e6, 1), "out": list(map(int, it.get_output_details()[0]["shape"])),
              "desktop_vs_original_maxabs": worst, "ref_absmax": float(np.abs(R[0][out_t]).max()), "flex": [k for k in ops if k.startswith("Flex")]}, flush=True)
