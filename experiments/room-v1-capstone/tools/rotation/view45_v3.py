"""E13 v3 geometry: the photo's camera re-derived from floor+ceiling vanishing lines (consistent ceiling height),
a new camera turned 45 deg about the room centre and kept inside the room, and per-plane photo->view matrices whose
source polygons are clipped in 3D (shared edges by construction). Writes view.json; matrices/quads only."""
import json, sys
import numpy as np
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
import camera as cam
from box import homography

OLD = {"K": cam.K.copy(), "Rw": cam.Rw.copy()}              # v1/v2 camera: only to carry v2's hand-fitted furniture over
def old_project(P):
    P = np.atleast_2d(P); uv = (OLD["K"] @ (OLD["Rw"] @ (P - cam.CAM).T)).T; return uv[:, :2] / uv[:, 2:3]

F = cam.configure((2, 1180), (3327, 1192), (2000, 1500))     # back: ceiling x floor line; left: ceiling x floor line
K, R0, C0 = cam.K, cam.Rw, cam.CAM
corner = cam.floor_point(1692, 1633)
XL, YB = corner[0], corner[1]
XR = cam.floor_point(3430, 2099)[0]
CEIL = 1.695                                                 # 1.685-1.703 measured along both ceiling lines
YN = -0.15                                                   # near wall (camera stands in its doorway)
W_, H_ = 4000, 3000

# new camera: view turned 45 deg (toward the right wall), standing inside the room near the near wall
YAW = np.radians(float(sys.argv[1]) if len(sys.argv) > 1 else 45.0)
C1 = np.array([float(sys.argv[2]) if len(sys.argv) > 2 else 1.15, float(sys.argv[3]) if len(sys.argv) > 3 else 0.0, 1.0])
Rz = lambda a: np.array([[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0], [0, 0, 1]])
R1 = R0 @ Rz(YAW)


def proj(P, R=R1, C=C1):
    P = np.atleast_2d(np.asarray(P, float)); pc = (R @ (P - C).T).T; uv = (K @ pc.T).T; return uv[:, :2] / uv[:, 2:3]


def depth(P, R=R1, C=C1):
    return (R @ (np.atleast_2d(P) - C).T).T[:, 2]


def frustum(R, C, margin=0.0, near=0.12):
    """Half-space functions (>0 inside) for a camera's view: near plane + the four image edges (margin in pixels)."""
    fs = [lambda P: depth(P, R, C) - near]
    for (a, b) in (((-margin, -margin), (-margin, H_ + margin)), ((-margin, H_ + margin), (W_ + margin, H_ + margin)),
                   ((W_ + margin, H_ + margin), (W_ + margin, -margin)), ((W_ + margin, -margin), (-margin, -margin))):
        ra = R.T @ np.linalg.inv(K) @ [*a, 1]; rb = R.T @ np.linalg.inv(K) @ [*b, 1]; n = np.cross(ra, rb)
        fs.append(lambda P, n=n, C=C: (np.atleast_2d(P) - C) @ n)
    return fs


def clip(poly, f):
    P = [np.asarray(p, float) for p in poly]; out = []
    for i in range(len(P)):
        a, b = P[i], P[(i + 1) % len(P)]; da, db = float(f(a)[0]), float(f(b)[0])
        if da > 0: out.append(a)
        if (da > 0) != (db > 0): out.append(a + (b - a) * (da / (da - db)))
    return out


def clip_all(poly, fs):
    for f in fs:
        poly = clip(poly, f)
        if len(poly) < 3: return []
    return poly


PLANES = {   # 3D rectangles (counter-clockwise doesn't matter)
    "floor": [(XR, YN, 0), (XL, YN, 0), (XL, YB, 0), (XR, YB, 0)],
    "ceiling": [(XR, YN, CEIL), (XL, YN, CEIL), (XL, YB, CEIL), (XR, YB, CEIL)],
    "left wall": [(XL, YN, 0), (XL, YB, 0), (XL, YB, CEIL), (XL, YN, CEIL)],
    "back wall": [(XL, YB, 0), (XR, YB, 0), (XR, YB, CEIL), (XL, YB, CEIL)],
    "right wall": [(XR, YB, 0), (XR, YN, 0), (XR, YN, CEIL), (XR, YB, CEIL)],
}
OLD_F, NEW_F = frustum(R0, C0, margin=0), frustum(R1, C1, margin=150)


def plane_matrix(P3):
    """photo -> view for the plane through these 3D points (exact for a plane), sign-normalised for w > 0."""
    P3 = np.asarray(P3, float); c = P3.mean(0); pts = c + 0.5 * (P3[:4] - c)
    src, dst = cam.project(pts), proj(pts)
    return homography(src, dst).reshape(3, 3)


out = {"camera_photo": {"f": F, "R": R0.tolist(), "C": C0.tolist()}, "camera_view": {"yaw_deg": float(np.degrees(YAW)), "C": C1.tolist()},
       "room": {"XL": XL, "XR": XR, "YB": YB, "YN": YN, "CEIL": CEIL}, "planes": {}}
for name, rect in PLANES.items():
    view = clip_all(rect, NEW_F)                                  # what of the plane this view sees
    seen = clip_all(view, OLD_F) if view else []                  # ... and the photo saw too
    out["planes"][name] = {"view_poly": proj(np.array(view)).round(1).tolist() if view else [],
                           "src_poly": cam.project(np.array(seen)).round(1).tolist() if seen else [],
                           "dst_poly": proj(np.array(seen)).round(1).tolist() if seen else [],
                           "H": plane_matrix(rect).tolist()}

# wireframe: the room's 12 edges, clipped to the view
E = [((XR, YB, 0), (XL, YB, 0)), ((XR, YB, CEIL), (XL, YB, CEIL)), ((XL, YB, 0), (XL, YB, CEIL)), ((XR, YB, 0), (XR, YB, CEIL)),
     ((XL, YN, 0), (XL, YB, 0)), ((XR, YN, 0), (XR, YB, 0)), ((XL, YN, CEIL), (XL, YB, CEIL)), ((XR, YN, CEIL), (XR, YB, CEIL))]
wire = []
for a, b in E:
    a, b = np.array(a, float), np.array(b, float); da, db = depth(a)[0] - 0.12, depth(b)[0] - 0.12
    if da <= 0 and db <= 0: continue
    if da <= 0: a = a + (b - a) * (da / (da - db))
    if db <= 0: b = b + (a - b) * (db / (db - da))
    wire.append(proj(np.array([a, b])).round(1).tolist())
out["wireframe"] = wire

# closet door on the right wall: outer casing from Y 1.58 (floor contact of the near casing) to the corner, head 1.43
DY0, DY1 = 1.58, YB - 0.03
door = [(XR, DY0, 1.43), (XR, DY1, 1.43), (XR, DY0, 0.0), (XR, DY1, 0.0)]       # UL UR LL LR as seen from the room
out["door"] = {"quad": proj(np.array(door)).round(1).tolist(), "world": door, "opening_top": 1.31}
# baseboard: the back wall's photographed baseboard band, mapped along the right wall
HB = 0.115
bb_src3 = [(1.2, YB, 0), (0.2, YB, 0), (0.2, YB, HB), (1.2, YB, HB)]
out["baseboard"] = {"height": HB, "src": cam.project(np.array(bb_src3)).round(1).tolist(), "segments": []}
for y0, y1 in ((YN, DY0), ):
    seg3 = [(XR, y1, 0), (XR, y0, 0), (XR, y0, HB), (XR, y1, HB)]
    seg = clip_all(seg3, NEW_F)                                    # bounded: only what lands in (or near) the frame
    if seg:
        Hs = homography(cam.project(np.array(bb_src3)), proj(np.array(seg3))).reshape(3, 3)
        dst = proj(np.array(seg)); Hi = np.linalg.inv(Hs); s_ = (Hi @ np.c_[dst, np.ones(len(dst))].T).T
        out["baseboard"]["segments"].append({"dst": dst.round(1).tolist(), "src": (s_[:, :2] / s_[:, 2:3]).round(1).tolist(), "H": Hs.tolist()})

# furniture: v2's boxes (fitted to the photo with the old camera) carried over through their image corners
def carry_box(b):
    foot = np.array([(b["x0"], b["y0"], 0), (b["x1"], b["y0"], 0), (b["x1"], b["y1"], 0), (b["x0"], b["y1"], 0)])
    uv = old_project(foot); new_foot = np.array([cam.floor_point(*p) for p in uv])
    top_uv = old_project(foot + [0, 0, b["z1"]])
    hs = [cam.height_above(f, *t) for f, t in zip(new_foot, top_uv)]
    return new_foot[:, :2], float(np.median(hs))
BED = dict(x0=1.664, x1=2.409, y0=1.52, y1=2.50, z0=0.0, z1=0.178)
NS = dict(x0=1.377, x1=1.579, y0=2.347, y1=2.522, z0=0.0, z1=0.308)


def box_faces(foot, h):
    c = foot.mean(0); faces = []
    def corners(i):
        a, b = foot[i], foot[(i + 1) % 4]; return np.array([[*a, 0], [*b, 0], [*b, h], [*a, h]])
    def visible(i, C):
        a, b = foot[i], foot[(i + 1) % 4]; mid = (a + b) / 2; e = b - a; n = np.array([e[1], -e[0]])
        if n @ (mid - c) < 0: n = -n
        return n @ (C[:2] - mid) > 0
    for i in range(4):
        if not visible(i, C1): continue
        si, mirror = i, False
        if not visible(i, C0): si, mirror = (i + 2) % 4, True
        S = cam.project(corners(si)); T = proj(corners(i))
        if mirror: S = S[[1, 0, 3, 2]]
        Cc = corners(i).mean(0); a, b = foot[i], foot[(i + 1) % 4]; e = b - a; n = np.array([e[1], -e[0], 0.0]) / np.linalg.norm(e)
        if n[:2] @ (Cc[:2] - [*c]) < 0: n = -n
        v = C1 - Cc; facing = float(n @ v / np.linalg.norm(v))          # cos of the viewing angle: ~0 = edge-on
        faces.append({"face": i, "src_face": si, "mirrored": mirror, "facing": round(facing, 3), "src": S.round(1).tolist(), "dst": T.round(1).tolist(),
                      "H": homography(S, T).reshape(3, 3).tolist(), "depth": float(np.linalg.norm(corners(i).mean(0) - C1))})
    top = np.array([[*p, h] for p in foot]); S = cam.project(top); T = proj(top)
    faces.sort(key=lambda f: -f["depth"])
    return {"foot": foot.round(3).tolist(), "h": h, "faces": faces, "shadow": proj(np.array([[*p, 0] for p in foot])).round(1).tolist(),
            "top": {"src": S.round(1).tolist(), "dst": T.round(1).tolist(), "H": homography(S, T).reshape(3, 3).tolist()},
            "depth": float(np.linalg.norm(np.array([*c, 0]) - C1))}


bf, bh = carry_box(BED); nf, nh = carry_box(NS)
out["bed"] = box_faces(bf, bh); out["nightstand"] = box_faces(nf, nh)


def sprite(uv, z):
    d = cam.ray(*uv); t = (z - C0[2]) / d[2]; P = C0 + t * d
    return {"anchor_old": list(uv), "anchor_new": proj(P)[0].round(1).tolist(), "scale": round(float(np.linalg.norm(P - C0) / np.linalg.norm(P - C1)), 4),
            "world": P.round(3).tolist(), "depth": float(np.linalg.norm(P - C1))}
out["sprites"] = {"pillow left": sprite((1816, 1600), bh), "pillow right": sprite((1961, 1615), bh), "lamp": sprite((2220, 1548), nh),
                  "stool": sprite((2410, 1898), 0.0), "fan": sprite((1675, 405), CEIL)}
json.dump(out, open(sys.argv[4] if len(sys.argv) > 4 else "view.json", "w"), indent=1)
print("f", round(F), "room X", round(XR, 3), round(XL, 3), "Y", YN, round(YB, 3), "ceil", CEIL, "| cam", C1, "yaw", np.degrees(YAW))
print("bed foot", bf.round(2).tolist(), "h", round(bh, 3), "| ns", nf.round(2).tolist(), round(nh, 3))
print("sprites", {k: (v["anchor_new"], v["scale"]) for k, v in out["sprites"].items()})
print("door quad", out["door"]["quad"])
for k, p in out["planes"].items(): print(k, "view", len(p["view_poly"]), "src", len(p["src_poly"]))
