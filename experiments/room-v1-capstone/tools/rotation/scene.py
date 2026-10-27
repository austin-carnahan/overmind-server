"""Bedroom as 2.5D planes for the original camera (camera.py) and an orbited camera: plane polygons (image), plane
equations (world), and per-plane homographies original -> new view."""
import numpy as np
import camera as cam
from box import homography
LT = lambda x: -0.246 * x + 1997; LB = lambda x: -0.270 * x + 2090
BT = lambda x: 0.250 * x + 1158;  BB = lambda x: 0.268 * (x - 1691.0) + 1633
CEIL_Z = 1.16
X_LEFT = cam.floor_point(1691, 1633)[0]                 # left wall plane X = const
Y_BACK = cam.floor_point(1691, 1633)[1]                 # back wall plane Y = const
X_RIGHT = cam.floor_point(3430, BB(3430))[0]            # right wall (parallel to the left wall)
POLYS = {  # image polygons of each surface (original view)
    "ceiling": [(0, 0), (3960, 0), (3725, 423), (1691, 848), (0, 515)],
    "left wall": [(0, 515), (1691, 848), (1691, 1633), (0, 2090)],
    "back wall": [(1691, 848), (3725, 423), (3430, 2099), (1691, 1633)],
    "right wall": [(3725, 423), (3960, 0), (4000, 0), (4000, 3000), (3505, 3000), (3430, 2099)],
    "floor": [(0, 2090), (1691, 1633), (3430, 2099), (3505, 3000), (0, 3000)],
}
def ray_plane(u, v, plane):
    d = cam.ray(u, v); C = cam.CAM
    if plane == "floor": t = -C[2] / d[2]
    elif plane == "ceiling": t = (CEIL_Z - C[2]) / d[2]
    elif plane == "left wall": t = (X_LEFT - C[0]) / d[0]
    elif plane == "right wall": t = (X_RIGHT - C[0]) / d[0]
    else: t = (Y_BACK - C[1]) / d[1]
    return C + t * d
def orbit(theta_deg, pivot):
    """New-view projection: rotate the world by -theta about a vertical axis through pivot, view with the old camera."""
    th = np.radians(-theta_deg); R = np.array([[np.cos(th), -np.sin(th), 0], [np.sin(th), np.cos(th), 0], [0, 0, 1]])
    P0 = np.asarray(pivot, float)
    return lambda X: cam.project((np.atleast_2d(X) - P0) @ R.T + P0)
def plane_homography(plane, proj_new):
    poly = np.array(POLYS[plane], float); c = poly.mean(0)
    src = [c + 0.6 * (p - c) for p in poly[:4]] if len(poly) >= 4 else poly
    src = np.array(src); W = np.array([ray_plane(u, v, plane) for u, v in src])
    dst = proj_new(W)
    return homography(src, dst).reshape(3, 3)
