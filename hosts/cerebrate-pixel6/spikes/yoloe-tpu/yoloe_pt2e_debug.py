"""Where does the int8 PT2E backbone lose accuracy: PyTorch quantized model
(after convert_pt2e) vs fp32, then the converted TFLite vs both."""
import sys, glob, importlib.util
import numpy as np, torch
sys.argv = [sys.argv[0]] + sys.argv[1:]
D, Y, C, OUT = sys.argv[1:5]
spec = importlib.util.spec_from_file_location("m", sys.path[0] + "/yoloe_int8_tflite.py")
src = open(sys.path[0] + "/yoloe_int8_tflite.py").read().split("for v in (")[0]       # definitions only
exec(src.replace("D, Y, C, OUT, NCAL = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5])", "NCAL = 32"))
v = "yoloe-v8s-seg-pf"
dm = YOLOE(f"{D}/{v}.pt").model.fuse().eval()
for mod in dm.modules():
    for name, ch in list(mod.named_children()):
        if isinstance(ch, torch.nn.SiLU): setattr(mod, name, SiLU())
B = Backbone(dm).eval(); x0 = torch.from_numpy(np.load(f"{Y}/in0.npz")["images"])
fp = [t.numpy() for t in B(x0)]
cos = lambda a, b: float(a.ravel() @ b.ravel() / (np.linalg.norm(a) * np.linalg.norm(b)))
for per_channel in (True, False):
    m = torch.export.export(B, (x0,)).module()
    q = pt2e_quantizer.PT2EQuantizer().set_global(pt2e_quantizer.get_symmetric_quantization_config(is_per_channel=per_channel))
    m = quantize_pt2e.prepare_pt2e(m, q)
    for p in sorted(glob.glob(f"{C}/*.jpg"))[:32]: m(prep(p))
    m = quantize_pt2e.convert_pt2e(m, fold_quantize=False)
    qo = [t.numpy() for t in m(x0)]
    print(f"per_channel={per_channel}: PyTorch quantized vs fp32 cosine per scale: {[round(cos(a, b), 4) for a, b in zip(qo, fp)]}", flush=True)
