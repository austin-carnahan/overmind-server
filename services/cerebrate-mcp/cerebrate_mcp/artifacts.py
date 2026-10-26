"""Image inputs and output artifacts. Not an artifact platform: one directory
of per-request folders, pruned by age. Outputs are referenced as
artifact://<run>/<name> (readable through the MCP resource of that name, for
clients on other machines) plus their path (for same-host clients); inputs
may be base64 / data: URIs, artifact:// URIs, or paths under the allowed
input roots."""
import base64
import binascii
import io
import os
import secrets
import shutil
import time
from pathlib import Path

import numpy as np
from PIL import Image

NAME_OK = set("abcdefghijklmnopqrstuvwxyz0123456789-_.")


class InputError(ValueError):
    """A request input the caller must fix."""


class Artifacts:
    def __init__(self, root: str, ttl_s: float, input_roots: list[str]):
        self.root = Path(root)
        self.ttl_s = ttl_s
        self.input_roots = [Path(r).resolve() for r in input_roots if r] + [self.root.resolve()]

    # ---- outputs ----------------------------------------------------------
    def new_run(self) -> str:
        self.root.mkdir(parents=True, exist_ok=True)
        cutoff = time.time() - self.ttl_s
        for d in self.root.iterdir():
            if d.is_dir() and d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)
        run = time.strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)
        (self.root / run).mkdir()
        return run

    def save_png(self, run: str, name: str, array: np.ndarray) -> dict:
        path = self.root / run / name
        Image.fromarray(array).save(path, format="PNG")
        return self.ref(run, name)

    def save_bytes(self, run: str, name: str, data: bytes) -> dict:
        path = self.root / run / name
        path.write_bytes(data)
        return self.ref(run, name)

    def ref(self, run: str, name: str) -> dict:
        path = self.root / run / name
        return {"uri": f"artifact://{run}/{name}", "path": str(path), "bytes": path.stat().st_size}

    def path_of(self, run: str, name: str) -> Path:
        if not run or not name or set(run.lower()) - NAME_OK or set(name.lower()) - NAME_OK or ".." in run or ".." in name:
            raise InputError(f"bad artifact reference artifact://{run}/{name}")
        path = self.root / run / name
        if not path.is_file():
            raise InputError(f"artifact://{run}/{name} not found (artifacts are kept {self.ttl_s / 3600:.0f} h)")
        return path

    # ---- inputs -----------------------------------------------------------
    def _allowed_file(self, raw: str) -> bool:
        path = Path(raw).resolve()
        return any(path.is_relative_to(r) for r in self.input_roots) and path.is_file()

    def _read_allowed(self, raw: str, what: str) -> bytes:
        path = Path(raw).resolve()
        if not any(path.is_relative_to(r) for r in self.input_roots):
            raise InputError(f"{what}: {raw[:200]} is outside the allowed input directories {[str(r) for r in self.input_roots]}")
        if not path.is_file():
            raise InputError(f"{what}: {raw[:200]} not found")
        return path.read_bytes()

    def load_image(self, value: str, what: str = "image") -> tuple[bytes, tuple[int, int]]:
        """Encoded image bytes and (width, height) from a data: URI, raw
        base64, an artifact:// URI, or a file under the allowed roots
        (file:///abs/path, or an absolute path that exists there). Base64
        can start with "/" too -- every JPEG's does, "/9j/" -- so a bare
        "/..." is a path only if such a file exists."""
        if not value:
            raise InputError(f"{what}: empty")
        if value.startswith("artifact://"):
            run, _, name = value[len("artifact://"):].partition("/")
            data = self.path_of(run, name).read_bytes()
        elif value.startswith("file://"):
            data = self._read_allowed(value[len("file://"):], what)
        elif value.startswith("/") and len(value) < 1024 and self._allowed_file(value):
            data = Path(value).read_bytes()
        else:
            b64 = value.split(",", 1)[1] if value.startswith("data:") else value
            try:
                data = base64.b64decode(b64, validate=True)
            except (binascii.Error, ValueError) as exc:
                if value.startswith("/") and len(value) < 1024:
                    self._read_allowed(value, what)   # raises the path's own reason
                raise InputError(f"{what}: not base64, a data: URI, an artifact:// URI or an allowed file path") from exc
        try:
            with Image.open(io.BytesIO(data)) as im:
                size = im.size
        except Exception as exc:
            raise InputError(f"{what}: not a decodable image ({exc})") from exc
        return data, size


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()
