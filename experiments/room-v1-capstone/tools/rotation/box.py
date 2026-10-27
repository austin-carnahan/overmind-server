"""Axis-aligned box on the floor (camera.py world), rotated 90 deg about its vertical axis: per visible target face,
the source quad (image), target quad (image) and the homography between them."""
import numpy as np
import camera as cam
project = lambda P: cam.project(P)
CAM = cam.CAM

def homography(src, dst):
    A = []
    for (x, y), (u, v) in zip(src, dst):
        A += [[x, y, 1, 0, 0, 0, -u * x, -u * y, -u], [0, 0, 0, x, y, 1, -v * x, -v * y, -v]]
    h = np.linalg.svd(np.array(A, float))[2][-1]; h = h / h[-1]
    c = np.mean(np.asarray(src, float), 0)            # GIMP clips points with w < 0 ("behind the camera"):
    if h[6] * c[0] + h[7] * c[1] + h[8] < 0:          # same projective map with the sign flipped keeps w > 0
        h = -h
    return h

class Box:
    """Corners in order A, B, C, D around the footprint (counter-clockwise from above); z from z0 to h."""
    def __init__(self, footprint, h, z0=0.0):
        self.F = np.array(footprint, float); self.h, self.z0 = h, z0
        self.c = self.F.mean(0)
    def face_corners(self, i, F=None):
        F = self.F if F is None else F
        a, b = F[i], F[(i + 1) % 4]
        return np.array([[*a, self.z0], [*b, self.z0], [*b, self.h], [*a, self.h]])     # bottom a, bottom b, top b, top a
    def visible(self, i, F=None):
        F = self.F if F is None else F
        a, b = F[i], F[(i + 1) % 4]; mid = (a + b) / 2; edge = b - a
        n = np.array([edge[1], -edge[0]])                    # outward for counter-clockwise order
        if n @ (mid - F.mean(0)) < 0: n = -n
        return n @ (CAM[:2] - mid) > 0
    def rotated(self, k=1, shift=(0, 0)):
        th = k * np.pi / 2; R = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
        return (self.F - self.c) @ R.T + self.c + np.array(shift)

def plan(box, k=1, shift=(0, 0)):
    """For each visible face of the rotated box: which source face supplies its texture (mirrored if that face was
    hidden: its opposite is used, flipped), and the image-space quads + homography."""
    G = box.rotated(k, shift); out = []
    for j in range(4):
        if not box.visible(j, G):
            continue
        src_i = j % 4                         # rotated face j carries original face j's texture
        mirror = False
        if not box.visible(src_i):
            src_i, mirror = (j + 2) % 4, True  # the opposite face, mirrored (symmetry assumption)
        S = project(box.face_corners(src_i)); T = project(box.face_corners(j, G))
        if mirror:
            S = S[[1, 0, 3, 2]]
        out.append({"face": j, "src_face": src_i, "mirrored": mirror, "src": S, "dst": T, "H": homography(S, T),
                    "depth": float(np.linalg.norm(box.face_corners(j, G).mean(0) - CAM))})
    top_s = project(np.c_[box.F, np.full(4, box.h)]); top_t = project(np.c_[G, np.full(4, box.h)])
    out.sort(key=lambda f: -f["depth"])
    return out, {"src": top_s, "dst": top_t, "H": homography(top_s, top_t)}, G
