"""TPU (fp16-relaxed) backbone + neck feature maps (NHWC float32 .bin, matched
by shape) -> the original fp32 head (ONNX, desktop) -> outputs in the layout
yoloe_task_accuracy.py reads.  usage: <yoloe dir> <device out dir> <tag>"""
import sys, os, glob
import numpy as np, onnxruntime as ort
Y, DO, tag = sys.argv[1:4]; v = "yoloe-v8s-seg-pf"
B = ort.InferenceSession(f"{Y}/{v}-backbone.onnx"); byshape = {tuple(o.shape): o.name for o in B.get_outputs()}
H = ort.InferenceSession(f"{Y}/{v}-head.onnx"); hin = [i.name for i in H.get_inputs()]
od = f"{Y}/desk/v8s-{tag}"; os.makedirs(od, exist_ok=True)
nchw = {(1, 80, 80, 128): (1, 128, 80, 80), (1, 40, 40, 256): (1, 256, 40, 40), (1, 20, 20, 512): (1, 512, 20, 20)}
for i in range(8):
    fmap = {}
    for f in glob.glob(f"{DO}/{i}_o*.bin"):
        a = np.fromfile(f, np.float32); hwc = next(s for s in nchw if np.prod(s) == a.size)
        fmap[byshape[nchw[hwc]]] = a.reshape(hwc).transpose(0, 3, 1, 2)
    for k, o in enumerate(H.run(None, {n: fmap[n] for n in hin})):
        o.astype(np.float32).tofile(f"{od}/{i}_o{k}.bin")
print("->", od)
