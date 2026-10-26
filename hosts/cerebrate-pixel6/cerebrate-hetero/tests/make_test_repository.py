"""Builds a test MLServer model repository from a checkout's model settings
(held-models/ or models/), for the side-by-side test supervisor: each model's
settings with exactly two kinds of override -- every worker port shifted by
--port-offset (the test supervisor's build, -DPORT_OFFSET, and its generated
profiles file use the same offset, because production's ports are in use) and
every model file moved into the test staging directory (the test supervisor
approves only files there) -- plus symlinks to the checkout's adapter files.
Nothing else changes, so a test run exercises the settings as they will be
promoted. Run the test MLServer with CEREBRATE_SUPERVISOR_PORT=8777 (and,
for short checks, CEREBRATE_IDLE_STOP_S / CEREBRATE_CAPACITY_WAIT_S).
usage: make_test_repository.py <checkout> <out dir> <model>... [--port-offset 100] [--staging /data/local/tmp/cerebrate-stage]"""
import argparse
import json
import os
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("checkout")
ap.add_argument("out")
ap.add_argument("models", nargs="+")
ap.add_argument("--port-offset", type=int, default=100)
ap.add_argument("--staging", default="/data/local/tmp/cerebrate-stage")
args = ap.parse_args()

mlserver = Path(args.checkout).resolve() / "hosts/cerebrate-pixel6/mlserver"
for name in args.models:
    src = next((d for d in (mlserver / "held-models" / name, mlserver / "models" / name) if d.is_dir()), None)
    if src is None:
        raise SystemExit(f"{name}: not in held-models/ or models/")
    settings = json.loads((src / "model-settings.json").read_text())
    extra = settings["parameters"]["extra"]
    changes = []
    for key in list(extra):
        if key.endswith("_port") and not key.endswith("supervisor_port"):
            extra[key] = int(extra[key]) + args.port_offset
            changes.append(f"{key}={extra[key]}")
        elif key.endswith("_model_path") or key.endswith("_mmproj_path"):
            extra[key] = f"{args.staging}/{os.path.basename(extra[key])}"
            changes.append(f"{key}={extra[key]}")
    dst = Path(args.out) / name
    dst.mkdir(parents=True, exist_ok=True)
    (dst / "model-settings.json").write_text(json.dumps(settings, indent=2) + "\n")
    for f in src.iterdir():   # the adapter files, as the checkout has them (symlinks resolved)
        if f.name in ("model-settings.json", "README.md") or f.name.startswith("__"):
            continue
        link = dst / f.name
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(f.resolve())
    print(f"{name}: {src.relative_to(mlserver)} -> {dst} ({', '.join(changes)})")
