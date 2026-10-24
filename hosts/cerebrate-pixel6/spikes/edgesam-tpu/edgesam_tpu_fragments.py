"""Growing fragments of the TPU-prepared EdgeSAM encoder for the guarded
device sequence (as yoloe-tpu's fp16 run): each cut from the input image to
a block boundary, converted with onnx2tf to float32 TFLite (NHWC), checked
on the desktop against the *unmodified* exported encoder's tensor at the
same point, plus device inputs (raw NHWC float32) and references.
F1 -> features.3 (end of the 256x256 stage, incl. the first SE mean over
256x256), F2 -> features.7 (128x128), F3 -> features.23 (64x64),
F4 -> the whole encoder. The "t" fragments use tanh-GELU: the near-exact
GELU's F1 had every op on the TPU but its compile hit the driver's deadline
(~60 s), while the tanh F1 compiled in 7.6 s. F2t (118 ops) also hit the
deadline, so the encoder goes to the TPU as segments: S1 = F1t, S2 =
features.4-7, S3 = features.8-23, S4 = the rest; each segment's input is the
unmodified model's tensor at its cut (errors measured per segment).
usage: edgesam_tpu_fragments.py <out dir> <calibration sample .npy for onnx2tf> [fragment ...]"""
import sys, os, json, shutil, subprocess
import numpy as np, onnx, onnxruntime as ort
from onnx import helper, TensorProto
OUT, SAMPLE = sys.argv[1:3]
RAW = f"{OUT}/edgesam_encoder_bicubic.onnx"
B = lambda k: f"/features.{k}/channel_mixer/Add_output_0"
FRAGS = {"F1": ("erfpoly", B(3), [0, 1]), "F2": ("erfpoly", B(7), [0, 1]), "F3": ("erfpoly", B(23), [0, 1]),
         "F4": ("erfpoly", "image_embeddings", list(range(8))), "F1t": ("tanh", B(3), [0, 1]), "F2t": ("tanh", B(7), [0, 1]),
         "F3t": ("tanh", B(23), [0, 1]), "F4t": ("tanh", "image_embeddings", list(range(8))),
         "S2": ("tanh", B(7), [0, 1], B(3)), "S2a": ("tanh", B(4), [0], B(3)), "S2b": ("tanh", B(7), [0], B(4)), "S3": ("tanh", B(23), [0, 1], B(7)), "S4": ("tanh", "image_embeddings", [0, 1], B(23))}
F4M = "/features.4/channel_mixer/m/m."   # S2a (block 4 alone) cut after each step, to bisect its compile timeout
FRAGS.update({"S2a1": ("tanh", "/features.4/token_mixer/token_mixer.2/c/Conv_output_0", [0], B(3)),
              "S2a2": ("tanh", F4M + "0/c/Conv_output_0", [0], B(3)),
              "S2a3": ("tanh", F4M + "1/Mul_1_output_0", [0], B(3)),
              "S2a4": ("tanh", F4M + "2/c/Conv_output_0", [0], B(3)),
              "S2a3b": ("tanh", F4M + "1/Mul_1_output_0", [0], "/features.4/token_mixer/token_mixer.0/c/Conv_output_0"),
              "S2a3c": ("tanh", F4M + "1/Mul_1_output_0", [0], "/features.4/token_mixer/token_mixer.2/c/Conv_output_0")})
# TPU + GPU split: the TPU stage stops before the neck, whose two LayerNorms
# the TPU rejects (19 ops fell to the CPU in F4t) and which would overflow
# in fp16 anyway (squares of activations ~600); the neck runs exact on the GPU.
FRAGS.update({"T1": ("tanh", "/Add_output_0", list(range(8))),
              "N1": ("erfpoly", "image_embeddings", list(range(8)), "/Add_output_0"),   # the neck has no GELU
              # T1 with the refitted GELU: identical structure, different constants -- for the
              # compilation-cache collision test (a reused token must not serve T1's compilation)
              "T1fit": ("fit", "/Add_output_0", [0, 1])})
if len(sys.argv) > 3:
    FRAGS = {k: v for k, v in FRAGS.items() if k in sys.argv[3:]}
inter = onnx.load(RAW)
for t in ({v[1] for v in FRAGS.values()} | {v[3] for v in FRAGS.values() if len(v) > 3}) - {"image_embeddings"}:
    inter.graph.output.append(helper.make_tensor_value_info(t, TensorProto.FLOAT, None))
onnx.save(inter, f"{OUT}/inter.onnx")
IS = ort.InferenceSession(f"{OUT}/inter.onnx"); names = [o.name for o in IS.get_outputs()]
refs = {}
for i in range(8):
    refs[i] = dict(zip(names, IS.run(None, {"image": np.load(f"{OUT}/in{i}.npz")["image"]})))
from ai_edge_litert.interpreter import Interpreter, OpResolverType
meta = {}
for f, (variant, out_t, photos, *cut) in FRAGS.items():
    in_t = cut[0] if cut else "image"
    fd = f"{OUT}/fp16tpu/{f}"; os.makedirs(fd, exist_ok=True); shutil.copy(SAMPLE, fd)
    onnx.utils.extract_model(f"{OUT}/edgesam_encoder_tpu_{variant}.onnx", f"{fd}/{f}.onnx", [in_t], [out_t])
    r = subprocess.run(["onnx2tf", "-i", f"{fd}/{f}.onnx", "-o", fd, "-n"], cwd=fd, capture_output=True, text=True)
    tfl = f"{fd}/{f}_float32.tflite"
    if not os.path.exists(tfl): print(r.stdout[-2000:], r.stderr[-2000:]); raise SystemExit(f"{f}: onnx2tf failed")
    it = Interpreter(model_path=tfl, experimental_op_resolver_type=OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES); it.allocate_tensors()
    ops = {}
    for d in it._get_ops_details(): ops[d["op_name"]] = ops.get(d["op_name"], 0) + 1
    lines, worst = [], 0.0
    for i in photos:
        x = np.load(f"{OUT}/in{i}_nhwc.npz")["image"] if in_t == "image" else np.ascontiguousarray(refs[i][in_t].transpose(0, 2, 3, 1))
        ref = refs[i][out_t].transpose(0, 2, 3, 1)
        x.astype(np.float32).tofile(f"{fd}/in{i}.bin"); lines.append(f"/data/local/tmp/edgesam/fp16tpu/{f}/in{i}.bin")
        np.save(f"{fd}/ref{i}.npy", ref)
        if i < 2:
            it.set_tensor(it.get_input_details()[0]["index"], x); it.invoke()
            worst = max(worst, float(np.abs(it.get_tensor(it.get_output_details()[0]["index"]) - ref).max()))
    open(f"{fd}/inputs.txt", "w").write("\n".join(lines) + "\n")
    meta[f] = {"gelu": variant, "ops": sum(ops.values()), "MB": round(os.path.getsize(tfl) / 1e6, 1),
               "out": list(map(int, it.get_output_details()[0]["shape"])), "photos": len(photos),
               "desktop_fp32_tflite_vs_unmodified_maxabs": worst, "ref_absmax": float(np.abs(refs[0][out_t]).max()),
               "op_types": dict(sorted(ops.items(), key=lambda kv: -kv[1]))}
    print(f, {k: v for k, v in meta[f].items() if k != "op_types"}, flush=True)
    print("   ", meta[f]["op_types"], flush=True)
mp = f"{OUT}/fp16tpu/meta.json"
json.dump({**(json.load(open(mp)) if os.path.exists(mp) else {}), **meta}, open(mp, "w"), indent=1)
