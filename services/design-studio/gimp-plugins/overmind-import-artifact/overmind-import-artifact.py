#!/usr/bin/env python3
"""GIMP 3 plug-in: the GIMP end of Overmind's artifact transport. Publish
what the document currently looks like for Cerebrate to work on, import
results (e.g. inpaint patches) as layers, and keep each object's repairs in
the object's own layer group.

Five PDB procedures, called by agents through the GIMP MCP's gimp_pdb_call:

  overmind-publish(image, mode, x, y, width, height, format, name)
      -> snapshot, image-url, mask-url, x, y, width, height
      Upload the visible composite (what the canvas shows; hidden layers
      excluded) of a region, and the selection over it as a mask, to the
      artifact service; Cerebrate tools take the URLs as inputs.
      - mode "selection": the window an inpainting model needs around the
        selection (>= 512 px, twice its extent; photo_postprocess.inpaint_window)
      - mode "image": the whole canvas (results then use document coordinates)
      - mode "region": x, y, width, height
      The snapshot's provenance (its region and a hash of its pixels) stays in
      the document; results computed from it are imported with snapshot=.

  overmind-make-object-group(image, layer, name) -> group
      The layer's object group: its parent group if it is already in one,
      else a new group around it (same place in the stack, same look). Call it
      right after cutting an object out, while the cutout still lines up with
      the photo: the group records an *anchor* (which member is the original
      and where it sat), so later patches, whose offsets are in the photo's
      pixels, land where the object is now.

  overmind-seamless-blend(image, patch, background, margin, op-id) -> report
      Poisson-blend a patch layer, or every visible layer of a patch group, into
      the background drawable's surroundings (GEGL seamless-clone): the patch's
      own texture, the surroundings' light and colour at its edge. Writes the
      blended colour back into each patch layer (their outlines unchanged).
      Works only on the patch's bounding box plus margin, in the plug-in's
      own buffers: the whole canvas took minutes and timed the bridge out.

  overmind-op-status(image, op-id) -> status, details
      What became of an operation started with an op-id: "done" (and its
      result), "started" (not finished: it may have failed, or still be
      running), or "unknown". For when a call's response was lost.

  overmind-import-artifact(image, url, x, y, name, target, group-name, context-url, snapshot, force, op-id)
      -> layer, group
      Fetch the image at url and add it as a layer.
      - No target: a new top layer at (x, y), image coordinates.
      - target (a layer or a group): into that object's group, never nesting
        (a group: at its top; a layer: right above it; a layer not in a
        group gets one, named group-name), at (x, y) in the photo's pixels
        plus however far the group has moved since its anchor was recorded.
      - context-url (Cerebrate's inpaint `context`: the photo's pixels around
        the fill): compared with what the target shows at the placement spot
        first; a mismatch means a misplaced or stale patch, and the import is
        refused unless force. The check has to see enough of the ring.
      - snapshot (a result computed from overmind-publish's snapshot): (x, y)
        are in the snapshot's coordinates. The document must still show
        exactly what was published there -- the region is re-rendered and its
        hash compared -- or the import is refused (publish a new snapshot)
        unless force: an optimistic concurrency check, so a fill computed
        before someone edited that area is never silently applied.
      One undo step. Returns the new layer and its group.

Operation ids: overmind-seamless-blend and overmind-import-artifact take an
op-id (any string). Its progress is journalled in the document (parasite
overmind-ops): run again with the same op-id after an operation finished, it
returns the recorded result instead of repeating the work, so a retry after a
lost response can't duplicate layers. An agent whose call's outcome is
unknown asks overmind-op-status first, and never blindly re-runs.

Why fetching here: GIMP's own file loading can't use a URL on macOS (the MCP
bridge turns file arguments into local paths; GIO has no http backend), and
agents should pass references, not pixels -- services/cerebrate-mcp/README.md,
"GIMP handoff". Fetches are limited to the artifact service (allowed URL
prefixes), no redirects, a size cap, and PNG/JPEG/WebP only. Publishing
needs this host's upload token (create-only; services/cerebrate-mcp,
"Uploads"). Settings go in overmind-import-artifact.json next to this file
(0600 -- it holds the token):
  {"allowed_prefixes": ["http://artifacts.home.arpa/artifacts/"], "max_bytes": 67108864,
   "upload_url": "http://artifacts.home.arpa/artifacts/upload", "token": "<host>.<secret>"}
"""
import hashlib
import json
import math
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

import gi

gi.require_version("Gimp", "3.0")
gi.require_version("Gegl", "0.4")
from gi.repository import Gegl, Gimp, Gio, GLib, GObject  # noqa: E402

IMPORT, GROUP, PUBLISH = "overmind-import-artifact", "overmind-make-object-group", "overmind-publish"
BLEND, STATUS, OPS, KEEP_OPS = "overmind-seamless-blend", "overmind-op-status", "overmind-ops", 50
ANCHOR, SNAPSHOTS, KEEP_SNAPSHOTS = "overmind-object-anchor", "overmind-snapshots", 20
DEFAULTS = {"allowed_prefixes": ["http://artifacts.home.arpa/artifacts/"], "max_bytes": 64 * 1024 * 1024,
            "upload_url": "http://artifacts.home.arpa/artifacts/upload", "token": ""}
SIGNATURES = ((b"\x89PNG\r\n\x1a\n", ".png"), (b"\xff\xd8\xff", ".jpg"), (b"RIFF", ".webp"))
# Context check: per pixel, the largest channel difference; the ring "matches"
# when the mean is small and few pixels differ a lot. Decoder differences
# (GIMP vs. the server's JPEG decode) stay well under these.
MEAN_MAX, OUTLIER_DIFF, OUTLIER_FRAC, MIN_PIXELS = 6.0, 40, 0.02, 50
CONTEXT_PX = 6   # Cerebrate's inpaint context margin (services/cerebrate-mcp contracts.CONTEXT_PX)


class Refused(Exception):
    """An import the caller must fix (or force)."""


def config():
    cfg = dict(DEFAULTS)
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), IMPORT + ".json")
    if os.path.exists(path):
        with open(path) as f:
            cfg.update(json.load(f))
    return cfg


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "redirects are not followed", headers, fp)


def fetch(url, cfg):
    """The image bytes and a file suffix, or Refused saying why not."""
    if urlsplit(url).scheme not in ("http", "https") or not any(url.startswith(p) for p in cfg["allowed_prefixes"]):
        raise Refused(f"URL not allowed (allowed prefixes: {cfg['allowed_prefixes']})")
    opener = urllib.request.build_opener(_NoRedirect)
    with opener.open(urllib.request.Request(url, headers={"User-Agent": IMPORT}), timeout=60) as r:
        data = r.read(cfg["max_bytes"] + 1)
    if len(data) > cfg["max_bytes"]:
        raise Refused(f"larger than {cfg['max_bytes']} bytes")
    for sig, suffix in SIGNATURES:
        if data.startswith(sig) and (suffix != ".webp" or data[8:12] == b"WEBP"):
            return data, suffix
    raise Refused("not a PNG, JPEG or WebP image")


def load_layer(image, url, cfg, tmps):
    data, suffix = fetch(url, cfg)
    fd, tmp = tempfile.mkstemp(prefix="overmind-artifact-", suffix=suffix)
    tmps.append(tmp)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    layer = Gimp.file_load_layer(Gimp.RunMode.NONINTERACTIVE, image, Gio.File.new_for_path(tmp))
    if layer is None:
        raise Refused(f"GIMP could not load {os.path.basename(urlsplit(url).path)}")
    return layer


def rgba(drawable, x, y, w, h):
    """Pixels of a drawable (a group: its projection) over an image-space rect."""
    ox, oy = drawable.get_offsets()[1:]
    return drawable.get_buffer().get(Gegl.Rectangle.new(x - ox, y - oy, w, h), 1.0, "R'G'B'A u8", Gegl.AbyssPolicy.NONE)


# ---- object groups --------------------------------------------------------------
def anchor_of(group):
    p = group.get_parasite(ANCHOR) if group is not None else None
    return json.loads(bytes(p.get_data())) if p is not None else None


def stamp_anchor(group, layer):
    x, y = layer.get_offsets()[1:]
    data = json.dumps({"tattoo": layer.get_tattoo(), "x": x, "y": y, "w": layer.get_width(), "h": layer.get_height()})
    group.attach_parasite(Gimp.Parasite.new(ANCHOR, Gimp.PARASITE_PERSISTENT | Gimp.PARASITE_UNDOABLE, list(data.encode())))


def existing_group(target):
    """The object group a target belongs to, if any: itself if a group, else its parent group."""
    if target.is_group():
        return target
    return target.get_parent()


def make_group(image, layer, name):
    """A new group around a top-level-or-ungrouped layer, in its place, with its anchor.
    The group takes the object's name; a layer of the same name becomes
    "<name> (original)" (GIMP keeps layer names unique, and would otherwise
    rename the group "<name> #1")."""
    parent = layer.get_parent()
    name = name or layer.get_name()
    if layer.get_name() == name:
        layer.set_name(f"{name} (original)")
    group = Gimp.GroupLayer.new(image, name)
    image.insert_layer(group, parent, image.get_item_position(layer))
    image.reorder_item(layer, group, 0)
    stamp_anchor(group, layer)
    return group


def displacement(image, group):
    """How far the group's anchored original has moved since the anchor was
    recorded: (dx, dy), or Refused if it was resized/transformed (a patch's
    photo offsets no longer map by a translation)."""
    a = anchor_of(group)
    if a is None:
        return 0, 0
    member = image.get_layer_by_tattoo(a["tattoo"])
    if member is None:
        return 0, 0                      # original removed: no translation; the context check decides
    if (member.get_width(), member.get_height()) != (a["w"], a["h"]):
        raise Refused(f"group '{group.get_name()}' was scaled or transformed since its anchor was recorded; "
                      "photo offsets can't be mapped onto it (re-run inpainting on its current pixels, or force)")
    x, y = member.get_offsets()[1:]
    return x - a["x"], y - a["y"]


def check_context(image, drawable, ctx_layer, x, y):
    """Compare the photo's pixels around the fill with what drawable shows at (x, y)."""
    w, h = ctx_layer.get_width(), ctx_layer.get_height()
    ref = rgba(ctx_layer, *ctx_layer.get_offsets()[1:], w, h)
    cur = rgba(drawable, x, y, w, h)
    n = total = outliers = 0
    for i in range(0, len(ref), 4):
        if ref[i + 3] == 255 and cur[i + 3] == 255:
            d = max(abs(ref[i] - cur[i]), abs(ref[i + 1] - cur[i + 1]), abs(ref[i + 2] - cur[i + 2]))
            n += 1
            total += d
            outliers += d > OUTLIER_DIFF
    if n < MIN_PIXELS:
        raise Refused(f"can't verify placement: only {n} context pixels overlap '{drawable.get_name()}' at ({x}, {y})")
    mean, frac = total / n, outliers / n
    if mean > MEAN_MAX or frac > OUTLIER_FRAC:
        raise Refused(f"context mismatch at ({x}, {y}) on '{drawable.get_name()}': mean difference {mean:.1f}, "
                      f"{frac:.1%} of {n} pixels differ by > {OUTLIER_DIFF} -- the patch would be misplaced, or was "
                      "computed from pixels that have changed since (force to place it anyway)")
    return {"pixels": n, "mean": round(mean, 2), "outliers": round(frac, 4)}


# ---- snapshots ------------------------------------------------------------------------
def inpaint_window(size, bbox, side_min=512, context=2.0):
    """photo_postprocess.inpaint_window's rule (services/cerebrate-mcp): a
    square of at least side_min and context x the selection's extent, centred
    on it, clamped to the canvas."""
    w, h = size
    x0, y0, x1, y1 = bbox
    side = max(side_min, math.ceil(context * max(x1 - x0, y1 - y0)))
    ww, wh = min(side, w), min(side, h)
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    wx = min(max(cx - ww // 2, 0), w - ww)
    wy = min(max(cy - wh // 2, 0), h - wh)
    return wx, wy, ww, wh


def visible_rgba(image, x, y, w, h):
    """The visible composite over an image-space rect: what the canvas shows."""
    vis = Gimp.Layer.new_from_visible(image, image, "overmind-snapshot")
    try:
        return bytes(rgba(vis, x, y, w, h))
    finally:
        vis.delete()


def selection_gray(image, x, y, w, h):
    sel = image.get_selection()
    return bytes(sel.get_buffer().get(Gegl.Rectangle.new(x, y, w, h), 1.0, "Y u8", Gegl.AbyssPolicy.NONE))


def encode(data, w, h, gray, fmt, tmps):
    """Raw pixels -> PNG/JPEG bytes, through a temporary GIMP image."""
    img = Gimp.Image.new(w, h, Gimp.ImageBaseType.GRAY if gray else Gimp.ImageBaseType.RGB)
    try:
        lay = Gimp.Layer.new(img, "x", w, h, Gimp.ImageType.GRAY_IMAGE if gray else Gimp.ImageType.RGBA_IMAGE, 100,
                             Gimp.LayerMode.NORMAL)
        img.insert_layer(lay, None, 0)
        buf = lay.get_buffer()
        buf.set(Gegl.Rectangle.new(0, 0, w, h), "Y u8" if gray else "R'G'B'A u8", data)
        buf.flush()
        fd, tmp = tempfile.mkstemp(prefix="overmind-publish-", suffix=".png" if gray or fmt == "png" else ".jpg")
        os.close(fd)
        tmps.append(tmp)
        if not Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, img, Gio.File.new_for_path(tmp), None):
            raise Refused("GIMP could not encode the snapshot")
        with open(tmp, "rb") as f:
            return f.read()
    finally:
        img.delete()


def upload(data, name, cfg):
    if not cfg.get("token"):
        raise Refused("no upload token configured (overmind-import-artifact.json)")
    req = urllib.request.Request(f"{cfg['upload_url']}?name={name}", data=data, method="POST",
                                 headers={"Authorization": f"Bearer {cfg['token']}", "User-Agent": PUBLISH,
                                          "Content-Type": "application/octet-stream"})
    try:
        with urllib.request.build_opener(_NoRedirect).open(req, timeout=120) as r:
            return json.load(r)
    except urllib.error.HTTPError as exc:
        raise Refused(f"upload refused: HTTP {exc.code} {exc.read().decode(errors='replace').strip()}") from exc


def snapshots(image):
    p = image.get_parasite(SNAPSHOTS)
    return json.loads(bytes(p.get_data())) if p is not None else {}


def remember(image, snap_id, entry):
    d = snapshots(image)
    d[snap_id] = entry
    for k in sorted(d, key=lambda k: d[k]["t"])[:-KEEP_SNAPSHOTS]:
        del d[k]
    image.attach_parasite(Gimp.Parasite.new(SNAPSHOTS, Gimp.PARASITE_PERSISTENT, list(json.dumps(d).encode())))


def snapshot_hash(image, x, y, w, h):
    return hashlib.sha256(visible_rgba(image, x, y, w, h)).hexdigest()


# ---- operation journal ----------------------------------------------------------------
def ops(image):
    p = image.get_parasite(OPS)
    return json.loads(bytes(p.get_data())) if p is not None else {}


def journal(image, op_id, **entry):
    if not op_id:
        return
    d = ops(image)
    d[op_id] = {**d.get(op_id, {}), **entry, "t": time.time()}
    for k in sorted(d, key=lambda k: d[k]["t"])[:-KEEP_OPS]:
        del d[k]
    image.attach_parasite(Gimp.Parasite.new(OPS, Gimp.PARASITE_PERSISTENT, list(json.dumps(d).encode())))


def finished(image, op_id):
    """The recorded result of an op-id that already completed, else None."""
    e = ops(image).get(op_id) if op_id else None
    return e["result"] if e and e.get("status") == "done" else None


def by_tattoo(image, tattoo):
    return image.get_layer_by_tattoo(tattoo) if tattoo else None


# ---- seamless blend --------------------------------------------------------------------
def leaves(item):
    if item.is_group():
        return [x for ch in item.get_children() for x in leaves(ch)]
    return [item] if item.get_visible() else []


def blend(image, patch, background, margin):
    """Poisson-blend the patch's layers into the background over their bounding box + margin."""
    members = leaves(patch)
    if not members:
        raise Refused("the patch has no visible layers")
    W, H = image.get_width(), image.get_height()
    boxes = [(m.get_offsets()[1], m.get_offsets()[2], m.get_width(), m.get_height()) for m in members]
    rx0 = max(min(x for x, y, w, h in boxes) - margin, 0)
    ry0 = max(min(y for x, y, w, h in boxes) - margin, 0)
    rx1 = min(max(x + w for x, y, w, h in boxes) + margin, W)
    ry1 = min(max(y + h for x, y, w, h in boxes) + margin, H)
    rw, rh = rx1 - rx0, ry1 - ry0
    Gimp.progress_init("Blending into the surroundings")
    t = [time.time()]
    tmp = Gimp.Image.new(rw, rh, Gimp.ImageBaseType.RGB)
    try:
        for m in members:
            lay = Gimp.Layer.new_from_drawable(m, tmp)
            tmp.insert_layer(lay, None, 0)
            lay.set_offsets(m.get_offsets()[1] - rx0, m.get_offsets()[2] - ry0)
        merged = tmp.merge_visible_layers(Gimp.MergeType.CLIP_TO_IMAGE)
        aux_px = bytes(rgba(merged, 0, 0, rw, rh))
    finally:
        tmp.delete()
    t.append(time.time())
    bg_px = bytes(rgba(background, rx0, ry0, rw, rh))
    Gimp.progress_update(0.2)
    # GEGL graphs in a plug-in need GEGL initialised in this process: without it, building the graph
    # segfaults the plug-in (and GIMP then hangs waiting on it -- the freezes of 2026-10-26).
    Gegl.init(None)
    t.append(time.time())
    rect = Gegl.Rectangle.new(0, 0, rw, rh)
    in_buf, aux_buf, out_buf = (Gegl.Buffer.new("R'G'B'A u8", 0, 0, rw, rh) for _ in range(3))
    in_buf.set(rect, "R'G'B'A u8", bg_px)
    aux_buf.set(rect, "R'G'B'A u8", aux_px)
    graph = Gegl.Node.new()
    src = graph.create_child("gegl:buffer-source")
    src.set_property("buffer", in_buf)
    aux = graph.create_child("gegl:buffer-source")
    aux.set_property("buffer", aux_buf)
    sc = graph.create_child("gegl:seamless-clone")
    src.connect_to("output", sc, "input")
    aux.connect_to("output", sc, "aux")
    wr = graph.create_child("gegl:write-buffer")
    wr.set_property("buffer", out_buf)
    sc.connect_to("output", wr, "input")
    wr.process()
    t.append(time.time())
    if sc.get_property("error-msg"):
        raise Refused(f"seamless clone: {sc.get_property('error-msg')}")
    out = bytes(out_buf.get(rect, 1.0, "R'G'B'A u8", Gegl.AbyssPolicy.NONE))
    Gimp.progress_update(0.8)
    image.undo_group_start()
    try:
        for m in members:
            mx, my = m.get_offsets()[1] - rx0, m.get_offsets()[2] - ry0
            w, h = m.get_width(), m.get_height()
            healed = b"".join(out[((my + r) * rw + mx) * 4:((my + r) * rw + mx + w) * 4] for r in range(h))
            mine = bytearray(m.get_buffer().get(Gegl.Rectangle.new(0, 0, w, h), 1.0, "R'G'B'A u8", Gegl.AbyssPolicy.NONE))
            for ch in range(3):
                mine[ch::4] = healed[ch::4]                       # blended colour, the layer's own outline
            buf = m.get_buffer()
            buf.set(Gegl.Rectangle.new(0, 0, w, h), "R'G'B'A u8", bytes(mine))
            buf.flush()
            m.update(0, 0, w, h)
    finally:
        image.undo_group_end()
    Gimp.progress_update(1.0)
    t.append(time.time())
    stages = ("patch", "background", "blend", "write")
    return {"layers": len(members), "region": [rx0, ry0, rw, rh],
            "stage_s": {k: round(b - a, 1) for k, a, b in zip(stages, t, t[1:])}}


# ---- procedures -----------------------------------------------------------------------
def _error(procedure, name, exc):
    return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR,
                                       GLib.Error.new_literal(GLib.quark_from_string(name), f"{name}: {exc}", 1))


def run_group(procedure, config_, data):
    image, layer, name = config_.get_property("image"), config_.get_property("layer"), config_.get_property("name")
    try:
        image.undo_group_start()
        try:
            group = existing_group(layer) if (layer.is_group() or layer.get_parent() is not None) else None
            if group is None:
                group = make_group(image, layer, name)
            else:
                if anchor_of(group) is None and not layer.is_group():
                    stamp_anchor(group, layer)
                if name:
                    group.set_name(name)
        finally:
            image.undo_group_end()
        Gimp.displays_flush()
    except Exception as exc:
        return _error(procedure, GROUP, exc)
    return Gimp.ValueArray.new_from_values([GObject.Value(Gimp.PDBStatusType, Gimp.PDBStatusType.SUCCESS),
                                            GObject.Value(Gimp.GroupLayer, group)])


def run_publish(procedure, config_, data):
    get = config_.get_property
    image, mode, fmt = get("image"), (get("mode") or "selection").lower(), (get("format") or "png").lower()
    cfg, tmps = config(), []
    try:
        W, H = image.get_width(), image.get_height()
        ok, nonempty, sx0, sy0, sx1, sy1 = Gimp.Selection.bounds(image)
        if mode == "selection":
            if not nonempty:
                raise Refused("mode selection: the selection is empty")
            x, y, w, h = inpaint_window((W, H), (sx0, sy0, sx1, sy1))
        elif mode == "image":
            x, y, w, h = 0, 0, W, H
        elif mode == "region":
            x, y, w, h = get("x"), get("y"), get("width"), get("height")
            if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > W or y + h > H:
                raise Refused(f"region {x},{y} {w}x{h} isn't inside the {W}x{H} canvas")
        else:
            raise Refused("mode: selection, image or region")
        if fmt not in ("png", "jpeg"):
            raise Refused("format: png or jpeg")
        pixels = visible_rgba(image, x, y, w, h)
        name = (get("name") or "snapshot").lower()
        img_ref = upload(encode(pixels, w, h, False, fmt, tmps), name, cfg)
        mask_url = ""
        if nonempty:
            mask_url = upload(encode(selection_gray(image, x, y, w, h), w, h, True, "png", tmps), name + "-mask", cfg)["url"]
        snap_id = img_ref["uri"].split("/")[2]                     # its upload run: unique
        remember(image, snap_id, {"x": x, "y": y, "w": w, "h": h, "sha256": hashlib.sha256(pixels).hexdigest(),
                                  "t": __import__("time").time()})
    except Exception as exc:
        return _error(procedure, PUBLISH, exc)
    finally:
        for t in tmps:
            if os.path.exists(t):
                os.unlink(t)
    return Gimp.ValueArray.new_from_values([
        GObject.Value(Gimp.PDBStatusType, Gimp.PDBStatusType.SUCCESS),
        GObject.Value(GObject.TYPE_STRING, snap_id), GObject.Value(GObject.TYPE_STRING, img_ref["url"]),
        GObject.Value(GObject.TYPE_STRING, mask_url),
        GObject.Value(GObject.TYPE_INT, x), GObject.Value(GObject.TYPE_INT, y),
        GObject.Value(GObject.TYPE_INT, w), GObject.Value(GObject.TYPE_INT, h)])


def run_blend(procedure, config_, data):
    get = config_.get_property
    image, patch, background, op_id = get("image"), get("patch"), get("background"), get("op-id")
    try:
        report = finished(image, op_id)
        if report is None:
            journal(image, op_id, proc=BLEND, status="started")
            t0 = time.time()
            report = {**blend(image, patch, background, get("margin")), "seconds": round(time.time() - t0, 1)}
            journal(image, op_id, status="done", result=report)
        Gimp.displays_flush()
    except Exception as exc:
        journal(image, op_id, status="failed", error=str(exc)[:300])
        return _error(procedure, BLEND, exc)
    return Gimp.ValueArray.new_from_values([GObject.Value(Gimp.PDBStatusType, Gimp.PDBStatusType.SUCCESS),
                                            GObject.Value(GObject.TYPE_STRING, json.dumps(report))])


def run_status(procedure, config_, data):
    image, op_id = config_.get_property("image"), config_.get_property("op-id")
    e = ops(image).get(op_id)
    status = e.get("status", "unknown") if e else "unknown"
    details = {k: v for k, v in (e or {}).items() if k != "status"}
    if e:
        details["age_s"] = round(time.time() - e["t"])
    return Gimp.ValueArray.new_from_values([GObject.Value(Gimp.PDBStatusType, Gimp.PDBStatusType.SUCCESS),
                                            GObject.Value(GObject.TYPE_STRING, status),
                                            GObject.Value(GObject.TYPE_STRING, json.dumps(details))])


def run_import(procedure, config_, data):
    get = config_.get_property
    image, url, x, y = get("image"), get("url"), get("x"), get("y")
    target, force, ctx_url, snap_id = get("target"), get("force"), get("context-url"), get("snapshot")
    name = get("name") or os.path.basename(urlsplit(url).path) or "artifact"
    op_id = get("op-id")
    cfg, tmps = config(), []
    try:
        done = finished(image, op_id)
        if done:                                                        # a retry after a lost response
            return Gimp.ValueArray.new_from_values([
                GObject.Value(Gimp.PDBStatusType, Gimp.PDBStatusType.SUCCESS),
                GObject.Value(Gimp.Layer, by_tattoo(image, done["layer"])),
                GObject.Value(Gimp.GroupLayer, by_tattoo(image, done.get("group")))])
        journal(image, op_id, proc=IMPORT, status="started", url=url)
        group = existing_group(target) if target is not None and (target.is_group() or target.get_parent() is not None) else None
        dx, dy = (0, 0)
        if snap_id:
            snap = snapshots(image).get(snap_id)
            if snap is None:
                raise Refused(f"snapshot {snap_id} isn't one of this document's (publish it from this image)")
            dx, dy = snap["x"], snap["y"]                           # snapshot coordinates -> document
            if not force and snapshot_hash(image, snap["x"], snap["y"], snap["w"], snap["h"]) != snap["sha256"]:
                raise Refused(f"the document changed in snapshot {snap_id}'s region since it was published; "
                              "publish a new snapshot and run again (or force)")
        elif group is not None:
            try:
                dx, dy = displacement(image, group)
            except Refused:
                if not force:
                    raise
        px, py = x + dx, y + dy
        image.undo_group_start()
        try:
            if target is not None and ctx_url and not force and not snap_id:
                ctx_layer = load_layer(image, ctx_url, cfg, tmps)   # loaded, never inserted
                try:
                    # the ring starts CONTEXT_PX before the patch, less where the photo's edge clipped it
                    check_context(image, group or target, ctx_layer, px - min(CONTEXT_PX, x), py - min(CONTEXT_PX, y))
                finally:
                    ctx_layer.delete()
            layer = load_layer(image, url, cfg, tmps)
            if target is None:
                image.insert_layer(layer, None, 0)
            else:
                if group is None:
                    group = make_group(image, target, get("group-name"))
                pos = 0 if target.is_group() else image.get_item_position(target)
                image.insert_layer(layer, group, pos)
            layer.set_offsets(px, py)
            layer.set_name(name)
        finally:
            image.undo_group_end()
        journal(image, op_id, status="done", result={"layer": layer.get_tattoo(), "group": group.get_tattoo() if group else None})
        Gimp.displays_flush()
    except Exception as exc:  # every failure goes back to the caller as a PDB error
        journal(image, op_id, status="failed", error=str(exc)[:300])
        return _error(procedure, IMPORT, exc)
    finally:
        for t in tmps:
            if os.path.exists(t):
                os.unlink(t)
    return Gimp.ValueArray.new_from_values([GObject.Value(Gimp.PDBStatusType, Gimp.PDBStatusType.SUCCESS),
                                            GObject.Value(Gimp.Layer, layer),
                                            GObject.Value(Gimp.GroupLayer, group)])


class OvermindArtifacts(Gimp.PlugIn):
    def do_set_i18n(self, name):
        return False

    def do_query_procedures(self):
        return [IMPORT, GROUP, PUBLISH, BLEND, STATUS]

    def do_create_procedure(self, name):
        rw = GObject.ParamFlags.READWRITE
        if name == IMPORT:
            procedure = Gimp.Procedure.new(self, name, Gimp.PDBProcType.PLUGIN, run_import, None)
            procedure.set_documentation(
                "Add an image from Overmind's artifact service as a layer, optionally into an object's group",
                "Fetches url (artifact service only, no redirects, size-capped, PNG/JPEG/WebP). Without target: a new "
                "top layer at (x, y). With target (a layer or group): into that object's group (created around a "
                "lone layer), above the target, at (x, y) in photo pixels plus the group's movement since its anchor; "
                "with context-url, the photo's pixels around the fill must match the target there, or the import is "
                "refused unless force. One undo step. Returns the layer and its group.", name)
        elif name == PUBLISH:
            procedure = Gimp.Procedure.new(self, name, Gimp.PDBProcType.PLUGIN, run_publish, None)
            procedure.set_documentation(
                "Publish what the canvas shows (a region, and the selection as a mask) to Overmind's artifact service",
                "Uploads the visible composite of the selection's inpainting window (mode selection), the whole canvas "
                "(image) or x/y/width/height (region), and the selection over it as a mask, with this host's upload "
                "token. Returns the snapshot id, the image and mask URLs (for Cerebrate) and the region. The snapshot's "
                "provenance stays in the document, for importing results with snapshot=.", name)
        elif name == BLEND:
            procedure = Gimp.Procedure.new(self, name, Gimp.PDBProcType.PLUGIN, run_blend, None)
            procedure.set_documentation(
                "Poisson-blend a patch layer or group into the background's surroundings",
                "GEGL seamless-clone over the patch's bounding box plus margin: keeps the patch's texture, matches the "
                "background's light and colour at its edge, and writes the blended colour back into each visible patch "
                "layer (outlines unchanged). One undo step. op-id makes it safe to re-run after a lost response.", name)
        elif name == STATUS:
            procedure = Gimp.Procedure.new(self, name, Gimp.PDBProcType.PLUGIN, run_status, None)
            procedure.set_documentation(
                "What became of an operation started with an op-id",
                "Returns done (with its result), started (not finished), failed (with the error) or unknown, from the "
                "document's operation journal.", name)
        else:
            procedure = Gimp.Procedure.new(self, name, Gimp.PDBProcType.PLUGIN, run_group, None)
            procedure.set_documentation(
                "The layer's object group (created around it if needed), anchored for later patches",
                "Returns the layer's parent group, or a new group around it in its place. Records the layer as the "
                "group's anchor (if none yet): call it while the layer still lines up with the photo, e.g. right "
                "after a cutout and before moving it.", name)
        procedure.set_attribution("overmind-server", "overmind-server", "2026")
        procedure.add_enum_argument("run-mode", "Run mode", "The run mode", Gimp.RunMode, Gimp.RunMode.NONINTERACTIVE, rw)
        procedure.add_image_argument("image", "Image", "The image", False, rw)
        if name == IMPORT:
            procedure.add_string_argument("url", "URL", "Artifact URL", "", rw)
            procedure.add_int_argument("x", "X", "Layer x offset", -GLib.MAXINT, GLib.MAXINT, 0, rw)
            procedure.add_int_argument("y", "Y", "Layer y offset", -GLib.MAXINT, GLib.MAXINT, 0, rw)
            procedure.add_string_argument("name", "Name", "Layer name (default: the file name)", "", rw)
            procedure.add_layer_argument("target", "Target", "Layer or group the patch repairs (optional)", True, rw)
            procedure.add_string_argument("group-name", "Group name", "Name for a new group (default: the target's)", "", rw)
            procedure.add_string_argument("context-url", "Context URL", "Cerebrate inpaint context, for the check", "", rw)
            procedure.add_string_argument("snapshot", "Snapshot", "overmind-publish snapshot the result was computed from", "", rw)
            procedure.add_boolean_argument("force", "Force", "Place even if the check fails", False, rw)
            procedure.add_string_argument("op-id", "Operation id", "Makes a retry after a lost response safe", "", rw)
            procedure.add_layer_return_value("layer", "Layer", "The new layer", False, rw)
            procedure.add_group_layer_return_value("group", "Group", "Its group (none without target)", True, rw)
        elif name == PUBLISH:
            procedure.add_string_argument("mode", "Mode", "selection, image or region", "selection", rw)
            procedure.add_int_argument("x", "X", "Region x (mode region)", 0, GLib.MAXINT, 0, rw)
            procedure.add_int_argument("y", "Y", "Region y (mode region)", 0, GLib.MAXINT, 0, rw)
            procedure.add_int_argument("width", "Width", "Region width (mode region)", 0, GLib.MAXINT, 0, rw)
            procedure.add_int_argument("height", "Height", "Region height (mode region)", 0, GLib.MAXINT, 0, rw)
            procedure.add_string_argument("format", "Format", "png or jpeg (the mask is always png)", "png", rw)
            procedure.add_string_argument("name", "Name", "File name stem", "snapshot", rw)
            for rv, nick in (("snapshot", "Snapshot id"), ("image-url", "Image URL"), ("mask-url", "Mask URL (empty without a selection)")):
                procedure.add_string_return_value(rv, nick, nick, "", rw)
            for rv in ("x", "y", "width", "height"):
                procedure.add_int_return_value(rv, rv, f"Snapshot region {rv}", 0, GLib.MAXINT, 0, rw)
        elif name == BLEND:
            procedure.add_layer_argument("patch", "Patch", "A patch layer, or a group of them", False, rw)
            procedure.add_layer_argument("background", "Background", "What the patch must blend into", False, rw)
            procedure.add_int_argument("margin", "Margin", "Pixels of surroundings around the patch", 8, 512, 48, rw)
            procedure.add_string_argument("op-id", "Operation id", "Makes a retry after a lost response safe", "", rw)
            procedure.add_string_return_value("report", "Report", "JSON: layers, region, seconds", "", rw)
        elif name == STATUS:
            procedure.add_string_argument("op-id", "Operation id", "The op-id the operation was started with", "", rw)
            procedure.add_string_return_value("status", "Status", "done, started, failed or unknown", "", rw)
            procedure.add_string_return_value("details", "Details", "JSON: the result or error, age_s", "", rw)
        else:
            procedure.add_layer_argument("layer", "Layer", "The object's layer", False, rw)
            procedure.add_string_argument("name", "Name", "Group name (default: the layer's)", "", rw)
            procedure.add_group_layer_return_value("group", "Group", "The object's group", False, rw)
        return procedure


Gimp.main(OvermindArtifacts.__gtype__, sys.argv)
