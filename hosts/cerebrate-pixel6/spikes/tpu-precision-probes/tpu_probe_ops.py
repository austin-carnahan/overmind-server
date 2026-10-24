"""Single-op Edge TPU probes: which op carries the TPU's error? sigmoid, SiLU
(x * sigmoid(x)), conv3x3, maxpool 5x5 stride 1 SAME, nearest 2x resize,
conv3x3 stride 2, and residual add + concat -- each alone, each as fp32 (run with fp16
relaxation) and int8 (full integer). Inputs span [-8, 8] for the activations.
usage: <out dir> [kinds, comma-separated]"""
import sys, json
import numpy as np, tensorflow as tf
OUT = sys.argv[1]; rng = np.random.default_rng(1); tf.random.set_seed(1)
SH = (1, 80, 80, 64)
class Op(tf.Module):
    def __init__(self, kind):
        self.kind = kind; self.w = tf.Variable(tf.random.normal((3, 3, 64, 64), stddev=(2 / 576) ** 0.5)); self.b = tf.Variable(tf.zeros(64))
    @tf.function(input_signature=[tf.TensorSpec(SH, tf.float32)])
    def __call__(self, x):
        if self.kind == "sigmoid": return tf.sigmoid(x)
        if self.kind == "silu": return x * tf.sigmoid(x)
        if self.kind == "maxpool": return tf.nn.max_pool2d(x, 5, 1, "SAME")
        if self.kind == "resize": return tf.image.resize(x, (160, 160), "nearest")
        if self.kind == "conv2": return tf.nn.conv2d(x, self.w, 2, "SAME") + self.b
        if self.kind == "addcat": return tf.concat([x + x[:, :, ::-1, :], x], -1)
        return tf.nn.conv2d(x, self.w, 1, "SAME") + self.b
meta = json.load(open(f"{OUT}/meta.json"))
x = np.linspace(-8, 8, int(np.prod(SH)), dtype=np.float32).reshape(SH); rng.shuffle(x.reshape(-1)); x.tofile(f"{OUT}/op-in-f32.bin")
calib = [rng.uniform(-8, 8, SH).astype(np.float32) for _ in range(16)] + [x]
KINDS = sys.argv[2].split(",") if len(sys.argv) > 2 else ["sigmoid", "silu", "conv"]
for kind in KINDS:
    m = Op(kind); np.save(f"{OUT}/op{kind}-ref.npy", m(tf.constant(x)).numpy())
    for var in ("fp32", "int8"):
        c = tf.lite.TFLiteConverter.from_concrete_functions([m.__call__.get_concrete_function()], m)
        if var == "int8":
            c.optimizations = [tf.lite.Optimize.DEFAULT]; c.representative_dataset = lambda: ([a] for a in calib)
            c.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]; c.inference_input_type = tf.int8; c.inference_output_type = tf.int8
        name = f"op{kind}-{var}"; open(f"{OUT}/{name}.tflite", "wb").write(c.convert())
        it = tf.lite.Interpreter(model_path=f"{OUT}/{name}.tflite"); d = it.get_input_details()[0]; o = it.get_output_details()[0]
        inp = f"op-in-f32.bin"
        if d["dtype"] != np.float32:
            s, z = d["quantization"]; np.clip(np.round(x / s + z), -128, 127).astype(np.int8).tofile(f"{OUT}/op{kind}-in-int8.bin"); inp = f"op{kind}-in-int8.bin"
        open(f"{OUT}/{name}.txt", "w").write(f"/data/local/tmp/tpuprobe/{inp}\n")
        meta[name] = {"out": o["dtype"].__name__, "out_q": list(map(float, o["quantization"])), "ops": len(it._get_ops_details())}
        print(name, meta[name])
json.dump(meta, open(f"{OUT}/meta.json", "w"), indent=1)
