"""Desktop chain for the partitioned YOLOE: backbone (fp32 or int8, ONNX
Runtime CPU) -> fp32 head; writes the outputs as .bin files in the device
layout for yoloe_task_accuracy.py.  usage: <yoloe dir> <model> <backbone tag> <out dir>"""
import sys, os
import numpy as np, onnxruntime as ort
Y, v, tag, OUT = sys.argv[1:5]
# tag: fp32, int8, int8-percentile, ...
b = ort.InferenceSession(f"{Y}/{v}-backbone{'' if tag == 'fp32' else '-' + tag}.onnx"); h = ort.InferenceSession(f"{Y}/{v}-head.onnx")
names = [i.name for i in h.get_inputs()]; os.makedirs(OUT, exist_ok=True)
for i in range(8):
    feats = b.run(None, {"images": np.load(f"{Y}/in{i}.npz")["images"]})
    fmap = dict(zip([o.name for o in b.get_outputs()], feats))
    for k, o in enumerate(h.run(None, {n: fmap[n] for n in names})):
        o.astype(np.float32).tofile(f"{OUT}/{i}_o{k}.bin")
