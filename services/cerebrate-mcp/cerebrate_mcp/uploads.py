"""Uploads into the artifact store, e.g. a GIMP host publishing a snapshot of
its document for Cerebrate to work on. Create-only: an upload makes a new
artifact (same lifetime and signed URLs as any output) and can't read,
overwrite or delete anything.

Each uploading host has its own token, `<host>.<secret>`, sent as
`Authorization: Bearer ...`. Only the secret's sha256 is stored, in a JSON
file re-read when it changes, so issuing or revoking takes effect without a
restart:
  python -m cerebrate_mcp.uploads add macbook-m1     # prints the token once
  python -m cerebrate_mcp.uploads revoke macbook-m1
  python -m cerebrate_mcp.uploads list
(in the container: docker exec cerebrate-mcp python -m cerebrate_mcp.uploads ...).

Limits: PNG or JPEG only (checked by decoding), a size cap, and a daily
per-host count, counted from the host's upload folders in the store. Tokens
travel over plain HTTP on the LAN like every *.home.arpa site (the DNS plan
defers HTTPS) -- an accepted, deferred risk."""
import hashlib
import hmac
import io
import json
import os
import secrets
import sys
import time
from pathlib import Path

from PIL import Image

from .artifacts import NAME_OK, Artifacts

FORMATS = {"PNG": ".png", "JPEG": ".jpg"}


class UploadError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class Tokens:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._mtime, self._data = None, {}

    def _load(self) -> dict:
        try:
            mtime = self.path.stat().st_mtime
        except FileNotFoundError:
            return {}
        if mtime != self._mtime:
            self._data, self._mtime = json.loads(self.path.read_text() or "{}"), mtime
        return self._data

    def host_for(self, header: str | None) -> str | None:
        """The host a bearer token belongs to, or None."""
        if not header or not header.startswith("Bearer "):
            return None
        host, _, secret = header[len("Bearer "):].strip().partition(".")
        entry = self._load().get(host)
        if not entry or entry.get("revoked") or not secret:
            return None
        return host if hmac.compare_digest(entry["sha256"], hashlib.sha256(secret.encode()).hexdigest()) else None

    # ---- administration (the CLI below) ----
    def _write(self, data: dict):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=1)
        os.replace(tmp, self.path)

    def add(self, host: str) -> str:
        if not host or set(host) - NAME_OK or "." in host:
            raise ValueError("host: lowercase letters, digits, - and _")
        secret = secrets.token_urlsafe(32)
        data = dict(self._load())
        data[host] = {"sha256": hashlib.sha256(secret.encode()).hexdigest(), "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "revoked": False}
        self._write(data)
        return f"{host}.{secret}"

    def revoke(self, host: str) -> bool:
        data = dict(self._load())
        if host not in data:
            return False
        data[host] = {**data[host], "revoked": True, "revoked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        self._write(data)
        return True


def accept(art: Artifacts, host: str, body: bytes, name: str, max_bytes: int, daily_max: int) -> dict:
    """Store one uploaded image as a new artifact; the artifact reference plus its size and format."""
    if len(body) > max_bytes:
        raise UploadError(413, f"larger than {max_bytes} bytes")
    if not body:
        raise UploadError(400, "empty body")
    name = (name or "upload").lower()
    if set(name) - NAME_OK or ".." in name or name.startswith("."):
        raise UploadError(400, "name: lowercase letters, digits, - _ and . (no leading dot)")
    stem = name.rsplit(".", 1)[0] if "." in name else name
    try:
        with Image.open(io.BytesIO(body)) as im:
            fmt, size = im.format, im.size
            im.verify()
    except Exception as exc:
        raise UploadError(415, f"not a decodable image ({exc})") from exc
    if fmt not in FORMATS:
        raise UploadError(415, f"{fmt}: PNG or JPEG only")
    today = time.strftime("%Y%m%d")
    prefix = f"up-{host}-{today}"
    if art.root.is_dir() and sum(1 for d in art.root.iterdir() if d.name.startswith(prefix)) >= daily_max:
        raise UploadError(429, f"{host}: daily upload limit ({daily_max}) reached")
    run = art.new_run(prefix=f"up-{host}-")
    ref = art.save_bytes(run, stem + FORMATS[fmt], body)
    return {**ref, "width": size[0], "height": size[1], "format": fmt.lower()}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    root = Path(os.environ.get("CEREBRATE_MCP_ARTIFACT_DIR", "/var/lib/overmind/cerebrate-mcp/artifacts"))
    tokens = Tokens(Path(os.environ.get("CEREBRATE_MCP_UPLOAD_TOKENS", str(root.parent / "upload-tokens.json"))))
    if argv[:1] == ["add"] and len(argv) == 2:
        print(tokens.add(argv[1]))
    elif argv[:1] == ["revoke"] and len(argv) == 2:
        print("revoked" if tokens.revoke(argv[1]) else "no such host")
    elif argv == ["list"]:
        for host, e in sorted(tokens._load().items()):
            print(f"{host}\tcreated {e['created']}\t{'REVOKED ' + e.get('revoked_at', '') if e.get('revoked') else 'active'}")
    else:
        sys.exit("usage: python -m cerebrate_mcp.uploads add <host> | revoke <host> | list")


if __name__ == "__main__":
    main()
