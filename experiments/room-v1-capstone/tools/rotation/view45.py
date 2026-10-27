"""E13 v2 geometry for a GIMP-native view (no ray casting): every element is a layer moved by a 3x3 matrix or
placed as a sprite. Writes view45.json with matrices (source image -> new view), target quads and anchors."""
import json, sys
import numpy as np
import camera as cam
from scene import POLYS, X_LEFT, X_RIGHT, Y_BACK, CEIL_Z, ray_plane
from box import homography

THETA = float(sys.argv[1]) if len(sys.argv) > 1 else 45.0
P0 = np.array([1.9, 1.9, 0.0])
th = np.radians(THETA); Rz = np.array([[np.cos(th), -np.sin(th), 0], [np.sin(th), np.cos(th), 0], [0, 0, 1]])
CN = P0 + Rz @ (cam.CAM - P0)


def to_cam(X):
    X = np.atleast_2d(np.asarray(X, float)); Y = (X - P0) @ Rz + P0          # world -> old-camera frame of reference
    return (cam.Rw @ (Y - cam.CAM).T).T


def proj(X):
    pc = to_cam(X); uv = (cam.K @ pc.T).T; return uv[:, :2] / uv[:, 2:3]


def clip_world(poly, near=0.15):
    """Sutherland-Hodgman: keep the part of a world polygon with new-camera depth > near."""
    P = [np.asarray(p, float) for p in poly]; out = []
    d = [to_cam(p)[0, 2] - near for p in P]
    for i in range(len(P)):
        a, b, da, db = P[i], P[(i + 1) % len(P)], d[i], d[(i + 1) % len(P)]
        if da > 0: out.append(a)
        if (da > 0) != (db > 0): out.append(a + (b - a) * (da / (da - db)))
    return out


def norm_h(Hm, pts):
    Hm = Hm / Hm[2, 2]
    w = (Hm @ np.c_[pts, np.ones(len(pts))].T)[2]
    return Hm if np.median(w) > 0 else -Hm


def plane_entry(name, poly_img, plane):
    """Matrix photo -> new view for a room plane; the source polygon clipped to what stays in front of the camera."""
    W = [ray_plane(u, v, plane) for u, v in poly_img]
    Wc = clip_world(W)
    src = cam.project(np.array(Wc)); dst = proj(np.array(Wc))
    c = np.mean(poly_img, 0); ref = np.array([c + 0.5 * (np.array(p) - c) for p in poly_img[:4]])
    Wr = np.array([ray_plane(u, v, plane) for u, v in ref])
    Hm = norm_h(homography(ref, proj(Wr)).reshape(3, 3), ref)
    return {"name": name, "src_poly": src.round(1).tolist(), "dst_poly": dst.round(1).tolist(), "H": Hm.tolist()}


def quad(points3d):
    return proj(np.array(clip_world(points3d))).round(1).tolist()


out = {"theta": THETA, "camera": CN.round(3).tolist(), "planes": [], "paint": {}}
floor_poly = [(62, 2073), (1691, 1633), (3430, 2099), (3505, 3000), (430, 3000)]           # without the left door + knob
for name, poly, plane in (("ceiling", POLYS["ceiling"], "ceiling"), ("left wall", POLYS["left wall"], "left wall"),
                          ("back wall", POLYS["back wall"], "back wall"), ("floor", floor_poly, "floor")):
    out["planes"].append(plane_entry(name, poly, plane))
Y_NEAR = -2.0
out["paint"]["ceiling"] = quad([(X_LEFT, Y_BACK, CEIL_Z), (X_RIGHT, Y_BACK, CEIL_Z), (X_RIGHT, Y_NEAR, CEIL_Z), (X_LEFT, Y_NEAR, CEIL_Z)])
out["paint"]["floor"] = quad([(X_LEFT, Y_BACK, 0), (X_RIGHT, Y_BACK, 0), (X_RIGHT, Y_NEAR, 0), (X_LEFT, Y_NEAR, 0)])
out["paint"]["left wall"] = quad([(X_LEFT, Y_BACK, 0), (X_LEFT, Y_BACK, CEIL_Z), (X_LEFT, Y_NEAR, CEIL_Z), (X_LEFT, Y_NEAR, 0)])
out["paint"]["right wall"] = quad([(X_RIGHT, Y_BACK, 0), (X_RIGHT, Y_BACK, CEIL_Z), (X_RIGHT, Y_NEAR, CEIL_Z), (X_RIGHT, Y_NEAR, 0)])
HB = ray_plane(2500, 0.250 * 2500 + 1158, "back wall")[2]                                    # baseboard height (back wall)
out["paint"]["right baseboard"] = quad([(X_RIGHT, Y_BACK, 0), (X_RIGHT, Y_BACK, HB), (X_RIGHT, Y_NEAR, HB), (X_RIGHT, Y_NEAR, 0)])
out["baseboard_height"] = HB
# the door unit on the right wall: casing far edge at Y 1.33 (from its floor contact), standard proportions vs the ceiling
DY0, DY1, DZ = 0.87, 1.33, 0.99
door3d = [(X_RIGHT, DY1, DZ), (X_RIGHT, DY0, DZ), (X_RIGHT, DY1, 0.0), (X_RIGHT, DY0, 0.0)]         # UL UR LL LR as seen
out["door"] = {"quad": proj(np.array(door3d)).round(1).tolist(), "depth": to_cam(door3d)[:, 2].round(2).tolist()}

# furniture boxes: per visible face, photo quad -> new quad (hidden faces: opposite face, mirrored)
def box_faces(b, label):
    F = [(b["x0"], b["y0"]), (b["x1"], b["y0"]), (b["x1"], b["y1"]), (b["x0"], b["y1"])]
    c = np.array([(b["x0"] + b["x1"]) / 2, (b["y0"] + b["y1"]) / 2])
    faces = []
    def corners(i):
        a, bb = F[i], F[(i + 1) % 4]
        return np.array([[*a, b["z0"]], [*bb, b["z0"]], [*bb, b["z1"]], [*a, b["z1"]]])
    def visible(i, C):
        a, bb = np.array(F[i]), np.array(F[(i + 1) % 4]); mid = (a + bb) / 2; e = bb - a; n = np.array([e[1], -e[0]])
        if n @ (mid - c) < 0: n = -n
        return n @ (C[:2] - mid) > 0
    for i in range(4):
        if not visible(i, CN): continue
        si, mirror = i, False
        if not visible(i, cam.CAM): si, mirror = (i + 2) % 4, True
        S = cam.project(corners(si)); T = proj(corners(i))
        if mirror: S = S[[1, 0, 3, 2]]
        faces.append({"face": i, "src_face": si, "mirrored": mirror, "src": S.round(1).tolist(), "dst": T.round(1).tolist(),
                      "H": norm_h(homography(S, T).reshape(3, 3), S).tolist(), "depth": float(np.linalg.norm(corners(i).mean(0) - CN))})
    top = np.array([[*p, b["z1"]] for p in F]); S = cam.project(top); T = proj(top)
    faces.sort(key=lambda f: -f["depth"])
    return {"faces": faces, "top": {"src": S.round(1).tolist(), "dst": T.round(1).tolist(), "H": norm_h(homography(S, T).reshape(3, 3), S).tolist()},
            "depth": float(np.linalg.norm(np.array([*c, 0]) - CN))}

BED = dict(x0=1.664, x1=2.409, y0=1.52, y1=2.50, z0=0.0, z1=0.178)
NS = dict(x0=1.377, x1=1.579, y0=2.347, y1=2.522, z0=0.0, z1=0.308)
out["bed"] = box_faces(BED, "bed"); out["nightstand"] = box_faces(NS, "nightstand")


def sprite(base_uv, h):
    """An upright object anchored at a photo point on the plane z=h: new anchor and scale (depth ratio)."""
    d = cam.ray(*base_uv); t = (h - cam.CAM[2]) / d[2]; P = cam.CAM + t * d
    old = np.linalg.norm(P - cam.CAM); new = np.linalg.norm(P - CN)
    return {"anchor_old": list(base_uv), "anchor_new": proj(P)[0].round(1).tolist(), "scale": round(float(old / new), 4), "world": P.round(3).tolist(), "depth": float(new)}
out["sprites"] = {"pillow left": sprite((1816 - 300 + 300, 1600), BED["z1"]), "pillow right": sprite((1961, 1615), BED["z1"]),
                  "lamp": sprite((2220, 1548), NS["z1"]), "stool": sprite((2410, 1898), 0.0)}
json.dump(out, open(sys.argv[2] if len(sys.argv) > 2 else "view45.json", "w"), indent=1)
print("camera", out["camera"], "| door quad", out["door"]["quad"], "| depth", out["door"]["depth"])
print("bed faces", [(f["face"], f["src_face"], f["mirrored"]) for f in out["bed"]["faces"]], "| ns faces", [(f["face"], f["src_face"], f["mirrored"]) for f in out["nightstand"]["faces"]])
print("sprites", {k: (v["anchor_new"], v["scale"]) for k, v in out["sprites"].items()})
print("paint right wall", out["paint"]["right wall"])
