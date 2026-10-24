"""MI-GAN infill vs the original fp32 generator, judged only inside the
removed region of the composited result (outside it the composite is the
original photo by construction): PSNR, SSIM (local SSIM map averaged over
the removed region, on 8-bit RGB), and relative L2."""
import sys
import numpy as np
from skimage.metrics import structural_similarity
D = sys.argv[1]; configs = sys.argv[2:]
ref = np.load(f"{D}/reference.npy"); keep = np.load(f"{D}/keep.npy"); rgb = np.load(f"{D}/rgb.npy"); n = len(ref)
def comp(out, i): return rgb[i] * keep[i] + out * (1 - keep[i])
def to8(x): return ((x.transpose(1, 2, 0) + 1) * 127.5).clip(0, 255).astype(np.uint8)
print(f"{'config':14} {'PSNR min (dB)':>13} {'PSNR mean':>9} {'SSIM min':>8} {'SSIM mean':>9} {'rel L2 max':>10}")
for c in configs:
    ps, ss, rl = [], [], []
    for i in range(n):
        g = np.fromfile(f"{D}/pulled/out-{c}/{i}_o0.bin", np.float32).reshape(3, 512, 512)
        a, b = comp(g, i), comp(ref[i], i); region = keep[i] < 0.5
        mse = ((a - b) ** 2).mean(0)[region].mean(); ps.append(10 * np.log10(4.0 / max(mse, 1e-12)))
        _, smap = structural_similarity(to8(a), to8(b), channel_axis=2, full=True, data_range=255)
        ss.append(smap.mean(2)[region].mean())
        rl.append(np.linalg.norm((a - b)[:, region]) / np.linalg.norm(b[:, region]))
    print(f"{c:14} {min(ps):13.1f} {np.mean(ps):9.1f} {min(ss):8.4f} {np.mean(ss):9.4f} {max(rl):10.3g}")
