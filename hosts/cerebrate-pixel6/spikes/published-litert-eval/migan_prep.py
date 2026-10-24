"""MI-GAN 512 Places2 evaluation: eight photos with object-removal masks (the
top RF-DETR reference instance per photo, scaled to 512 and dilated), the
original fp32 generator (author-hosted migan.onnx) as reference, and a
desktop LiteRT CPU check of the published fp16 file."""
import sys, glob
import numpy as np
import onnxruntime as ort
from PIL import Image, ImageFilter
from ai_edge_litert.interpreter import Interpreter
P, RF, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
sess = ort.InferenceSession(sys.argv[4], providers=["CPUExecutionProvider"])  # generator subgraph extracted from the author-hosted migan.onnx (tensor 222 -> 1299)
print("original onnx inputs", [(i.name, i.shape, i.type) for i in sess.get_inputs()], "outputs", [(o.name, o.shape) for o in sess.get_outputs()], flush=True)
BP = "/Users/dev/Code/browser-perception/demos"
imgs = sorted(glob.glob(f"{BP}/object-selection/samples/*.jpg"))[:5] + sorted(glob.glob(f"{BP}/segmentation/samples/*.jpg"))[:3]
it = Interpreter(model_path=f"{P}/migan_fp16.tflite"); it.allocate_tensors()
print("published tflite input", it.get_input_details()[0]["shape"], "output", it.get_output_details()[0]["shape"], flush=True)
lines, refs, keeps, rgbs = [], [], [], []
def psnr_ssim(a, b, region):
    # a, b: [3,H,W] in [-1,1]; region: [H,W] bool (removed area)
    d = ((a - b) ** 2).mean(0)[region].mean(); psnr = 10 * np.log10(4.0 / max(d, 1e-12))
    return psnr
for i, p in enumerate(imgs):
    rgb = (np.asarray(Image.open(p).convert("RGB").resize((512, 512), Image.BICUBIC), np.float32) / 127.5 - 1).transpose(2, 0, 1)
    r = np.load(f"{RF}/ref{i}.npz"); score = 1 / (1 + np.exp(-r["logits"].max(-1))); cls = r["logits"].argmax(-1)
    q = int(np.argmax(np.where(cls > 0, score, -1)))
    m = Image.fromarray(((r["masks"][q] > 0) * 255).astype(np.uint8)).resize((512, 512), Image.NEAREST).filter(ImageFilter.MaxFilter(17))
    erase = np.asarray(m) > 127
    keep = (~erase).astype(np.float32)[None]
    x = np.concatenate([keep - 0.5, rgb * keep])[None].astype(np.float32)
    x.tofile(f"{OUT}/inputs/{i}.bin"); keep.tofile(f"{OUT}/inputs/keep{i}.bin"); lines.append(f"/data/local/tmp/migan/{i}.bin")
    ref = sess.run(None, {sess.get_inputs()[0].name: x})[0][0]
    refs.append(ref); keeps.append(keep[0]); rgbs.append(rgb)
    it.set_tensor(it.get_input_details()[0]["index"], x); it.invoke(); got = it.get_tensor(it.get_output_details()[0]["index"])[0]
    print(f"img{i}: erase {erase.mean() * 100:.1f}% of image | published fp16 desktop CPU vs original, masked-region PSNR {psnr_ssim(got, ref, erase):.1f} dB, rel L2 {np.linalg.norm(got - ref) / np.linalg.norm(ref):.3g}", flush=True)
np.save(f"{OUT}/reference.npy", np.stack(refs)); np.save(f"{OUT}/keep.npy", np.stack(keeps)); np.save(f"{OUT}/rgb.npy", np.stack(rgbs))
open(f"{OUT}/inputs.txt", "w").write("\n".join(lines) + "\n")
