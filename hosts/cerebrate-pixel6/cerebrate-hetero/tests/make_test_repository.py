"""Builds a test MLServer model repository from a checkout's held (or
production) model settings, for the side-by-side test supervisor: each
model's settings with exactly two overrides -- the supervisor port (8777) and
the model path moved into the test staging directory (the test supervisor
approves only files there) -- and symlinks to the checkout's adapter. Nothing
else changes, so a test run exercises the settings as they will be promoted.
usage: make_test_repository.py <checkout> <out dir> <model>... [--port 8777] [--staging /data/local/tmp/cerebrate-stage]"""
import argparse
import json
import os
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("checkout")
ap.add_argument("out")
ap.add_argument("models", nargs="+")
ap.add_argument("--port", type=int, default=8777)
ap.add_argument("--staging", default="/data/local/tmp/cerebrate-stage")
args = ap.parse_args()

mlserver = Path(args.checkout).resolve() / "hosts/cerebrate-pixel6/mlserver"
adapter = mlserver / "models/cerebrate-graph"
for name in args.models:
    src = next((d for d in (mlserver / "held-models" / name, mlserver / "models" / name) if d.is_dir()), None)
    if src is None:
        raise SystemExit(f"{name}: not in held-models/ or models/")
    settings = json.loads((src / "model-settings.json").read_text())
    extra = settings["parameters"]["extra"]
    extra["cerebrate_graph_supervisor_port"] = args.port
    extra["cerebrate_graph_model_path"] = f"{args.staging}/{os.path.basename(extra['cerebrate_graph_model_path'])}"
    dst = Path(args.out) / name
    dst.mkdir(parents=True, exist_ok=True)
    (dst / "model-settings.json").write_text(json.dumps(settings, indent=2) + "\n")
    for module in ("cerebrate_graph_runtime.py", "cerebrate_graph_protocol.py"):
        link = dst / module
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(adapter / module)
    print(f"{name}: {src.relative_to(mlserver)} -> {dst} (supervisor port {args.port}, model {extra['cerebrate_graph_model_path']})")
