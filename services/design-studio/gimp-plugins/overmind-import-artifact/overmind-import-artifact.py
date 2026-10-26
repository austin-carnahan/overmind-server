#!/usr/bin/env python3
"""GIMP 3 plug-in: `overmind-import-artifact` -- fetch an image from Overmind's
artifact service by URL and add it to an image as a layer at (x, y).

Why: agents pass artifact *references* (a Cerebrate inpaint patch, a mask)
instead of moving pixels themselves. GIMP's own file loading can't do it on
macOS: the bridge turns every file argument into a local path, and GIMP's GIO
has no http backend there (only file and resource schemes) -- see
services/cerebrate-mcp/README.md, "GIMP handoff". GIMP's bundled Python can
fetch over HTTP(S), so this procedure downloads to a temporary file and loads
that. Agents call it through the GIMP MCP's gimp_pdb_call:

  gimp_pdb_call(name="overmind-import-artifact",
                args={"image": <id>, "url": "<patch url>", "x": <x>, "y": <y>, "name": "lamp removed"})

Fetches are limited to the artifact service (allowed URL prefixes, below), no
redirects, a size cap, and PNG/JPEG/WebP content only: an agent can't make
GIMP fetch arbitrary URLs. Prefixes and the cap can be overridden in
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
from gi.repository import Gimp, Gio, GLib, GObject  # noqa: E402

PROC = "overmind-import-artifact"
DEFAULTS = {"allowed_prefixes": ["http://artifacts.home.arpa/artifacts/"], "max_bytes": 64 * 1024 * 1024}
SIGNATURES = ((b"\x89PNG\r\n\x1a\n", ".png"), (b"\xff\xd8\xff", ".jpg"), (b"RIFF", ".webp"))


def config():
    cfg = dict(DEFAULTS)
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), PROC + ".json")
    if os.path.exists(path):
        with open(path) as f:
            cfg.update(json.load(f))
    return cfg


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "redirects are not followed", headers, fp)


def fetch(url, cfg):
    """The image bytes and a file suffix, or ValueError saying why not."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not any(url.startswith(p) for p in cfg["allowed_prefixes"]):
        raise ValueError(f"URL not allowed (allowed prefixes: {cfg['allowed_prefixes']})")
    opener = urllib.request.build_opener(_NoRedirect)
    with opener.open(urllib.request.Request(url, headers={"User-Agent": PROC}), timeout=60) as r:
        data = r.read(cfg["max_bytes"] + 1)
    if len(data) > cfg["max_bytes"]:
        raise ValueError(f"larger than {cfg['max_bytes']} bytes")
    for sig, suffix in SIGNATURES:
        if data.startswith(sig) and (suffix != ".webp" or data[8:12] == b"WEBP"):
            return data, suffix
    raise ValueError("not a PNG, JPEG or WebP image")


def run(procedure, config_, data):
    image = config_.get_property("image")
    url = config_.get_property("url")
    x, y = config_.get_property("x"), config_.get_property("y")
    name = config_.get_property("name") or os.path.basename(urlsplit(url).path) or "artifact"
    tmp = None
    try:
        payload, suffix = fetch(url, config())
        fd, tmp = tempfile.mkstemp(prefix="overmind-artifact-", suffix=suffix)
        with os.fdopen(fd, "wb") as f:
            f.write(payload)
        image.undo_group_start()
        try:
            layer = Gimp.file_load_layer(Gimp.RunMode.NONINTERACTIVE, image, Gio.File.new_for_path(tmp))
            if layer is None:
                raise ValueError("GIMP could not load the image")
            image.insert_layer(layer, None, 0)
            layer.set_offsets(x, y)
            layer.set_name(name)
        finally:
            image.undo_group_end()
        Gimp.displays_flush()
    except Exception as exc:  # report every failure to the caller as a PDB error
        return procedure.new_return_values(
            Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error.new_literal(GLib.quark_from_string(PROC), f"{PROC}: {exc}", 1))
    finally:
        if tmp and os.path.exists(tmp):
            os.unlink(tmp)
    return Gimp.ValueArray.new_from_values([
        GObject.Value(Gimp.PDBStatusType, Gimp.PDBStatusType.SUCCESS),
        GObject.Value(Gimp.Layer, layer),
    ])


class OvermindImportArtifact(Gimp.PlugIn):
    def do_set_i18n(self, name):
        return False

    def do_query_procedures(self):
        return [PROC]

    def do_create_procedure(self, name):
        procedure = Gimp.Procedure.new(self, name, Gimp.PDBProcType.PLUGIN, run, None)
        procedure.set_documentation(
            "Add an image from Overmind's artifact service as a layer",
            "Fetches the URL (artifact service only, no redirects, size-capped, PNG/JPEG/WebP), loads it as a "
            "new top layer of the image at offset (x, y), and returns the layer. For Cerebrate results such as "
            "inpaint patches: pass the patch's url and offset.",
            name,
        )
        procedure.set_attribution("overmind-server", "overmind-server", "2026")
        procedure.add_enum_argument("run-mode", "Run mode", "The run mode", Gimp.RunMode, Gimp.RunMode.NONINTERACTIVE,
                                    GObject.ParamFlags.READWRITE)
        procedure.add_image_argument("image", "Image", "The image to add the layer to", False, GObject.ParamFlags.READWRITE)
        procedure.add_string_argument("url", "URL", "Artifact URL", "", GObject.ParamFlags.READWRITE)
        procedure.add_int_argument("x", "X", "Layer x offset", -GLib.MAXINT, GLib.MAXINT, 0, GObject.ParamFlags.READWRITE)
        procedure.add_int_argument("y", "Y", "Layer y offset", -GLib.MAXINT, GLib.MAXINT, 0, GObject.ParamFlags.READWRITE)
        procedure.add_string_argument("name", "Name", "Layer name (default: the file name)", "",
                                      GObject.ParamFlags.READWRITE)
        procedure.add_layer_return_value("layer", "Layer", "The new layer", False, GObject.ParamFlags.READWRITE)
        return procedure


Gimp.main(OvermindImportArtifact.__gtype__, sys.argv)
