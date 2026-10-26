"""Step 2: where does YOLOE-v8s's int8 accuracy go?
(a) input mapping: the letterboxed image (k/255) through the int8 input
    quantization and back;
(b) per reference detection (Ultralytics' .pt predictions, 132): matched
    (same label, IoU >= 0.5), label flip (found at IoU >= 0.5 with another
    label), or missed -- with, for flips, the rank of the original label among
    the int8 run's class scores at the matched anchor and the original model's
    own top-1/top-2 margin; for misses, the int8 score of the original label
    at the original anchor (below the 0.25 threshold?);
(c) layer by layer: every intermediate tensor of the onnx2tf full-integer
    backbone vs its float32 twin (same tensor names), cosine after
    dequantization, in graph order.
usage: <yoloe dir> <onnx2tf out dir> <int8 run tag (desk subdir)>"""
import sys, os, collections
import numpy as np, onnx, onnx.utils, onnxruntime as ort
from ai_edge_litert.interpreter import Interpreter, OpResolverType
sys.argv, args = sys.argv[:1] + ["-", "-"], sys.argv[1:]
import yoloe_prep as yp
Y, TF, TAG = args; v = "yoloe-v8s-seg-pf"
# (a)
it8 = Interpreter(model_path=f"{TF}/{v}-backbone_full_integer_quant.tflite"); q = it8.get_input_details()[0]["quantization"]
x = np.load(f"{Y}/in0.npz")["images"]; xq = np.clip(np.round(x / q[0] + q[1]), -128, 127); back = (xq - q[1]) * q[0]
print(f"(a) input scale {q[0]:.9f} zp {q[1]}: max |dequant(quant(x)) - x| = {np.abs(back - x).max():.2e} (one step = {q[0]:.2e})")
# (b) full class scores from the fp32 head: extract the head up to the sigmoid scores
head = onnx.load(f"{Y}/{v}-head.onnx"); rm = next(n for n in head.graph.node if n.op_type == "ReduceMax")
full = f"{Y}/{v}-head-fullscores.onnx"
onnx.utils.extract_model(f"{Y}/{v}-head.onnx", full, [i.name for i in head.graph.input], ["boxes", rm.input[0]])
H = ort.InferenceSession(full); hin = [i.name for i in H.get_inputs()]
B = ort.InferenceSession(f"{Y}/{v}-backbone.onnx")
def feats_from_bins(d, i):
    o = {}
    for k in range(3):
        a = np.fromfile(f"{d}/{i}_o{k}.bin", np.float32)
    return None
def iou(a, b):
    lt = np.maximum(a[:, None, :2], b[None, :, :2]); rb = np.minimum(a[:, None, 2:], b[None, :, 2:])
    inter = np.clip(rb - lt, 0, None).prod(-1); ar = lambda z: (z[:, 2] - z[:, 0]) * (z[:, 3] - z[:, 1])
    return inter / (ar(a)[:, None] + ar(b)[None] - inter + 1e-9)
xyxy = lambda b: np.stack([b[0] - b[2] / 2, b[1] - b[3] / 2, b[0] + b[2] / 2, b[1] + b[3] / 2], 1)
miss_conf, match_conf = [], []
cat = collections.Counter(); flip_ranks, flip_margins, match_margins, miss_scores = [], [], [], []
names = __import__("ultralytics").YOLOE(f"{Y}/../dl-yoloe/{v}.pt").names
examples = []
for i in range(8):
    t = np.load(f"{Y}/{v}-task{i}.npz")
    fp = dict(zip([o.name for o in B.get_outputs()], B.run(None, {"images": np.load(f"{Y}/in{i}.npz")["images"]})))
    b32, s32 = H.run(None, {n: fp[n] for n in hin}); b32, s32 = b32[0], s32[0]           # [4,8400], [4585,8400]
    # int8 run: rebuild its features from the device/desktop .bin outputs of the int8 chain (head outputs only) ->
    # recompute class scores from the int8 backbone features instead: re-run the int8 tflite here
    it = Interpreter(model_path=f"{TF}/{v}-backbone_full_integer_quant.tflite", experimental_op_resolver_type=OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES); it.allocate_tensors()
    d = it.get_input_details()[0]; xx = np.load(f"{Y}/in{i}.npz")["images"].transpose(0, 2, 3, 1)
    it.set_tensor(d["index"], np.clip(np.round(xx / d["quantization"][0] + d["quantization"][1]), -128, 127).astype(np.int8)); it.invoke()
    byshape = {tuple(o.shape): o.name for o in B.get_outputs()}; f8 = {}
    for o in it.get_output_details():
        a = it.get_tensor(o["index"]); s, z = o["quantization"]; a = ((a.astype(np.float32) - z) * s).transpose(0, 3, 1, 2); f8[byshape[a.shape]] = a
    b8, s8 = H.run(None, {n: f8[n] for n in hin}); b8, s8 = b8[0], s8[0]
    det8, _ = yp.detections(b8[None], s8.max(0)[None], s8.argmax(0)[None], np.zeros((1, 32, 8400), np.float32), np.zeros((1, 32, 160, 160), np.float32))
    for r in range(len(t["conf"])):
        rb, rc = t["xyxy"][r], int(t["cls"][r])
        # the original anchor: best IoU with the reference box among fp32 anchors whose argmax is the reference class
        U32 = iou(rb[None], xyxy(b32))[0]; a32 = int(np.argmax(U32 * (s32.argmax(0) == rc)))
        top2 = np.sort(s32[:, a32])[-2:]; margin = float(top2[1] - top2[0])
        if len(det8):
            U = iou(rb[None], det8[:, :4])[0]; j = int(np.argmax(U))
        if len(det8) and U[j] >= 0.5 and int(det8[j, 5]) == rc:
            cat["matched"] += 1; match_margins.append(margin); match_conf.append(float(t["conf"][r]))
        elif len(det8) and U[j] >= 0.5:
            cat["label flip"] += 1; flip_margins.append(margin)
            a8 = int(np.argmax(iou(det8[j:j + 1, :4], xyxy(b8))[0] * (s8.argmax(0) == int(det8[j, 5]))))
            rank = int((s8[:, a8] > s8[rc, a8]).sum()) + 1; flip_ranks.append(rank)
            if len(examples) < 12: examples.append(f"{names[rc]} -> {names[int(det8[j, 5])]} (orig rank {rank}, fp32 margin {margin:.3f})")
        else:
            cat["missed"] += 1; miss_scores.append(float(s8[rc, a32])); miss_conf.append(float(t["conf"][r]))
print(f"(b) {dict(cat)} of {sum(cat.values())}")
pct = lambda a: np.percentile(a, [25, 50, 75]).round(3).tolist() if len(a) else []
print(f"    fp32 top-1/top-2 score margin (25/50/75th pct): matched {pct(match_margins)}, flipped {pct(flip_margins)}")
print(f"    flips: original label's rank in the int8 scores: {collections.Counter(min(r, 6) for r in flip_ranks)} (6 = 6 or worse)")
print(f"    misses: int8 score of the original label at the original anchor (25/50/75th): {pct(miss_scores)}; below 0.25: {sum(s < 0.25 for s in miss_scores)}/{len(miss_scores)}")
print(f"    original-model confidence (25/50/75th): matched {pct(match_conf)}, missed {pct(miss_conf)}; missed with original confidence < 0.35: {sum(c < 0.35 for c in miss_conf)}/{len(miss_conf)}")
print("    example flips:", "; ".join(examples))
if os.environ.get("SKIP_LAYERS"): sys.exit(0)
# (c) layer by layer
f32 = Interpreter(model_path=f"{TF}/{v}-backbone_float32.tflite", experimental_preserve_all_tensors=True, experimental_op_resolver_type=OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES); f32.allocate_tensors()
i8 = Interpreter(model_path=f"{TF}/{v}-backbone_full_integer_quant.tflite", experimental_preserve_all_tensors=True, experimental_op_resolver_type=OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES); i8.allocate_tensors()
xx = np.load(f"{Y}/in0.npz")["images"].transpose(0, 2, 3, 1)
f32.set_tensor(f32.get_input_details()[0]["index"], xx); f32.invoke()
d = i8.get_input_details()[0]; i8.set_tensor(d["index"], np.clip(np.round(xx / d["quantization"][0] + d["quantization"][1]), -128, 127).astype(np.int8)); i8.invoke()
t32 = {t["name"]: t for t in f32.get_tensor_details()}; rows = []
for op in i8._get_ops_details():
    for oi in op["outputs"]:
        t = i8.get_tensor_details()[oi] if False else next(tt for tt in i8.get_tensor_details() if tt["index"] == oi)
        if t["name"] not in t32 or t["dtype"] != np.int8: continue
        a = i8.get_tensor(oi).astype(np.float32); s, z = t["quantization"]; a = (a - z) * s
        b = f32.get_tensor(t32[t["name"]]["index"])
        if a.shape != b.shape: continue
        rows.append((op["index"], op["op_name"], t["name"][-48:], float(a.ravel() @ b.ravel() / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12)), a.shape))
print(f"(c) {len(rows)} int8 tensors matched to float32 by name; cosine along the graph (every 8th, plus every drop of > 0.02 from the previous):")
prev = 1.0
for k, (idx, op, name, c, shp) in enumerate(rows):
    if k % 8 == 0 or prev - c > 0.02:
        print(f"    op {idx:3} {op:24} {name:48} {list(shp)} cos {c:.4f}{'   <-- drop ' + format(prev - c, '.3f') if prev - c > 0.02 else ''}")
    prev = c
