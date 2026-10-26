"""Bisect the conv probe block's TPU error: the same block truncated after
each stage (A conv+SiLU, B + conv1x1 + residual, C concat, D maxpool 5x5,
E nearest 2x, F conv stride 2 = the full block), same weights and input as
conv-* (rebuilt from the same seed), fp32 (run fp16-relaxed) and int8.
usage: <probe dir>"""
import sys, json
import numpy as np, tensorflow as tf
OUT = sys.argv[1]; rng = np.random.default_rng(0); tf.random.set_seed(0)
silu = lambda x: x * tf.sigmoid(x)
V = lambda *shape: tf.Variable(tf.random.normal(shape, stddev=(2.0 / np.prod(shape[:-1])) ** 0.5))
conv = lambda x, w, b, stride=1: tf.nn.conv2d(x, w, stride, "SAME") + b
SH = (1, 80, 80, 64)
W = [V(3, 3, 64, 64), V(64), V(1, 1, 64, 64), V(64), V(3, 3, 128, 64), V(64)]
class Block(tf.Module):
    def __init__(self, stage): self.stage = stage; self.w = W
    @tf.function(input_signature=[tf.TensorSpec(SH, tf.float32)])
    def __call__(self, i):
        w1, b1, w2, b2, w3, b3 = self.w
        a = silu(conv(i, w1, b1))
        if self.stage == "A": return a
        b = conv(a, w2, b2) + i
        if self.stage == "B": return b
        c = tf.concat([a, b], -1)
        if self.stage == "C": return c
        d = tf.nn.max_pool2d(c, 5, 1, "SAME")
        if self.stage == "D": return d
        e = tf.image.resize(d, (160, 160), "nearest")
        if self.stage == "E": return e
        return conv(e, w3, b3, 2)
meta = json.load(open(f"{OUT}/meta.json"))
x = np.fromfile(f"{OUT}/conv-in-f32.bin", np.float32).reshape(SH)
calib = [rng.standard_normal(SH).astype(np.float32) for _ in range(32)]
for st in "ABCDEF":
    m = Block(st); np.save(f"{OUT}/bis{st}-ref.npy", m(tf.constant(x)).numpy())
    for var in ("fp32", "int8"):
        c = tf.lite.TFLiteConverter.from_concrete_functions([m.__call__.get_concrete_function()], m)
        if var == "int8":
            c.optimizations = [tf.lite.Optimize.DEFAULT]; c.representative_dataset = lambda: ([a] for a in calib)
            c.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]; c.inference_input_type = tf.int8; c.inference_output_type = tf.int8
        name = f"bis{st}-{var}"; open(f"{OUT}/{name}.tflite", "wb").write(c.convert())
        it = tf.lite.Interpreter(model_path=f"{OUT}/{name}.tflite"); d = it.get_input_details()[0]; o = it.get_output_details()[0]
        inp = "conv-in-f32.bin"
        if d["dtype"] != np.float32:
            s, z = d["quantization"]; np.clip(np.round(x / s + z), -128, 127).astype(np.int8).tofile(f"{OUT}/bis{st}-in-int8.bin"); inp = f"bis{st}-in-int8.bin"
        open(f"{OUT}/{name}.txt", "w").write(f"/data/local/tmp/tpuprobe/{inp}\n")
        meta[name] = {"out": o["dtype"].__name__, "out_q": list(map(float, o["quantization"]))}
json.dump(meta, open(f"{OUT}/meta.json", "w"), indent=1)
w0 = np.load(f"{OUT}/conv-ref.npy"); print("full block F reproduces conv-ref:", bool(np.allclose(np.load(f"{OUT}/bisF-ref.npy"), w0, atol=1e-5)))
