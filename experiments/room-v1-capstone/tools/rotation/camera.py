"""Single-view camera for bedroom.jpg from two orthogonal floor vanishing points (back-wall and left-wall baseboards),
principal point at the image centre, square pixels. World: X along the back wall, Y along the left wall, Z up,
floor Z=0, camera height 1 (arbitrary unit; consistent for every object)."""
import numpy as np
LT = lambda x: -0.246 * x + 1997; LB = lambda x: -0.270 * x + 2090
BT = lambda x: 0.250 * x + 1158;  BB = lambda x: 0.268 * (x - 1691.0) + 1633
line = lambda f: np.cross([0.0, f(0.0), 1.0], [1000.0, f(1000.0), 1.0])
def _vp(a, b):
    p = np.cross(line(a), line(b)); return p[:2] / p[2]
VPB, VPL = _vp(BT, BB), _vp(LT, LB)
C = np.array([2000.0, 1500.0])
F = float(np.sqrt(-np.dot(VPB - C, VPL - C)))
K = np.array([[F, 0, C[0]], [0, F, C[1]], [0, 0, 1]])
Ki = np.linalg.inv(K)
r1 = Ki @ [*VPB, 1]; r1 /= np.linalg.norm(r1)
r2 = Ki @ [*VPL, 1]; r2 /= np.linalg.norm(r2)
r2 -= r1 * (r1 @ r2); r2 /= np.linalg.norm(r2)                    # exact orthogonality
r3 = np.cross(r1, r2)
if r3[1] > 0: r3 = -r3                                              # Z up = image up (camera y points down)
Rw = np.stack([r1, r2, r3], axis=1)                                 # world -> camera rotation (columns: world axes)
# camera centre at height 1 above the floor: camera-frame floor normal is r3; place origin so the floor is Z=0
CAM = np.array([0.0, 0.0, 1.0])                                     # camera position in world
def project(P):
    P = np.atleast_2d(P).astype(float)
    pc = (Rw @ (P - CAM).T)
    uv = K @ pc
    return (uv[:2] / uv[2]).T
def ray(u, v):
    d = Rw.T @ (Ki @ [u, v, 1.0]); return d / np.linalg.norm(d)
def floor_point(u, v):
    d = ray(u, v); t = -CAM[2] / d[2]; return CAM + t * d          # Z = 0
def height_above(floor_xyz, u_top, v_top):
    """Height of the point on the vertical through floor_xyz that projects nearest to (u_top, v_top)."""
    zs = np.linspace(0, 2.0, 4001)
    pts = project(np.c_[np.repeat(floor_xyz[None, :2], len(zs), 0), zs])
    return float(zs[np.argmin(np.hypot(pts[:, 0] - u_top, pts[:, 1] - v_top))])
def configure(vp_x, vp_y, centre):
    """Re-derive the camera for another photo: vanishing points of two perpendicular floor directions + image centre."""
    global VPB, VPL, C, F, K, Ki, Rw
    VPB, VPL, C = np.asarray(vp_x, float), np.asarray(vp_y, float), np.asarray(centre, float)
    F = float(np.sqrt(-np.dot(VPB - C, VPL - C)))
    K = np.array([[F, 0, C[0]], [0, F, C[1]], [0, 0, 1]]); Ki = np.linalg.inv(K)
    a = Ki @ [*VPB, 1]; a /= np.linalg.norm(a); b = Ki @ [*VPL, 1]; b /= np.linalg.norm(b)
    b -= a * (a @ b); b /= np.linalg.norm(b); z = np.cross(a, b)
    if z[1] > 0: z = -z
    Rw = np.stack([a, b, z], axis=1)
    return F

if __name__ == "__main__":
    print("VPs", VPB.round(), VPL.round(), "f", round(F), "HFOV deg", round(np.degrees(2 * np.arctan(2000 / F)), 1))
    print("r3 (world up in camera)", r3.round(3), "camera tilt deg", round(np.degrees(np.arcsin(-r3[2])), 1))
    vv = K @ r3; print("vertical VP", (vv[:2] / vv[2]).round())
    # checks: baseboard corner; door casing lean
    for name, (u, v) in {"corner floor (1691,1633)": (1691, 1633), "back-wall floor (3000,1984)": (3000, BB(3000))}.items():
        P = floor_point(u, v); print(name, "->", P.round(3), "reproj", project(P).round(1))
    P = floor_point(3505, 3000)                                      # casing bottom; where does the vertical through it go?
    for z in (0.5, 1.0, 1.5): print("vertical at casing, z", z, project([P[0], P[1], z]).round())
