"""Exact x2 bicubic upsampling (PyTorch semantics: half-pixel coordinates,
A = -0.75, indices clamped at the border) from TPU-friendly ops: replicate
padding by 2, four 5x5 depthwise "phase" convolutions (one per output
row/column parity), channel concat in phase-major order, DepthToSpace
(DCR, block 2). NNAPI has no bicubic resize.
Output row 2i samples source row i - 0.25 (taps i-2..i+1, t = 0.75); row
2i+1 samples i + 0.25 (taps i-1..i+2, t = 0.25). Same for columns."""
import numpy as np

A = -0.75


def cubic_weights(t):
    """Weights of taps floor-1 .. floor+2 for fractional offset t."""
    def near(x): return ((A + 2) * x - (A + 3)) * x * x + 1
    def far(x): return ((A * x - 5 * A) * x + 8 * A) * x - 4 * A
    return np.array([far(t + 1), near(t), near(1 - t), far(2 - t)])


def phase_kernels():
    """1-D 5-tap kernels over padded taps i-2..i+2: [even, odd]."""
    even = np.concatenate([cubic_weights(0.75), [0.0]])
    odd = np.concatenate([[0.0], cubic_weights(0.25)])
    return even, odd


def phase_kernels_2d():
    """[(row phase, col phase) -> 5x5 kernel] in DCR order (0,0),(0,1),(1,0),(1,1)."""
    k = phase_kernels()
    return [np.outer(k[i], k[j]) for i in (0, 1) for j in (0, 1)]


if __name__ == "__main__":
    import torch, torch.nn.functional as F
    torch.manual_seed(0)
    x = torch.randn(1, 8, 32, 32, dtype=torch.float64) * 3
    ref = F.interpolate(x, scale_factor=2, mode="bicubic", align_corners=False)
    xp = F.pad(x, (2, 2, 2, 2), mode="replicate")
    C = x.shape[1]
    phases = [F.conv2d(xp, torch.tensor(k).expand(C, 1, 5, 5), groups=C) for k in phase_kernels_2d()]
    out = F.pixel_shuffle(torch.stack(phases, 2).reshape(1, C * 4, 32, 32), 2)  # CRD of (c, phase) == DCR of (phase, c)
    print("max |diff| vs F.interpolate bicubic (float64):", float((out - ref).abs().max()))
