"""Image inputs and output artifacts. Not an artifact platform: one directory
of per-request folders, pruned by age. Outputs are referenced as
artifact://<run>/<name> (readable through the MCP resource of that name),
their path (for same-host clients) and, when a public base URL is set, a
signed HTTP URL that any tool on the Tailnet/LAN can fetch directly (the
server's /artifacts route -- the same file, no copy). Inputs may be base64 /
data: URIs, artifact:// URIs, this store's own URLs, or paths under the
allowed input roots."""
import base64
import binascii
import hashlib
import hmac
import io
import os
import secrets
import shutil
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import numpy as np
from PIL import Image

NAME_OK = set("abcdefghijklmnopqrstuvwxyz0123456789-_.")


class InputError(ValueError):
    """A request input the caller must fix."""


class Artifacts:
    def __init__(self, root: str, ttl_s: float, input_roots: list[str], public_url: str = "",
                 key_file: str = "", url_ttl_s: float = 0):
        self.root = Path(root)
        self.ttl_s = ttl_s
        self.input_roots = [Path(r).resolve() for r in input_roots if r] + [self.root.resolve()]
        self.public_url = public_url.rstrip("/")
        self.url_ttl_s = url_ttl_s or ttl_s
        self.key = self._load_key(Path(key_file) if key_file else self.root.parent / "url-key") if self.public_url else b""

    @staticmethod
    def _load_key(path: Path) -> bytes:
        """The URL-signing key: 32 random bytes, created on first start (0600)."""
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(secrets.token_bytes(32))
        return path.read_bytes()

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
        out = {"uri": f"artifact://{run}/{name}", "path": str(path), "bytes": path.stat().st_size}
        if self.public_url:
            out["url"] = self.signed_url(run, name)
        return out

    # ---- signed URLs ------------------------------------------------------
    def _sig(self, run: str, name: str, exp: int) -> str:
        return hmac.new(self.key, f"{run}/{name}:{exp}".encode(), hashlib.sha256).hexdigest()[:32]

    def signed_url(self, run: str, name: str) -> str:
        exp = int(time.time() + self.url_ttl_s)
        return f"{self.public_url}/artifacts/{run}/{name}?exp={exp}&sig={self._sig(run, name, exp)}"

    def verify(self, run: str, name: str, exp: str, sig: str) -> bool:
        """A URL is valid until exp, for exactly that file; the file itself must still exist."""
        if not self.key or not exp.isdigit() or int(exp) < time.time():
            return False
        return hmac.compare_digest(self._sig(run, name, int(exp)), sig)

    def _own_url(self, value: str) -> Path | None:
        """This store's own signed URL (e.g. passed back by an agent) -> the local file, no fetch."""
        if not self.public_url or not value.startswith(self.public_url + "/artifacts/"):
            return None
        parts = urlsplit(value)
        run, _, name = parts.path[len("/artifacts/"):].partition("/")
        q = parse_qs(parts.query)
        if not self.verify(run, name, q.get("exp", [""])[0], q.get("sig", [""])[0]):
            raise InputError("artifact URL: invalid or expired signature")
        return self.path_of(run, name)

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
        base64, an artifact:// URI or this store's URL, or a file under the
        allowed roots (file:///abs/path, or an absolute path that exists
        there). Base64 can start with "/" too -- every JPEG's does, "/9j/" --
        so a bare "/..." is a path only if such a file exists."""
        if not value:
            raise InputError(f"{what}: empty")
        if (own := self._own_url(value)) is not None:
            data = own.read_bytes()
        elif value.startswith("artifact://"):
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
