"""YOLOE backbone + neck as a fully-integer TFLite model for the Edge TPU via
TFLite's NNAPI delegate (TPU path 2). Wrapper over the fused Ultralytics
layers before the head (returning the three feature maps the head takes);
PT2E static quantization in litert-torch (int8 per-channel symmetric weights,
int8 affine activations from histogram observers; sigmoid with fixed
qparams), calibrated on indoor COCO val2017 photos. nn.SiLU is spelled out as
x * sigmoid(x) (identical) so the quantizer annotates its sigmoid and mul --
left as SiLU it stays float, with QUANTIZE/DEQUANTIZE around every
activation. The model's input and outputs come out int8: the host quantizes
the image and dequantizes the feature maps with their scale/zero point. Stage 1: wrapper vs the fp32 ONNX backbone;
then an op/dtype inspection; then int8 TFLite (desktop) -> fp32 head ONNX ->
.bin outputs in the device layout for yoloe_task_accuracy.py.
usage: <dl-yoloe dir> <yoloe dir> <calib dir> <out dir> <n_calib>"""
import sys, glob, os, collections
import numpy as np, cv2, torch, onnxruntime as ort
import litert_torch
from litert_torch.quantize import pt2e_quantizer
from litert_torch.quantize.quant_config import QuantConfig
from torchao.quantization.pt2e import quantize_pt2e
from ultralytics import YOLOE
from ultralytics.data.augment import LetterBox
D, Y, C, OUT, NCAL = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5])
torch.set_grad_enabled(False)
lb = LetterBox((640, 640), auto=False)
def prep(p):
    im = lb(image=cv2.imread(p)); return torch.from_numpy(np.ascontiguousarray(im[..., ::-1].transpose(2, 0, 1))[None].astype(np.float32) / 255)

class SiLU(torch.nn.Module):
    def forward(s, x): return x * torch.sigmoid(x)

class Backbone(torch.nn.Module):
    def __init__(s, dm):
        super().__init__(); s.layers = dm.model[:-1]; s.save = set(dm.save); s.head_f = list(dm.model[-1].f)
    def forward(s, x):
        y = []
        for m in s.layers:
            if m.f != -1:
                x = y[m.f] if isinstance(m.f, int) else [x if j == -1 else y[j] for j in m.f]
            x = m(x); y.append(x if m.i in s.save or m.i in s.head_f else None)
        return tuple(y[j] for j in s.head_f)

for v in ("yoloe-v8s-seg-pf", "yoloe-11s-seg-pf"):
    dm = YOLOE(f"{D}/{v}.pt").model.fuse().eval()
    for mod in dm.modules():
        for name, ch in list(mod.named_children()):
            if isinstance(ch, torch.nn.SiLU): setattr(mod, name, SiLU())
    B = Backbone(dm).eval()
    x0 = torch.from_numpy(np.load(f"{Y}/in0.npz")["images"])
    onb = ort.InferenceSession(f"{Y}/{v}-backbone.onnx"); ref = onb.run(None, {"images": x0.numpy()})
    got = [t.numpy() for t in B(x0)]
    print(f"{v} stage 1 (wrapper vs fp32 ONNX backbone): max abs " + ", ".join(f"{np.abs(a - b).max():.1e}" for a, b in zip(got, ref)), flush=True)
    m = torch.export.export(B, (x0,)).module()
    q = pt2e_quantizer.PT2EQuantizer().set_global(pt2e_quantizer.get_symmetric_quantization_config(is_per_channel=True))
    m = quantize_pt2e.prepare_pt2e(m, q)
    for p in sorted(glob.glob(f"{C}/*.jpg"))[:NCAL]:
        m(prep(p))
    m = quantize_pt2e.convert_pt2e(m, fold_quantize=False)
    path = f"{OUT}/{v}-backbone-int8.tflite"
    litert_torch.convert(m, (x0,), quant_config=QuantConfig(pt2e_quantizer=q)).export(path)
    from ai_edge_litert.interpreter import Interpreter
    it = Interpreter(model_path=path, experimental_op_resolver_type=__import__("ai_edge_litert.interpreter", fromlist=["x"]).OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES)
    it.allocate_tensors(); td = {t["index"]: t for t in it.get_tensor_details()}
    ops = it._get_ops_details()
    fl = collections.Counter(o["op_name"] for o in ops if any(td[i]["dtype"] == np.float32 for i in o["outputs"]))
    print(f"  {path.split('/')[-1]}: {os.path.getsize(path) / 1e6:.1f} MB, {len(ops)} ops: {collections.Counter(o['op_name'] for o in ops).most_common(12)}; "
          f"ops with float outputs: {dict(fl)}", flush=True)
    # desktop chain: int8 TFLite backbone -> fp32 head
    h = ort.InferenceSession(f"{Y}/{v}-head.onnx"); hin = [i.name for i in h.get_inputs()]
    ins = it.get_input_details(); outs = it.get_output_details()
    od = f"{Y}/desk/{v.split('-')[1]}-backbone-int8-tflite"; os.makedirs(od, exist_ok=True)
    qin = ins[0]["quantization"]; print(f"  input {ins[0]['dtype'].__name__} scale/zp {qin}; outputs {[(o['dtype'].__name__, o['quantization']) for o in outs]}", flush=True)
    deq = lambda a, q: (a.astype(np.float32) - q[1]) * q[0] if q[0] else a
    for i in range(8):
        x = np.load(f"{Y}/in{i}.npz")["images"]
        if ins[0]["dtype"] != np.float32:
            x = np.clip(np.round(x / qin[0] + qin[1]), -128, 127).astype(ins[0]["dtype"])
            x.tofile(f"{OUT}/{v}-in{i}.bin")                                   # device input, same quantization
        it.set_tensor(ins[0]["index"], x); it.invoke()
        feats = sorted([deq(it.get_tensor(o["index"]), o["quantization"]) for o in outs], key=lambda a: -a.shape[2])   # 80, 40, 20
        bsz = {tuple(onb.get_outputs()[k].shape): n for k, n in enumerate(o.name for o in onb.get_outputs())}
        fmap = {bsz[tuple(f.shape)]: f for f in feats}
        for k, o in enumerate(h.run(None, {n: fmap[n] for n in hin})):
            o.astype(np.float32).tofile(f"{od}/{i}_o{k}.bin")
    print(f"  desktop chain outputs -> {od}", flush=True)
