"""Claude Code's run helper for the Room V1 capstone (environment-dependent: Python on the Mac).

Every operation goes through one of three routes and is logged with it, so a run record can say what
was done through the shared MCP tools and what needed more:

  mcp-gimp       a GIMP Agent MCP tool, over the MCP protocol (the same 38 tools Buckminster has)
  mcp-cerebrate  a Cerebrate MCP tool, over the MCP protocol (the same 9 tools)
  direct-bridge  the GIMP bridge client directly (incl. ops the MCP server doesn't expose, e.g. exec)
  local          image processing in this process (NumPy, OpenCV, PIL) on exported pixels

    async with Session(run_dir) as s:
        info = await s.gimp("gimp_image_info", image_id=1)
        png = await s.render(image_id=1, path=run_dir / "before.png")
        r = await s.cerebrate("segment_region", image=..., boxes=[...], candidates=True)
        s.local("mask union + hole fill", why="per-pixel arithmetic")
    print(s.summary())

Calls land in <run_dir>/calls.jsonl.
"""
import base64, glob, json, os, sys, time
from pathlib import Path

from fastmcp import Client

GIMP_SERVER = {"mcpServers": {"gimp": {"command": "/Users/dev/.local/bin/uvx",
                                       "args": ["--from", "gimp-agent-mcp==0.5.0", "gimp-agent-mcp", "serve"],
                                       "env": {"GIMP_AGENT_ALLOW_PYTHON": "0"}}}}
CEREBRATE_URL = "http://127.0.0.1:18002/mcp"


def _bridge_client():
    site = glob.glob(os.path.expanduser("~/.cache/uv/archive-v0/*/lib/python3*/site-packages/gimp_agent_mcp"))
    sys.path.insert(0, str(Path(site[0]).parent))
    from gimp_agent_mcp.bridge_client import BridgeClient
    return BridgeClient(timeout=170)


class ToolError(RuntimeError):
    pass


class Session:
    def __init__(self, run_dir):
        self.run_dir = Path(run_dir).expanduser()
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.log = open(self.run_dir / "calls.jsonl", "a", buffering=1)
        self._bridge = None

    async def __aenter__(self):
        self._g = Client(GIMP_SERVER, timeout=180)
        self._c = Client(CEREBRATE_URL, timeout=330)
        await self._g.__aenter__()
        await self._c.__aenter__()
        return self

    async def __aexit__(self, *exc):
        await self._g.__aexit__(*exc)
        await self._c.__aexit__(*exc)
        self.log.close()

    async def open_image(self, path):
        """The image for path: the already-open one if GIMP has it, else gimp_open. Returns its image_info."""
        path = str(Path(path).expanduser())
        for im in await self.gimp("gimp_list_images"):
            if im.get("file") == path:
                return await self.gimp("gimp_image_info", image_id=im["id"])
        return await self.gimp("gimp_open", path=path)

    def _record(self, route, name, args, t0, ok, note=None):
        brief = {k: (v if len(json.dumps(v, default=str)) < 200 else "…") for k, v in (args or {}).items()}
        self.log.write(json.dumps({"t": round(t0, 1), "route": route, "name": name, "args": brief,
                                   "s": round(time.time() - t0, 2), "ok": ok, **({"note": note} if note else {})},
                                  default=str) + "\n")

    async def _call(self, client, route, tool, args):
        t0 = time.time()
        try:
            r = await client.call_tool(tool, args, raise_on_error=False)
        except Exception as exc:
            self._record(route, tool, args, t0, False, str(exc)[:300]); raise
        if r.is_error:
            msg = " ".join(getattr(b, "text", "") for b in r.content)[:500]
            self._record(route, tool, args, t0, False, msg); raise ToolError(f"{tool}: {msg}")
        self._record(route, tool, args, t0, True)
        return r

    async def gimp(self, tool, **args):
        """A GIMP Agent MCP tool; returns its structured result (dict/list) when there is one."""
        r = await self._call(self._g, "mcp-gimp", tool, args)
        sc = r.structured_content
        return sc.get("result", sc) if isinstance(sc, dict) else r.data

    async def pdb(self, procedure, **args):
        """gimp_pdb_call through MCP; returns the values list."""
        out = await self.gimp("gimp_pdb_call", name=procedure, args=args)
        return out.get("values", out) if isinstance(out, dict) else out

    async def render(self, path=None, **args):
        """gimp_render through MCP; saves the PNG to path (if given) and returns its bytes."""
        r = await self._call(self._g, "mcp-gimp", "gimp_render", args)
        png = next(base64.b64decode(b.data) for b in r.content if getattr(b, "mimeType", "") == "image/png")
        if path:
            Path(path).write_bytes(png)
        return png

    async def cerebrate(self, tool, **args):
        r = await self._call(self._c, "mcp-cerebrate", tool, args)
        return r.structured_content if r.structured_content is not None else r.data

    def bridge(self, op, why, **params):
        """The GIMP bridge directly: beyond Buckminster's reach. `why` is recorded."""
        if self._bridge is None:
            self._bridge = _bridge_client()
        t0 = time.time()
        try:
            out = self._bridge.call(op, params)
        except Exception as exc:
            self._record("direct-bridge", op, params, t0, False, f"{why} | {exc}"[:300]); raise
        self._record("direct-bridge", op, params, t0, True, why)
        return out

    def local(self, what, why):
        """Mark image processing done in this process (beyond Buckminster's reach)."""
        self._record("local", what, {}, time.time(), True, why)

    def summary(self):
        counts, beyond = {}, []
        for line in open(self.run_dir / "calls.jsonl"):
            d = json.loads(line)
            counts.setdefault(d["route"], {}).setdefault(d["name"], 0)
            counts[d["route"]][d["name"]] += 1
            if d["route"] in ("direct-bridge", "local"):
                beyond.append(f"{d['name']}: {d.get('note', '')}")
        return {"calls": counts, "beyond_mcp": sorted(set(beyond))}


async def hud(s, image_id, title, status, group=None):
    """Create or update the experiment HUD: a top group of native text layers, through MCP tools only.
    Returns {"group", "title", "status", "backing"} ids. Hide it before publishing or clean exports."""
    if group is None:
        g = (await s.pdb("gimp-group-layer-new", image=image_id, name=HUD_NAME))[0]["id"]
        await s.pdb("gimp-image-insert-layer", image=image_id, layer=g, position=0)
        back = (await s.gimp("gimp_layer", action="new", image_id=image_id, name="HUD backing", width=1500, height=170,
                             fill="#101010", x=40, y=40))
        back_id = back.get("id") or back.get("layer_id") or back["layer"]["id"]
        await s.gimp("gimp_layer", action="set", layer_id=back_id, opacity=72.0)
        await s.gimp("gimp_layer", action="reorder", layer_id=back_id, parent_id=g, position=0)
        t = await s.gimp("gimp_text", image_id=image_id, text=title, size=58, color="#ffffff", x=70, y=55)
        st = await s.gimp("gimp_text", image_id=image_id, text=status, size=40, color="#d8d8d8", x=70, y=135)
        ids = {"group": g, "backing": back_id, "title": _id(t), "status": _id(st)}
        for k in ("title", "status"):
            await s.gimp("gimp_layer", action="reorder", layer_id=ids[k], parent_id=g, position=0)
        return ids
    await s.gimp("gimp_text", layer_id=group["status"], text=status)
    return group


HUD_NAME = "EXPERIMENT HUD (exclude from inference/export)"


def _id(r):
    if isinstance(r, dict):
        for k in ("layer_id", "id"):
            if k in r:
                return r[k]
        for v in r.values():
            if isinstance(v, dict) and "id" in v:
                return v["id"]
    raise ValueError(f"no id in {r}")
