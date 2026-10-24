"""onnx2tf full-integer TFLite backbone (NHWC, int8 I/O): op/dtype inspection
(QUANTIZE requantizations, float ops), feature cosine vs the fp32 ONNX
backbone, and the desktop task chain (int8 TFLite -> fp32 head ONNX) written
in the device layout for yoloe_task_accuracy.py; also writes the quantized
device inputs.  usage: <yoloe dir> <tflite> <model> <tag>"""
import sys, os, collections
import numpy as np, onnxruntime as ort
from ai_edge_litert.interpreter import Interpreter, OpResolverType
Y, TFL, v, tag = sys.argv[1:5]
it = Interpreter(model_path=TFL, experimental_op_resolver_type=OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES); it.allocate_tensors()
td = {t["index"]: t for t in it.get_tensor_details()}; ops = it._get_ops_details()
fl = collections.Counter(o["op_name"] for o in ops if any(td[i]["dtype"] == np.float32 for i in o["outputs"]))
req = sum(1 for o in ops if o["op_name"] == "QUANTIZE" and td[o["inputs"][0]]["dtype"] != np.float32)
ins, outs = it.get_input_details(), it.get_output_details()
print(f"{os.path.basename(TFL)}: {len(ops)} ops {collections.Counter(o['op_name'] for o in ops).most_common(10)}; int8->int8 QUANTIZE: {req}; float-output ops: {dict(fl)}")
print(f"  input {list(ins[0]['shape'])} {ins[0]['dtype'].__name__} {ins[0]['quantization']}; outputs {[(list(o['shape']), o['dtype'].__name__) for o in outs]}")
onb = ort.InferenceSession(f"{Y}/{v}-backbone.onnx"); h = ort.InferenceSession(f"{Y}/{v}-head.onnx"); hin = [i.name for i in h.get_inputs()]
byshape = {tuple(o.shape): o.name for o in onb.get_outputs()}
od = f"{Y}/desk/{v.split('-')[1]}-backbone-{tag}"; os.makedirs(od, exist_ok=True); dd = os.path.dirname(TFL)
q = ins[0]["quantization"]; cos = []
for i in range(8):
    x = np.load(f"{Y}/in{i}.npz")["images"]; xn = x.transpose(0, 2, 3, 1)
    if ins[0]["dtype"] != np.float32:
        xn = np.clip(np.round(xn / q[0] + q[1]), -128, 127).astype(ins[0]["dtype"]); xn.tofile(f"{dd}/{v}-in{i}.bin")
    it.set_tensor(ins[0]["index"], xn); it.invoke()
    ref = dict(zip([o.name for o in onb.get_outputs()], onb.run(None, {"images": x})))
    fmap = {}
    for o in outs:
        a = it.get_tensor(o["index"]); s, z = o["quantization"]
        a = ((a.astype(np.float32) - z) * s if s else a).transpose(0, 3, 1, 2)
        n = byshape[a.shape]; fmap[n] = a; cos.append(float(a.ravel() @ ref[n].ravel() / (np.linalg.norm(a) * np.linalg.norm(ref[n]))))
    for k, o in enumerate(h.run(None, {n: fmap[n] for n in hin})):
        o.astype(np.float32).tofile(f"{od}/{i}_o{k}.bin")
c = np.array(cos).reshape(8, -1)
print(f"  feature cosine vs fp32 (min over 8 photos, per output): {[round(float(m), 4) for m in c.min(0)]}")
