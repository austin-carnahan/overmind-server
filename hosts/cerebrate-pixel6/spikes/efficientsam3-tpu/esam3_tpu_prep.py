"""EfficientSAM3 RV-M's vision graph toward the Edge TPU (fp16-relaxed), from
efficientsam3-gpu's wrappers (esam3_convert.py). The graph is RepViT-M1.1 +
head (512 -> 1024, 3x3 at 32x32) + bilinear to 72x72 (the trunk), then SAM 3's
simple FPN (transposed convs up to 288x288, 256-channel 1x1 + 3x3 convs at
288/144/72; the neck). Steps (each selectable):
- gelu: every exact GELU of the vision graph as the tanh chain
  x * sigmoid(x * (c1 + c3 x^2)) (edgesam-tpu's TPU form; NNAPI has no GELU or
  ERF); FPN error vs the original on the eight photos, then the original
  grounding on the 11 validation samples (efficientsam3-gpu's e2e set),
  written as <dev>/e2e-tanh/<n>_o<k>.bin for esam3_e2e_accuracy.py.
- split: trunk (pixels -> 72x72x1024) and neck (-> the three FPN levels) as
  LiteRT graphs (litert-torch, exact GELU) for the GPU time split.
- frag: two small TPU fragments via ONNX -> onnx2tf (float32, NHWC):
  T1 = stem + first three RepViT blocks (1008 -> 252x252x64, tanh GELU),
  N1 = the neck's dominant pair, conv_1x1 + conv_3x3 256 -> 256 at 288x288
  (fed the original's input to it); desktop check against PyTorch; device
  inputs (raw NHWC float32) and references for photos 0 and 3.
- bisect: T1 truncated -- B0 = the stem (conv s2, GELU, conv s2), B1 = + one
  block, B2 = + two -- and T1K = T1 at a 1024x1024 input (the photo
  zero-padded), for T1's compile failure.
- probe: block 1's parts alone at 252x252x64, fed the stem's output -- PSE =
  the SE module (MEAN over 252x252, two 1x1 convs, sigmoid gate), PDW = the
  RepVGG depthwise (3x3 dw + identity, folded), PCM = the channel mixer
  (1x1 64 -> 128, GELU, 1x1 -> 64, residual) -- and N1S = N1 on the central
  144x144 of its input (a quarter of N1's activations: N1's compile size
  first).
usage: esam3_tpu_prep.py <repo> <ckpt> <dev dir (px*.bin, vref*.npz, gref*/wref*.npz)> <out dir> <onnx2tf sample .npy> [gelu,split,frag,bisect,probe]"""
import sys, os, shutil, subprocess, importlib.util
import numpy as np, torch
REPO, CKPT, DEV, OUT, SAMPLE = sys.argv[1:6]
STEPS = (sys.argv[6] if len(sys.argv) > 6 else "gelu,split,frag").split(",")
HERE = os.path.dirname(os.path.abspath(__file__))
if "split" not in STEPS:   # esam3_convert imports litert_torch, which the onnx2tf environment doesn't carry
    import types; sys.modules.setdefault("litert_torch", types.ModuleType("litert_torch"))
sys.argv = [sys.argv[0], REPO, CKPT, OUT, "none"]
spec = importlib.util.spec_from_file_location("conv", f"{HERE}/../efficientsam3-gpu/esam3_convert.py")
conv = importlib.util.module_from_spec(spec); spec.loader.exec_module(conv)
vb = conv.model.backbone.vision_backbone; enc = vb.trunk.model
px = {i: torch.from_numpy(np.fromfile(f"{DEV}/px{i}.bin", np.float32).reshape(1, 3, 1008, 1008)) for i in range(8)}
rel = lambda a, b: float(np.linalg.norm(a - b) / np.linalg.norm(b))
C1 = 1.5957691216057308; C3 = C1 * 0.044715


class TanhGELU(torch.nn.Module):
    def forward(self, x):   # one dependency chain (edgesam-tpu: the TPU compiler's op-order defect)
        return x * torch.sigmoid(x * (x * x * C3 + C1))


def set_gelu(tanh):
    n = 0
    for mod in vb.modules():
        for name, ch in mod.named_children():
            if isinstance(ch, (torch.nn.GELU, TanhGELU)):
                setattr(mod, name, TanhGELU() if tanh else torch.nn.GELU()); n += 1
    return n


if "gelu" in STEPS:
    n = set_gelu(True)
    feats = {i: conv.V(px[i]) for i in range(8)}
    worst = [max(rel(feats[i][k].numpy(), np.load(f"{DEV}/vref{i}.npz")[f"arr_{k}"]) for i in range(8)) for k in range(3)]
    print(f"gelu: {n} GELUs -> tanh chain; FPN rel L2 vs original, worst of 8 photos (288, 144, 72): {['%.1e' % w for w in worst]}", flush=True)
    od = f"{DEV}/e2e-tanh"; os.makedirs(od, exist_ok=True)
    for n_, rn in enumerate([f"gref{s}" for s in range(3)] + [f"wref{j}" for j in range(8)]):
        r = np.load(f"{DEV}/{rn}.npz"); i, q = int(r["photo"]), str(r["prompt"])
        ids = conv.ids_of(q); o = conv.G(*feats[i], conv.pos, conv.T(ids), (ids == 0).float())
        for k, x in enumerate(o): x.numpy().astype(np.float32).tofile(f"{od}/{n_}_o{k}.bin")
    set_gelu(False)

if "split" in STEPS:
    import litert_torch

    class Trunk(torch.nn.Module):
        def forward(self, x): return vb.trunk(x)[-1]

    class Neck(torch.nn.Module):
        def forward(self, x): return tuple(vb.convs[k](x) for k in range(3))   # scalp 1: the 36x36 level is discarded
    x72 = Trunk()(px[0])
    ref = conv.V(px[0])
    print("split stage 1: neck(trunk(px)) vs vision:", ["%.1e" % float((a - b).abs().max()) for a, b in zip(Neck()(x72), ref)], flush=True)
    for name, mod, arg in (("trunk", Trunk().eval(), px[0]), ("neck", Neck().eval(), x72)):
        edge = litert_torch.convert(mod, (arg,)); edge.export(f"{OUT}/esam3-rvm-vision-{name}-fp32.tflite")
        got = edge(arg); got = got if isinstance(got, (list, tuple)) else [got]
        want = mod(arg); want = want if isinstance(want, tuple) else (want,)
        print(f"split stage 2 {name}:", ["%.1e" % rel(np.asarray(a), b.numpy()) for a, b in zip(got, want)], flush=True)
    for i in (0, 3):
        Trunk()(px[i]).numpy().tofile(f"{OUT}/x72_{i}.bin")


class Blocks(torch.nn.Module):
    def __init__(self, n): super().__init__(); self.n = n
    def forward(self, x):
        for f in enc.backbone.model.features[:self.n]: x = f(x)
        return x


def fragment(f, mod, inp):
    """ONNX -> onnx2tf float32 TFLite; desktop check vs PyTorch; device inputs and references."""
    from ai_edge_litert.interpreter import Interpreter, OpResolverType
    fd = f"{OUT}/fp16tpu/{f}"; os.makedirs(fd, exist_ok=True); shutil.copy(SAMPLE, fd)   # else onnx2tf downloads it
    torch.onnx.export(mod, (inp[0],), f"{fd}/{f}.onnx", input_names=["x"], output_names=["y"], opset_version=17, dynamo=False)
    r = subprocess.run(["onnx2tf", "-i", f"{fd}/{f}.onnx", "-o", fd, "-n"], cwd=fd, capture_output=True, text=True)
    tfl = f"{fd}/{f}_float32.tflite"
    if not os.path.exists(tfl): print(r.stdout[-1500:], r.stderr[-1500:]); raise SystemExit(f"{f}: onnx2tf failed")
    it = Interpreter(model_path=tfl, experimental_op_resolver_type=OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES); it.allocate_tensors()
    ops = {}
    for d in it._get_ops_details(): ops[d["op_name"]] = ops.get(d["op_name"], 0) + 1
    worst, lines = 0.0, []
    for i in (0, 3):
        x = np.ascontiguousarray(inp[i].numpy().transpose(0, 2, 3, 1)); ref = mod(inp[i]).numpy().transpose(0, 2, 3, 1)
        x.tofile(f"{fd}/in{i}.bin"); np.save(f"{fd}/ref{i}.npy", ref); lines.append(f"/data/local/tmp/esam3-tpu/fp16tpu/{f}/in{i}.bin")
        it.set_tensor(it.get_input_details()[0]["index"], x); it.invoke()
        worst = max(worst, rel(it.get_tensor(it.get_output_details()[0]["index"]), ref))
    open(f"{fd}/inputs.txt", "w").write("\n".join(lines) + "\n")
    print(f, {"ops": sum(ops.values()), "by_op": ops, "MB": round(os.path.getsize(tfl) / 1e6, 1),
              "in": list(map(int, it.get_input_details()[0]["shape"])), "out": list(map(int, it.get_output_details()[0]["shape"])),
              "desktop_rel_l2_vs_pytorch": "%.1e" % worst}, flush=True)


if "frag" in STEPS or "bisect" in STEPS or "probe" in STEPS:
    set_gelu(True)
    for p in vb.parameters(): p.requires_grad_(False)   # the ONNX tracer refuses grad-requiring constants
c0 = vb.convs[0]


class N1(torch.nn.Module):
    def forward(self, x): return c0.conv_3x3(c0.conv_1x1(x))


if "frag" in STEPS or "probe" in STEPS:
    x72 = {i: vb.trunk(px[i])[-1] for i in (0, 3)}
    n1_in = {i: c0.dconv_2x2_1(c0.gelu(c0.dconv_2x2_0(x72[i]))) for i in (0, 3)}   # the original's tensor entering conv_1x1
if "frag" in STEPS:
    fragment("T1", Blocks(4).eval(), px)
    fragment("N1", N1().eval(), n1_in)
if "bisect" in STEPS:
    for n in (1, 2, 3):
        fragment(f"B{n - 1}", Blocks(n).eval(), px)
    fragment("T1K", Blocks(4).eval(), {i: torch.nn.functional.pad(px[i], (0, 16, 0, 16)) for i in (0, 3)})
if "probe" in STEPS:
    stem = {i: enc.backbone.model.features[0](px[i]) for i in (0, 3)}
    b1 = enc.backbone.model.features[1]
    fragment("PSE", b1.token_mixer[1].eval(), {i: b1.token_mixer[0](stem[i]) for i in (0, 3)})
    fragment("PDW", b1.token_mixer[0].eval(), stem)
    fragment("PCM", b1.channel_mixer.eval(), {i: b1.token_mixer(stem[i]) for i in (0, 3)})
    fragment("N1S", N1().eval(), {i: n1_in[i][:, :, 72:216, 72:216].contiguous() for i in (0, 3)})
