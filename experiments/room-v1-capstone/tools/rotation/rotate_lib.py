"""Shared: build a rotated/re-posed box object in GIMP from per-face homographies (rot/box.py) via MCP tools."""
import json, sys
import numpy as np
sys.path.insert(0, __import__("os").path.dirname(__file__))
from camera import project, ray, CAM
from box import plan

def grow(q, px):
    q = np.asarray(q, float); c = q.mean(0); v = q - c
    return c + v * (1 + px / np.linalg.norm(v, axis=1))[:, None]

def at_h(u, v, h):
    d = ray(u, v); t = (h - CAM[2]) / d[2]; return CAM + t * d

async def build(s, rid, src, box, k, shift, group_name, parent_pos, sprites=(), top_clip=40):
    faces, topf, G = plan(box, k, shift)
    g = (await s.pdb("gimp-group-layer-new", image=rid, name=group_name))[0]["id"]
    await s.pdb("gimp-image-insert-layer", image=rid, layer=g, position=parent_pos)
    await s.gimp("gimp_layer", action="set", layer_id=g, mode="pass-through")
    async def warp(name, sq, dq, Hm, clip):
        d = await s.gimp("gimp_layer", action="duplicate", layer_id=src); lid = d["id"]
        await s.gimp("gimp_layer", action="set", layer_id=lid, visible=True)
        await s.pdb("gimp-image-select-polygon", image=rid, operation="replace", segs=[float(c) for p in grow(sq, 3) for c in p])
        await s.gimp("gimp_layer_mask", layer_id=lid, action="add", type="selection")
        await s.gimp("gimp_layer_mask", layer_id=lid, action="apply")
        await s.gimp("gimp_layer", action="crop_to_content", layer_id=lid)
        await s.pdb("gimp-selection-none", image=rid)
        M = np.asarray(Hm).reshape(3, 3)
        lid = (await s.pdb("gimp-item-transform-matrix", item=lid, **{f"coeff-{r}-{c}": float(M[r][c]) for r in range(3) for c in range(3)}))[0]["id"]
        await s.pdb("gimp-image-select-polygon", image=rid, operation="replace", segs=[float(c) for p in grow(dq, clip) for c in p])
        await s.gimp("gimp_layer_mask", layer_id=lid, action="add", type="selection")
        await s.pdb("gimp-selection-none", image=rid)
        await s.gimp("gimp_layer", action="set", layer_id=lid, name=name)
        await s.gimp("gimp_layer", action="reorder", layer_id=lid, parent_id=g, position=0)
    for f in faces:
        await warp(f"Face {f['face']} <- source face {f['src_face']}{' (mirrored)' if f['mirrored'] else ''}", f["src"], f["dst"], f["H"], 4)
    await warp("Top (rotated)", topf["src"], topf["dst"], topf["H"], top_clip)
    c0, R = box.c, None
    th = k * np.pi / 2; Rm = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
    for sp in sprites:                     # {"layer": id, "dx": 0, "base_frac": 0.95, "flip": True}
        info = await s.gimp("gimp_layer", action="info", layer_id=sp["layer"])
        x0, y0, w, h = info["x"] + sp.get("dx", 0), info["y"], info["width"], info["height"]
        base = np.array([x0 + w / 2, y0 + h * sp.get("base_frac", 0.95)])
        P = at_h(*base, box.h); Q = Rm @ (P[:2] - c0) + c0 + np.array(shift)
        nb = project([*Q, box.h])[0]
        sc = np.ptp(project([[*Q, box.h], [*Q, box.h + 0.05]])[:, 1]) / np.ptp(project([[*P[:2], box.h], [*P[:2], box.h + 0.05]])[:, 1])
        d = await s.gimp("gimp_layer", action="duplicate", layer_id=sp["layer"]); lid = d["id"]
        await s.gimp("gimp_layer", action="reorder", layer_id=lid, parent_id=g, position=0)
        await s.gimp("gimp_layer", action="set", layer_id=lid, visible=True, name=sp.get("name", "sprite"))
        if sp.get("flip", True):
            await s.pdb("gimp-item-transform-flip-simple", item=lid, **{"flip-type": "horizontal", "auto-center": True, "axis": 0.0})
        nw, nh = round(w * sc), round(h * sc)
        await s.gimp("gimp_layer", action="scale", layer_id=lid, width=nw, height=nh)
        await s.gimp("gimp_layer", action="set", layer_id=lid, x=round(nb[0] - nw / 2), y=round(nb[1] - nh * sp.get("base_frac", 0.95)))
    fp = project(np.c_[G, np.zeros(4)])
    L = await s.gimp("gimp_layer", action="new", image_id=rid, name="Contact shadow (rotated footprint)", width=4000, height=3000, fill="transparent", x=0, y=0)
    sh = L["id"] if "id" in L else L["layer_id"]
    n = len((await s.gimp("gimp_layer", action="info", layer_id=g)).get("children", [])) if False else 99
    await s.gimp("gimp_layer", action="reorder", layer_id=sh, parent_id=g, position=len(faces) + 1 + len(sprites))
    await s.pdb("gimp-image-select-polygon", image=rid, operation="replace", segs=[float(c) for p in grow(fp, 6) for c in p])
    await s.gimp("gimp_draw", action="fill_selection", image_id=rid, layer_id=sh, color="#000000")
    await s.pdb("gimp-selection-none", image=rid)
    await s.gimp("gimp_apply_filter", layer_id=sh, op="gegl:gaussian-blur", params={"std-dev-x": 8, "std-dev-y": 6}, mode="merge")
    await s.gimp("gimp_layer", action="set", layer_id=sh, mode="multiply", opacity=60.0)
    return g, faces, G
