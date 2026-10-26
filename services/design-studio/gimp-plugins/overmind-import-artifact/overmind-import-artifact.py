#!/usr/bin/env python3
"""GIMP 3 plug-in: import Overmind artifacts (e.g. Cerebrate inpaint patches)
as layers, and keep each object's repairs in the object's own layer group.

Two PDB procedures, called by agents through the GIMP MCP's gimp_pdb_call:

  overmind-make-object-group(image, layer, name) -> group
      The layer's object group: its parent group if it is already in one,
      else a new group around it (same place in the stack, same look). Call it
      right after cutting an object out, while the cutout still lines up with
      the photo: the group records an *anchor* (which member is the original
      and where it sat), so later patches, whose offsets are in the photo's
      pixels, land where the object is now.

  overmind-import-artifact(image, url, x, y, name, target, group-name, context-url, force)
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
      One undo step. Returns the new layer and its group.

Why fetching here: GIMP's own file loading can't use a URL on macOS (the MCP
bridge turns file arguments into local paths; GIO has no http backend), and
agents should pass references, not pixels -- services/cerebrate-mcp/README.md,
"GIMP handoff". Fetches are limited to the artifact service (allowed URL
prefixes), no redirects, a size cap, and PNG/JPEG/WebP only. Overrides go in
overmind-import-artifact.json next to this file:
  {"allowed_prefixes": ["http://artifacts.home.arpa/artifacts/"], "max_bytes": 67108864}
"""
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
from urllib.parse import urlsplit

import gi

gi.require_version("Gimp", "3.0")
gi.require_version("Gegl", "0.4")
from gi.repository import Gegl, Gimp, Gio, GLib, GObject  # noqa: E402

IMPORT, GROUP = "overmind-import-artifact", "overmind-make-object-group"
ANCHOR = "overmind-object-anchor"
DEFAULTS = {"allowed_prefixes": ["http://artifacts.home.arpa/artifacts/"], "max_bytes": 64 * 1024 * 1024}
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


def run_import(procedure, config_, data):
    get = config_.get_property
    image, url, x, y = get("image"), get("url"), get("x"), get("y")
    target, force, ctx_url = get("target"), get("force"), get("context-url")
    name = get("name") or os.path.basename(urlsplit(url).path) or "artifact"
    cfg, tmps = config(), []
    try:
        group = existing_group(target) if target is not None and (target.is_group() or target.get_parent() is not None) else None
        dx, dy = (0, 0)
        if group is not None:
            try:
                dx, dy = displacement(image, group)
            except Refused:
                if not force:
                    raise
        px, py = x + dx, y + dy
        image.undo_group_start()
        try:
            if target is not None and ctx_url and not force:
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
        Gimp.displays_flush()
    except Exception as exc:  # every failure goes back to the caller as a PDB error
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
        return [IMPORT, GROUP]

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
            procedure.add_boolean_argument("force", "Force", "Place even if the check fails", False, rw)
            procedure.add_layer_return_value("layer", "Layer", "The new layer", False, rw)
            procedure.add_group_layer_return_value("group", "Group", "Its group (none without target)", True, rw)
        else:
            procedure.add_layer_argument("layer", "Layer", "The object's layer", False, rw)
            procedure.add_string_argument("name", "Name", "Group name (default: the layer's)", "", rw)
            procedure.add_group_layer_return_value("group", "Group", "The object's group", False, rw)
        return procedure


Gimp.main(OvermindArtifacts.__gtype__, sys.argv)
