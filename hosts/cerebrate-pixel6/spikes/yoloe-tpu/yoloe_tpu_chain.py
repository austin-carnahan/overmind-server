"""Device int8 backbone outputs (TFLite bench .bin, NHWC int8) -> dequantize ->
fp32 head ONNX on the desktop, in the layout yoloe_task_accuracy.py reads;
plus TPU vs CPU int8 agreement.  usage: <yoloe dir> <tflite> <model> <device out dir> <tag> [compare dir]"""
import sys, os
import numpy as np, onnxruntime as ort
from ai_edge_litert.interpreter import Interpreter
Y, TFL, v, DO, tag = sys.argv[1:6]; CMP = sys.argv[6] if len(sys.argv) > 6 else None
outs = Interpreter(model_path=TFL).get_output_details()
onb = ort.InferenceSession(f"{Y}/{v}-backbone.onnx"); byshape = {tuple(o.shape): o.name for o in onb.get_outputs()}
h = ort.InferenceSession(f"{Y}/{v}-head.onnx"); hin = [i.name for i in h.get_inputs()]
od = f"{Y}/desk/{v.split('-')[1]}-{tag}"; os.makedirs(od, exist_ok=True)
diff = tot = mx = 0
for i in range(8):
    fmap = {}
    for k, o in enumerate(outs):
        raw = np.fromfile(f"{DO}/{i}_o{k}.bin", np.int8).reshape(o["shape"])
        if CMP:
            c = np.fromfile(f"{CMP}/{i}_o{k}.bin", np.int8).reshape(o["shape"]); d = np.abs(raw.astype(int) - c)
            diff += int((d > 0).sum()); tot += d.size; mx = max(mx, int(d.max()))
        s, z = o["quantization"]; a = ((raw.astype(np.float32) - z) * s).transpose(0, 3, 1, 2); fmap[byshape[a.shape]] = a
    for k, o in enumerate(h.run(None, {n: fmap[n] for n in hin})):
        o.astype(np.float32).tofile(f"{od}/{i}_o{k}.bin")
if CMP: print(f"{tag} vs {os.path.basename(CMP)}: {diff}/{tot} int8 values differ ({100 * diff / tot:.2f}%), max {mx} steps")
