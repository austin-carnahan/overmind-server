"""E08 wall-art geometry as a standalone computation (no GIMP, no MCP): an agent runs it, then applies the printed
corners with gimp-item-transform-perspective through GIMP MCP.

Input (JSON): the window trim's four image corners (TL, TR, BR, BL), the camera's focal length and principal point,
and the art's placement in the trim's rectified units (u0, v0, width) with the print's aspect ratio.
Output (JSON on stdout): the trim's true aspect (metric rectification), the angle between its recovered edge
directions (a sanity check: ~90 deg for a real rectangle), the homography, and the art's corners in GIMP's order
(x0,y0 top-left, x1,y1 top-right, x2,y2 bottom-left, x3,y3 bottom-right). OpenCV recomputes the homography as a check.

    python e08_wall_art.py inputs.json > result.json
"""
import json, sys
import numpy as np
import cv2


def vanishing_point(a, b, c, d):
    """Intersection of line a-b with line c-d (homogeneous)."""
    l1 = np.cross([*a, 1.0], [*b, 1.0]); l2 = np.cross([*c, 1.0], [*d, 1.0])
    p = np.cross(l1, l2); return p[:2] / p[2]


def homography(src, dst):
    A = []
    for (x, y), (u, v) in zip(src, dst):
        A += [[x, y, 1, 0, 0, 0, -u * x, -u * y, -u], [0, 0, 0, x, y, 1, -v * x, -v * y, -v]]
    h = np.linalg.svd(np.array(A, float))[2][-1]
    return (h / h[-1]).reshape(3, 3)


def main(inp):
    TL, TR, BR, BL = (np.array(p, float) for p in inp["trim_corners"])
    f, c = float(inp["focal_px"]), np.array(inp["principal_point"], float)
    Kinv = np.linalg.inv(np.array([[f, 0, c[0]], [0, f, c[1]], [0, 0, 1]]))
    # metric rectification: the rectangle's edge directions in 3D are K^-1 times its two vanishing points
    vh = vanishing_point(TL, TR, BL, BR); vv = vanishing_point(TL, BL, TR, BR)
    dh = Kinv @ [*vh, 1.0]; dh /= np.linalg.norm(dh); dv = Kinv @ [*vv, 1.0]; dv /= np.linalg.norm(dv)
    angle = float(np.degrees(np.arccos(abs(dh @ dv))))
    n = np.cross(dh, dv); n /= np.linalg.norm(n)                       # plane normal (camera frame)
    ray = lambda p: Kinv @ [*p, 1.0]
    on_plane = lambda p: ray(p) / (n @ ray(p))                         # the plane n.X = 1 (scale cancels in a ratio)
    P = {k: on_plane(p) for k, p in (("TL", TL), ("TR", TR), ("BR", BR), ("BL", BL))}
    width = (np.linalg.norm(P["TR"] - P["TL"]) + np.linalg.norm(P["BR"] - P["BL"])) / 2
    height = (np.linalg.norm(P["BL"] - P["TL"]) + np.linalg.norm(P["BR"] - P["TR"])) / 2
    aspect = float(width / height)
    if "aspect_override" in inp:                                       # reproduce a recorded run exactly
        aspect = float(inp["aspect_override"])
    # rectified trim coordinates: u in [0, aspect], v in [0, 1]
    src = np.array([(0, 0), (aspect, 0), (aspect, 1), (0, 1)], float)
    dst = np.array([TL, TR, BR, BL], float)
    H = homography(src, dst)
    H_cv = cv2.getPerspectiveTransform(src.astype(np.float32), dst.astype(np.float32))
    a = inp["art"]; u0, v0, w = a["u0"], a["v0"], a["width"]; h = w / a["ratio"]
    def map_(u, v):
        p = H @ [u, v, 1.0]; return (p[:2] / p[2]).tolist()
    corners = [map_(u0, v0), map_(u0 + w, v0), map_(u0, v0 + h), map_(u0 + w, v0 + h)]
    return {"trim_aspect_measured": round(float(width / height), 4), "trim_aspect_used": round(aspect, 4),
            "edge_angle_deg": round(angle, 2), "H": H.round(6).tolist(),
            "H_opencv_max_abs_diff": float(np.abs(H / H[2, 2] - H_cv / H_cv[2, 2]).max()),
            "art_corners": [[round(x, 1) for x in p] for p in corners],
            "gimp_transform_perspective": {f"{k}{i}": round(p[j], 1) for i, p in enumerate(corners) for j, k in enumerate("xy")},
            "versions": {"python": sys.version.split()[0], "numpy": np.__version__, "opencv": cv2.__version__}}


if __name__ == "__main__":
    print(json.dumps(main(json.load(open(sys.argv[1]))), indent=1))
