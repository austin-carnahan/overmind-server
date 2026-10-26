"""Single-op TFLite graphs to find what makes the Edge TPU compiler run past
its ~60 s deadline on EdgeSAM's 128x128 stage (S2a: 13 ops, S2b: 47 ops
both time out; the 256x256 stage F1t compiles in 7.6 s). float32 graphs,
run with fp16 relaxation. Random weights unless noted: only compile
behavior matters. Modes, in the order they were run:
  (default)  single ops on the stage's shapes -- all compile in < 0.5 s
  --gelu     three GELU structures alone on 128x128x192 -- all compile
  --convgelu 1x1 conv 96 -> 192 + each GELU -- all compile
  --s2a3c <weights.npz>  the failing fragment's real weights in the passing
             op order (compiles, 0.66 s) vs random weights in onnx2tf's op
             order (times out): the op order is the cause
usage: compile_probes.py <out dir> [--gelu | --convgelu | --s2a3c <weights.npz>]"""
import sys, os
import numpy as np, tensorflow as tf
OUT = sys.argv[1]
rng = np.random.default_rng(0)
def conv1x1(cin, cout): return tf.keras.layers.Conv2D(cout, 1, kernel_initializer=tf.constant_initializer(rng.normal(0, 0.1, (1, 1, cin, cout))))
PROBES = {  # name: (input shape, layer builder)
    "c256x48to96": ((256, 256, 48), lambda: conv1x1(48, 96)),
    "c128x96to96": ((128, 128, 96), lambda: conv1x1(96, 96)),
    "c128x96to128": ((128, 128, 96), lambda: conv1x1(96, 128)),
    "c128x96to192": ((128, 128, 96), lambda: conv1x1(96, 192)),
    "c128x192to96": ((128, 128, 192), lambda: conv1x1(192, 96)),
    "mul128x192": ((128, 128, 192), lambda: tf.keras.layers.Lambda(lambda x: x * x)),
    "mul256x96": ((256, 256, 96), lambda: tf.keras.layers.Lambda(lambda x: x * x)),
    "dw3s2_256x48": ((258, 258, 48), lambda: tf.keras.layers.DepthwiseConv2D(3, 2, padding="valid")),
    "c64x192to384": ((64, 64, 192), lambda: conv1x1(192, 384)),
}
# GELU structures on the failing 128x128x192 tensor (S2a3: the tanh GELU after
# the 96 -> 192 expansion times out; a single multiply there compiles).
C1, C3 = 1.5957691216057308, 1.5957691216057308 * 0.044715
GELUS = {"tanh": lambda x: x * tf.sigmoid(x * C1 + x * x * x * C3),          # as exported: 7 ops
         "compact": lambda x: x * tf.sigmoid(x * (C1 + C3 * (x * x))),     # 6 ops
         "silu": lambda x: x * tf.sigmoid(1.702 * x)}                       # 2-3 ops (structure only)
PROBES = {f"gelu_{g}_{h}x{c}": ((h, h, c), (lambda f: lambda: tf.keras.layers.Lambda(f))(fn))
          for g, fn in GELUS.items() for h, c in ((128, 192),)} if "--gelu" in sys.argv else PROBES
# ...and after a 1x1 conv (96 -> 192), as in the model
PROBES = {f"convgelu_{g}_128x192": ((128, 128, 96), (lambda f: lambda: tf.keras.Sequential([conv1x1(96, 192), tf.keras.layers.Lambda(f)]))(fn))
          for g, fn in GELUS.items()} if "--convgelu" in sys.argv else PROBES
# Hypotheses for S2a3c (conv 96 -> 192 + tanh GELU; times out, while the same
# ops from Keras compile): real weights vs random, and op order.
if "--s2a3c" in sys.argv:
    wb = np.load(sys.argv[sys.argv.index("--s2a3c") + 1])
    def real_conv():
        return tf.keras.layers.Conv2D(192, 1, kernel_initializer=tf.constant_initializer(wb["w"].transpose(1, 2, 3, 0)),
                                      bias_initializer=tf.constant_initializer(wb["b"]))
    onnx2tf_order = lambda x: x * tf.sigmoid((x * x * x) * C3 + x * C1)   # x2, x3, cub, lin (as onnx2tf emitted)
    PROBES = {"s2a3c_realw_kerasorder": ((128, 128, 96), lambda: tf.keras.Sequential([real_conv(), tf.keras.layers.Lambda(GELUS["tanh"])])),
              "s2a3c_randw_onnx2tforder": ((128, 128, 96), lambda: tf.keras.Sequential([conv1x1(96, 192), tf.keras.layers.Lambda(onnx2tf_order)]))}
for name, (shape, make) in PROBES.items():
    d = f"{OUT}/{name}"; os.makedirs(d, exist_ok=True)
    inp = tf.keras.Input(shape, batch_size=1); model = tf.keras.Model(inp, make()(inp))
    conv = tf.lite.TFLiteConverter.from_keras_model(model)
    open(f"{d}/{name}_float32.tflite", "wb").write(conv.convert())
    rng.normal(0, 1, (1,) + shape).astype(np.float32).tofile(f"{d}/in0.bin")
    open(f"{d}/inputs.txt", "w").write(f"/data/local/tmp/edgesam/fp16tpu/{name}/in0.bin\n")
    print(name, shape)
