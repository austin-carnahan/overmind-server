"""What is callable, derived -- never listed by hand: the model registry
(models/catalog.yaml + variants.yaml through models/registry.py: tasks,
aliases, production variants and their MLServer endpoints and interfaces)
intersected with MLServer's live readiness and the contracts this adapter
implements. A model added to the registry and loaded in MLServer appears
here with no change to this service; the registry is re-read whenever its
files change."""
import importlib.util
import os
from pathlib import Path

from .contracts import CONTRACTS
from .mlserver import MLServer, MLServerError


class TargetError(ValueError):
    """A target that doesn't resolve to a callable endpoint for the tool."""


class Discovery:
    def __init__(self, registry_dir: str, mlserver: MLServer):
        self.registry_dir = Path(registry_dir)
        self.mlserver = mlserver
        self._module = None
        self._stamp = None
        self._registry = None

    def registry(self):
        files = [self.registry_dir / n for n in ("catalog.yaml", "variants.yaml", "registry.py")]
        stamp = tuple(os.stat(f).st_mtime_ns for f in files)
        if stamp != self._stamp:
            if self._module is None or stamp[2] != (self._stamp or (0, 0, 0))[2]:
                spec = importlib.util.spec_from_file_location(f"cerebrate_registry_{id(self)}", files[2])
                self._module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(self._module)
            self._registry = self._module.Registry.load(files[0], files[1])
            self._stamp = stamp
        return self._registry

    def endpoints(self, readiness: dict | None) -> dict:
        """{endpoint: info} for every production variant with an MLServer
        endpoint whose interface has a contract here; "ready" from MLServer
        (None when MLServer couldn't be asked)."""
        reg = self.registry()
        out = {}
        for ref, v in sorted(reg.variants.get("variants", {}).items()):
            serving = v.get("serving") or {}
            endpoint = serving.get("mlserver_model")
            model_key = ref.split("/", 1)[0]
            model = reg.models.get(model_key, {})
            interface = (model.get("serving") or {}).get("interface")
            if v.get("status") != "production" or not endpoint or interface not in CONTRACTS:
                continue
            out[endpoint] = {
                "endpoint": endpoint, "model": model_key, "variant": ref, "interface": interface,
                "tool": CONTRACTS[interface].tool, "capabilities": model.get("capabilities", []),
                "stages": [f"{s['name']}: {s['accelerator']} {s['precision']}" for s in v.get("stages", [])],
                "verdict": (v.get("validation") or {}).get("verdict"),
                "ready": None if readiness is None else readiness.get(endpoint) == "READY",
            }
        return out

    def readiness(self):
        try:
            return self.mlserver.readiness(), None
        except MLServerError as exc:
            return None, str(exc)

    def capabilities(self) -> dict:
        readiness, problem = self.readiness()
        eps = self.endpoints(readiness)
        callable_eps = {k: e for k, e in eps.items() if e["ready"]}
        reg = self.registry()
        by_ref = {e["variant"]: e for e in callable_eps.values()}
        tasks = []
        for task, sel in reg.tasks.items():
            selections = {}
            for key in ("default", "quality", "fallback"):
                if key in sel:
                    try:
                        ep = by_ref.get(reg.resolve(sel[key]))
                    except KeyError:
                        ep = None
                    if ep:
                        selections[key] = {"endpoint": ep["endpoint"], "variant": ep["variant"]}
            if selections:
                tool = CONTRACTS[eps[next(iter(selections.values()))["endpoint"]]["interface"]].tool
                tasks.append({"task": task, "tool": tool, "selections": selections,
                              "target_examples": [task] + [f"{task}@{k}" for k in selections if k != "default"]})
        tools = {}
        for c in CONTRACTS.values():
            targets = sorted(e["endpoint"] for e in callable_eps.values() if e["interface"] == c.interface)
            tools[c.tool] = {"summary": c.summary, "inputs": c.inputs, "default_target": c.default_task,
                             "available": bool(targets), "endpoints": targets}
        return {
            "mlserver": {"url": self.mlserver.url, "reachable": readiness is not None, **({"error": problem} if problem else {})},
            "tools": tools,
            "tasks": tasks,
            "models": [{k: e[k] for k in ("model", "endpoint", "variant", "tool", "capabilities", "stages", "verdict")}
                       for e in sorted(callable_eps.values(), key=lambda e: e["model"])],
            "notes": ["Targets: a task (\"box-refinement\", \"box-refinement@quality\"), a model id (\"edgesam-3x\"), "
                      "a model alias (\"sam2.1-hiera-tiny@default\"), a variant (\"<model>/<variant>\") or an endpoint name.",
                      "Only production configurations loaded in MLServer are listed; a model starts on its first request "
                      "(a few seconds), and a request may wait while memory is in use by other requests.",
                      "Output files are artifact://<run>/<name> URIs, readable as MCP resources."],
        }

    def resolve(self, target: str, interface: str) -> dict:
        """The callable endpoint for a target, for a tool's contract."""
        readiness, problem = self.readiness()
        if readiness is None:
            raise TargetError(problem)
        eps = self.endpoints(readiness)
        reg = self.registry()
        if target in eps:
            ep = eps[target]
        else:
            ep = None
            if "@" not in target and "/" not in target and target not in reg.tasks:
                model = reg.canonical_model(target) if hasattr(reg, "canonical_model") else None
                if model:
                    own = [e for e in eps.values() if e["model"] == model]
                    ep = own[0] if len(own) == 1 else None
            if ep is None:
                try:
                    ref = reg.resolve(target)
                except KeyError as exc:
                    raise TargetError(f"unknown target {target!r}: {exc}") from exc
                ep = next((e for e in eps.values() if e["variant"] == ref), None)
                if ep is None:
                    raise TargetError(f"{target!r} resolves to {ref}, which has no MCP-callable endpoint "
                                      f"(production with an MLServer endpoint, contract {interface}); "
                                      f"callable here: {self._callable(eps, interface)}")
        if ep["interface"] != interface:
            raise TargetError(f"{target!r} ({ep['endpoint']}) is a {ep['interface']} endpoint: "
                              f"use {CONTRACTS[ep['interface']].tool}, not this tool")
        if not ep["ready"]:
            raise TargetError(f"{ep['endpoint']} is not loaded in MLServer right now")
        return ep

    @staticmethod
    def _callable(eps: dict, interface: str) -> list:
        return sorted(e["endpoint"] for e in eps.values() if e["interface"] == interface and e["ready"])
