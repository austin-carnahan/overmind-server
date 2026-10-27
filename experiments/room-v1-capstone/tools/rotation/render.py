"""E13: ray-cast a nearby viewpoint of the bedroom from the single photo (2.5D).

Scene (camera.py world, camera at (0,0,1)): five room planes, box furniture (bed, nightstand) and upright
billboards (lamp, stool). Each new-view pixel's ray hits the nearest surface; its colour comes from the original
photo (or a background texture) at that surface point's original projection -- valid only if that point was
visible in the original view on that surface. Everything else is a hole (alpha 0).

Outputs one RGBA layer per element so GIMP keeps the scene editable.
  render.py <out_dir> <theta_deg> <method A|B|C> <room_texture.png> <photo.npy> <masks.npz>
"""
import sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
import camera as cam
from scene import POLYS, X_LEFT, X_RIGHT, Y_BACK, CEIL_Z

W, H = 4000, 3000
PIVOT = np.array([1.9, 1.9, 0.0])
BED = dict(x0=1.664, x1=2.409, y0=1.52, y1=2.50, z0=0.0, z1=0.178)
NS = dict(x0=1.377, x1=1.579, y0=2.347, y1=2.522, z0=0.0, z1=0.308)


def poly_mask(poly):
    im = Image.new("L", (W, H), 0); ImageDraw.Draw(im).polygon([tuple(p) for p in poly], fill=1)
    return np.asarray(im, bool)


def sample(img, uv, valid):
    """Bilinear sample of img at original-image coordinates uv (N,2); valid (N,) also requires uv inside."""
    u, v = uv[:, 0], uv[:, 1]
    inside = valid & (u >= 0) & (u < W - 1) & (v >= 0) & (v < H - 1)
    out = np.zeros((len(u), img.shape[2]), np.float32)
    ui, vi = u[inside], v[inside]
    x0, y0 = np.floor(ui).astype(int), np.floor(vi).astype(int); fx, fy = (ui - x0)[:, None], (vi - y0)[:, None]
    I = img.astype(np.float32)
    out[inside] = (I[y0, x0] * (1 - fx) * (1 - fy) + I[y0, x0 + 1] * fx * (1 - fy) +
                   I[y0 + 1, x0] * (1 - fx) * fy + I[y0 + 1, x0 + 1] * fx * fy)
    return out, inside


def lookup(maskimg, uv):
    u = np.clip(np.round(uv[:, 0]).astype(int), 0, W - 1); v = np.clip(np.round(uv[:, 1]).astype(int), 0, H - 1)
    ok = (uv[:, 0] >= 0) & (uv[:, 0] < W) & (uv[:, 1] >= 0) & (uv[:, 1] < H)
    return maskimg[v, u] & ok


def render(theta, method, room_tex, photo, masks, out_dir, step=1):
    th = np.radians(theta); Rz = np.array([[np.cos(th), -np.sin(th), 0], [np.sin(th), np.cos(th), 0], [0, 0, 1]])
    Cn = PIVOT + Rz @ (cam.CAM - PIVOT)
    vs, us = np.mgrid[0:H:step, 0:W:step]; uu, vv = us.ravel().astype(float), vs.ravel().astype(float)
    d_old = (cam.Rw.T @ (cam.Ki @ np.stack([uu, vv, np.ones_like(uu)]))).T          # old-camera ray directions
    D = d_old @ Rz.T; D /= np.linalg.norm(D, axis=1, keepdims=True)
    N = len(uu); best_t = np.full(N, np.inf); owner = np.full(N, -1)
    layers = {}                                                                       # name -> (rgba (N,4), hit mask)

    def consider(name, t, P, src_img, src_valid_mask, extra_ok=None):
        nonlocal best_t, owner
        ok = np.isfinite(t) & (t > 1e-3)
        if extra_ok is not None: ok &= extra_ok
        uv = cam.project(P)
        ok &= lookup(src_valid_mask, uv)
        col, inside = sample(src_img, uv, ok)
        ok &= inside
        layers[name] = (col, ok, t)

    def plane_t(axis, value):
        with np.errstate(divide="ignore", invalid="ignore"):
            return (value - Cn[axis]) / D[:, axis]

    # room planes; their original-view validity = inside their polygon in the photo
    planes = {"floor": (2, 0.0), "ceiling": (2, CEIL_Z), "left wall": (0, X_LEFT), "right wall": (0, X_RIGHT), "back wall": (1, Y_BACK)}
    for name, (axis, val) in planes.items():
        t = plane_t(axis, val); P = Cn + t[:, None] * D
        valid = poly_mask(POLYS[name])
        if name in ("floor", "back wall", "left wall") and method != "C":
            pass
        consider(name, t, P, room_tex, valid)
    if method in ("B", "C"):
        # boxes: each face rectangle; texture from the photo where the face was visible originally (not mirrored)
        for label, b in (("bed", BED), ("nightstand", NS)):
            faces = {"x0": (0, b["x0"]), "x1": (0, b["x1"]), "y0": (1, b["y0"]), "y1": (1, b["y1"]), "top": (2, b["z1"])}
            for fname, (axis, val) in faces.items():
                t = plane_t(axis, val); P = Cn + t[:, None] * D
                inr = np.ones(N, bool)
                for ax, lo, hi in ((0, b["x0"], b["x1"]), (1, b["y0"], b["y1"]), (2, b["z0"], b["z1"])):
                    if ax != axis: inr &= (P[:, ax] >= lo - 1e-6) & (P[:, ax] <= hi + 1e-6)
                # was this face visible in the original view? (its outward normal faces the original camera)
                c = np.array([(b["x0"] + b["x1"]) / 2, (b["y0"] + b["y1"]) / 2, (b["z0"] + b["z1"]) / 2])
                fc = c.copy(); fc[axis] = val; n = np.zeros(3); n[axis] = np.sign(val - c[axis])
                vis_orig = n @ (cam.CAM - fc) > 0
                src_valid = np.ones((H, W), bool) if vis_orig else np.zeros((H, W), bool)
                consider(f"{label}:{fname}", t, P, photo, src_valid, inr)
        # billboards: vertical planes facing the original camera through a base point
        for label, base_uv, mask in (("lamp", (2220.0, 1548.0), masks["lamp"]), ("stool", (2410.0, 1898.0), masks["stool"])):
            if label == "lamp":
                B = cam.floor_point(*base_uv); d = cam.ray(*base_uv); tt = (NS["z1"] - cam.CAM[2]) / d[2]; B = cam.CAM + tt * d
            else:
                B = cam.floor_point(*base_uv)
            nrm = cam.CAM - B; nrm[2] = 0; nrm /= np.linalg.norm(nrm)
            with np.errstate(divide="ignore", invalid="ignore"):
                t = ((B - Cn) @ nrm) / (D @ nrm)
            P = Cn + t[:, None] * D
            consider(label, t, P, photo, mask)
    # nearest valid hit wins; a box face or billboard occludes even where its texture is invalid
    order = list(layers)
    T = np.stack([np.where(layers[n][1], layers[n][2], np.inf) for n in order])
    win = np.argmin(T, 0); anyhit = np.isfinite(T.min(0))
    # occlusion by solid objects even without texture: a ray that hits a box inside its rectangle is blocked
    groups = {}
    for i, n in enumerate(order):
        g = n.split(":")[0] if ":" in n else ("room" if n in planes else n)
        groups.setdefault(g, []).append(i)
    out_dir.mkdir(parents=True, exist_ok=True)
    stats = {}
    for g, idx in groups.items():
        rgba = np.zeros((N, 4), np.uint8)
        for i in idx:
            sel = anyhit & (win == i)
            rgba[sel, :3] = np.clip(layers[order[i]][0][sel], 0, 255).astype(np.uint8); rgba[sel, 3] = 255
        Image.fromarray(rgba.reshape(len(range(0, H, step)), len(range(0, W, step)), 4), "RGBA").save(out_dir / f"{g.replace(' ', '-')}.png")
        stats[g] = int((rgba[:, 3] > 0).sum())
    stats["holes"] = int((~anyhit).sum()); stats["pixels"] = N; stats["camera"] = Cn.round(3).tolist()
    return stats


if __name__ == "__main__":
    out, theta, method = Path(sys.argv[1]), float(sys.argv[2]), sys.argv[3]
    room = np.asarray(Image.open(sys.argv[4]).convert("RGB"))
    photo = np.load(sys.argv[5])
    m = np.load(sys.argv[6])
    st = render(theta, method, room, photo, {k: m[k] for k in m.files}, out, step=int(sys.argv[7]) if len(sys.argv) > 7 else 1)
    print(st)
