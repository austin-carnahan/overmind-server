"""Edge TPU precision probes (Step 2B follow-up, step 1). Tiny TensorFlow
models built from the ops YOLO-family models use, converted with the classic
TFLite converter in five precision variants, plus a size ladder for fp16.
- conv: [1,80,80,64] -> conv3x3 -> SiLU (x*sigmoid) -> conv1x1 -> residual add
  -> concat -> maxpool 5x5 -> nearest 2x upsample -> conv3x3 stride 2
- attn: [1,400,64] -> q/k/v dense -> softmax(q k^T / 8) v -> dense + residual
- variants: fp32 | fp16w (fp16 weights) | int8 (full integer, int8 I/O) |
  int8pt (int8 with per-tensor weights -- NNAPI's FULLY_CONNECTED rejects
  per-channel int8 weights) | int16x8 (16-bit activations, 8-bit weights)
- ladder: K x (conv3x3 64->64 + SiLU) at [1,160,160,64], fp32, K = 2, 8, 24
Writes .tflite files, fixed input .bin files (float and quantized) and the
fp32 reference outputs.  usage: <out dir>"""
import sys, json, os
import numpy as np, tensorflow as tf
OUT = sys.argv[1]; rng = np.random.default_rng(0); tf.random.set_seed(0)
silu = lambda x: x * tf.sigmoid(x)
V = lambda *shape: tf.Variable(tf.random.normal(shape, stddev=(2.0 / np.prod(shape[:-1])) ** 0.5))
conv = lambda x, w, b, stride=1: tf.nn.conv2d(x, w, stride, "SAME") + b

class ConvBlock(tf.Module):
    shape = (1, 80, 80, 64)
    def __init__(self):
        self.w1, self.b1, self.w2, self.b2, self.w3, self.b3 = V(3, 3, 64, 64), V(64), V(1, 1, 64, 64), V(64), V(3, 3, 128, 64), V(64)
    @tf.function(input_signature=[tf.TensorSpec(shape, tf.float32)])
    def __call__(self, i):
        a = silu(conv(i, self.w1, self.b1)); b = conv(a, self.w2, self.b2) + i
        d = tf.nn.max_pool2d(tf.concat([a, b], -1), 5, 1, "SAME")
        e = tf.image.resize(d, (160, 160), "nearest")
        return conv(e, self.w3, self.b3, 2)

class AttnBlock(tf.Module):
    shape = (1, 400, 64)
    def __init__(self):
        self.wq, self.wk, self.wv, self.wo = (V(64, 64) for _ in range(4))
    @tf.function(input_signature=[tf.TensorSpec(shape, tf.float32)])
    def __call__(self, i):
        q, k, v = (tf.matmul(i, w) for w in (self.wq, self.wk, self.wv))
        w = tf.nn.softmax(tf.matmul(q, k, transpose_b=True) / 8.0, -1)
        return tf.matmul(tf.matmul(w, v), self.wo) + i

def ladder_module(K):
    class Ladder(tf.Module):
        shape = (1, 160, 160, 64)
        def __init__(self): self.ws = [(V(3, 3, 64, 64), V(64)) for _ in range(K)]
        @tf.function(input_signature=[tf.TensorSpec((1, 160, 160, 64), tf.float32)])
        def __call__(self, x):
            for w, b in self.ws: x = silu(conv(x, w, b))
            return x
    return Ladder()

def convert(model, variant, calib):
    c = tf.lite.TFLiteConverter.from_concrete_functions([model.__call__.get_concrete_function()], model)
    if variant == "fp16w":
        c.optimizations = [tf.lite.Optimize.DEFAULT]; c.target_spec.supported_types = [tf.float16]
    elif variant in ("int8", "int8pt", "int16x8"):
        c.optimizations = [tf.lite.Optimize.DEFAULT]
        c.representative_dataset = lambda: ([x] for x in calib)
        if variant == "int8pt":
            c._experimental_disable_per_channel = True
        if variant in ("int8", "int8pt"):
            c.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
            c.inference_input_type = tf.int8; c.inference_output_type = tf.int8
        else:
            c.target_spec.supported_ops = [tf.lite.OpsSet.EXPERIMENTAL_TFLITE_BUILTINS_ACTIVATIONS_INT16_WEIGHTS_INT8]
    return c.convert()

meta = {}
for name, build in (("conv", ConvBlock), ("attn", AttnBlock)):
    m = build(); shape = m.shape; calib = [rng.standard_normal(shape).astype(np.float32) for _ in range(32)]
    x = rng.standard_normal(shape).astype(np.float32); x.tofile(f"{OUT}/{name}-in-f32.bin")
    np.save(f"{OUT}/{name}-ref.npy", m(tf.constant(x)).numpy())
    for var in ("fp32", "fp16w", "int8", "int8pt", "int16x8"):
        open(f"{OUT}/{name}-{var}.tflite", "wb").write(convert(m, var, calib))
        it = tf.lite.Interpreter(model_path=f"{OUT}/{name}-{var}.tflite"); d = it.get_input_details()[0]; o = it.get_output_details()[0]
        if d["dtype"] != np.float32:
            s, z = d["quantization"]; info = np.iinfo(d["dtype"])
            np.clip(np.round(x / s + z), info.min, info.max).astype(d["dtype"]).tofile(f"{OUT}/{name}-in-{var}.bin")
        meta[f"{name}-{var}"] = {"in": d["dtype"].__name__, "in_q": list(map(float, d["quantization"])), "out": o["dtype"].__name__,
                                 "out_q": list(map(float, o["quantization"])), "out_shape": list(map(int, o["shape"])),
                                 "ops": len(it._get_ops_details())}
for K in (2, 8, 24):
    m = ladder_module(K); x = rng.standard_normal((1, 160, 160, 64)).astype(np.float32)
    if K == 2: x.tofile(f"{OUT}/ladder-in-f32.bin")
    else: x = np.fromfile(f"{OUT}/ladder-in-f32.bin", np.float32).reshape(1, 160, 160, 64)
    np.save(f"{OUT}/ladder{K}-ref.npy", m(tf.constant(x)).numpy())
    open(f"{OUT}/ladder{K}-fp32.tflite", "wb").write(convert(m, "fp32", None))
    meta[f"ladder{K}-fp32"] = {"in": "float32", "out": "float32", "out_shape": [1, 160, 160, 64], "MB": os.path.getsize(f"{OUT}/ladder{K}-fp32.tflite") / 1e6}
json.dump(meta, open(f"{OUT}/meta.json", "w"), indent=1)
for k, v in meta.items(): print(k, v)
