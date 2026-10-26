"""Cerebrate model registry: loads models/catalog.yaml (what each model is and
does: identity, capabilities, artifacts, aliases, serving interface, task
selections) and models/variants.yaml (how each configuration executes:
stages, precisions, validation evidence, benchmarks, serving profile),
validates both, and resolves aliases and task selections.

Used by scripts/validate-model-catalog, scripts/cerebrate-models,
scripts/stage-model and models/tests. Needs pyyaml; validation also needs
jsonschema (see models/README.md)."""
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = REPO_ROOT / "models"
CATALOG_PATH = MODELS_DIR / "catalog.yaml"
VARIANTS_PATH = MODELS_DIR / "variants.yaml"
CATALOG_SCHEMA = MODELS_DIR / "schema.json"
VARIANTS_SCHEMA = MODELS_DIR / "variants.schema.json"
DEVICE_DIR = "/data/local/tmp"          # cerebrate-supervisor's flat staging directory
STORE_ROOT = "/mnt/models"               # artifact store on overmind-01 (models/README.md)

ALIASES = ("default", "fast", "quality", "reference", "fallback")
SERVED = ("staged", "production")       # statuses that need a complete serving path
ROLE_ORDER = ("default", "fast", "quality", "reference", "fallback")


def load_yaml(path):
    with open(path) as f:
        return yaml.safe_load(f)


def heading_anchor(text):
    """GitHub's heading slug: lowercase, punctuation dropped (hyphens and
    underscores kept), each space a hyphen."""
    text = re.sub(r"`", "", text.strip().lower())
    text = re.sub(r"[^\w\- ]", "", text, flags=re.UNICODE)
    return text.replace(" ", "-")


def markdown_anchors(path):
    anchors, seen = set(), {}
    in_code = False
    for line in Path(path).read_text().splitlines():
        if line.startswith("```"):
            in_code = not in_code
        if in_code:
            continue
        m = re.match(r"^#{1,6}\s+(.*)$", line)
        if m:
            a = heading_anchor(m.group(1))
            n = seen.get(a, 0)
            anchors.add(a if n == 0 else f"{a}-{n}")
            seen[a] = n + 1
    return anchors


def rel(path):
    """A path for messages: repo-relative when inside the repo."""
    try:
        return str(Path(path).relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def parse_worker_config(path):
    """cerebrate-hetero's key=value config (# comments) -> dict of lists."""
    out = {}
    for raw in Path(path).read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        key, _, value = line.partition("=")
        out.setdefault(key.strip(), []).append(value.strip())
    return out


NON_FILE_KEYS = ("nnapi_cache_dir", "tpu_lock")   # a cache directory and a lock file, not artifacts


def config_device_files(conf):
    """Every /data/local/tmp/<file> a worker config refers to (artifacts and
    runtime libraries; not the NNAPI cache directory or the TPU lock)."""
    files = set()
    for key, values in conf.items():
        if key in NON_FILE_KEYS:
            continue
        for v in values:
            files.update(re.findall(re.escape(DEVICE_DIR) + r"/([A-Za-z0-9._+-]+)", v))
    return files


def parse_profiles_file(path):
    """cerebrate-supervisor's profiles file: 'slot <name> <port> <binary>
    [ready_ms]' and 'profile <name> <slot> <model> <config>' (the capacity
    lines: parse_capacity)."""
    slots, profiles = {}, {}
    if not Path(path).exists():
        return slots, profiles
    for raw in Path(path).read_text().splitlines():
        parts = raw.split("#", 1)[0].split()
        if not parts:
            continue
        if parts[0] == "slot" and len(parts) in (4, 5):
            slots[parts[1]] = {"port": int(parts[2]), "binary": parts[3]}
        elif parts[0] == "profile" and len(parts) == 5:
            profiles[parts[1]] = {"slot": parts[2], "model": parts[3], "config": parts[4]}
    return slots, profiles


def parse_capacity(path):
    """The profiles file's capacity lines: (reserve_mb or None, {key: cost_mb})."""
    reserve, costs = None, {}
    if Path(path).exists():
        for raw in Path(path).read_text().splitlines():
            parts = raw.split("#", 1)[0].split()
            if len(parts) == 2 and parts[0] == "reserve_mb":
                reserve = int(parts[1])
            elif len(parts) == 3 and parts[0] == "cost":
                costs[parts[1]] = int(parts[2])
    return reserve, costs


SUPERVISOR_SOURCE = REPO_ROOT / "hosts/cerebrate-pixel6/cerebrate-supervisor/cerebrate-supervisor.cc"
PROFILES_FILE = REPO_ROOT / "hosts/cerebrate-pixel6/cerebrate-supervisor/cerebrate-profiles.conf"
WORKER_CONFIG_DIR = REPO_ROOT / "hosts/cerebrate-pixel6/cerebrate-hetero/configs"
MLSERVER_MODELS_DIR = REPO_ROOT / "hosts/cerebrate-pixel6/mlserver/models"
HELD_MODELS_DIR = REPO_ROOT / "hosts/cerebrate-pixel6/mlserver/held-models"   # staged: not loaded by production MLServer
GUEST_ASSETS_DIR = MLSERVER_MODELS_DIR / "cerebrate-graph" / "assets"
POLICY_FILE = MLSERVER_MODELS_DIR / "cerebrate-graph" / "serving_policy.json"   # the adapter's copy of serving_policy


def compiled_supervisor():
    """Slots and hetero profiles compiled into cerebrate-supervisor.cc."""
    src = SUPERVISOR_SOURCE.read_text()
    slots = {}
    for m in re.finditer(r'\{"([a-z0-9]+)", STAGING_DIR "/([^"]+)", (\d+)(?: \+ PORT_OFFSET)?,', src):
        slots[m.group(1)] = {"port": int(m.group(3)), "binary": m.group(2)}
    profiles = {}
    for m in re.finditer(r'\{"([a-z0-9.-]+)", STAGING_DIR "/([^"]+)", \{"--config", STAGING_DIR "/([^"]+)"', src):
        profiles[m.group(1)] = {"model": m.group(2), "config": m.group(3), "slot": None}
    for slot, var in (("hetero1", "kHeteroBackends"), ("hetero2", "kEdgesamBackends")):
        m = re.search(r"#define %s \"([^\"]+)\"" % var, src)
        for name in (m.group(1).split(",") if m else []):
            if name in profiles:
                profiles[name]["slot"] = slot
    return slots, profiles


@dataclass
class Registry:
    catalog: dict
    variants: dict
    errors: list = field(default_factory=list)

    # ---- loading -------------------------------------------------------
    @classmethod
    def load(cls, catalog_path=CATALOG_PATH, variants_path=VARIANTS_PATH):
        return cls(load_yaml(catalog_path), load_yaml(variants_path))

    @property
    def models(self):
        return self.catalog.get("models", {})

    @property
    def tasks(self):
        return self.catalog.get("tasks", {})

    def model_variants(self, model):
        return {k.split("/", 1)[1]: v for k, v in self.variants.get("variants", {}).items() if k.split("/", 1)[0] == model}

    def variant(self, ref):
        return self.variants.get("variants", {}).get(ref)

    def canonical_model(self, name):
        """Model id, accepting a previous id."""
        if name in self.models:
            return name
        for key, m in self.models.items():
            if name in (m.get("previous_ids") or []):
                return key
        return None

    def resolve(self, ref):
        """'<model>' / '<model>@<alias>' / '<model>/<variant>' / '<task>' /
        '<task>@<selection>' -> '<model>/<variant>'. Raises KeyError."""
        if "@" in ref:
            name, alias = ref.split("@", 1)
        else:
            name, alias = ref, None
        if "/" in name:
            model, var = name.split("/", 1)
            model = self.canonical_model(model) or model
            full = f"{model}/{var}"
            if self.variant(full) is not None:
                return full
            for key, v in self.model_variants(model).items():   # a previous variant id
                if var in (v.get("previous_ids") or []):
                    return f"{model}/{key}"
            raise KeyError(f"no variant {name}")
        if name in self.tasks:
            sel = alias or "default"
            if sel not in self.tasks[name] or sel in ("notes", "available"):
                raise KeyError(f"task {name} has no {sel} selection")
            return self.resolve(self.tasks[name][sel])
        model = self.canonical_model(name)
        if model is None:
            raise KeyError(f"no model or task {name}")
        target = (self.models[model].get("aliases") or {}).get(alias or "default")
        if target is None:
            raise KeyError(f"model {model} has no alias {alias or 'default'}")
        return f"{model}/{target}"

    def serving_of(self, ref):
        v = self.variant(ref) or {}
        return v.get("serving")

    def endpoints(self):
        """MLServer endpoints: (model name, model/variant, status) for every
        staged or production variant with serving."""
        out = []
        for ref, v in sorted(self.variants.get("variants", {}).items()):
            s = v.get("serving")
            if s and v.get("status") in SERVED and s.get("mlserver_model"):
                out.append((s["mlserver_model"], ref, v["status"]))
        return out

    def task_available(self, task):
        sel = self.tasks[task]
        if not sel.get("available", False):
            return False
        for key in ("default", "fallback"):
            if key in sel:
                v = self.variant(self.resolve(sel[key]))
                if not v or v.get("status") != "production" or not v.get("serving"):
                    return False
        return True

    # ---- validation ----------------------------------------------------
    def validate(self, check_files=True):
        from jsonschema import Draft7Validator   # only validation needs it
        self.errors = []
        err = self.errors.append
        for doc, schema_path, label in ((self.catalog, CATALOG_SCHEMA, "catalog"), (self.variants, VARIANTS_SCHEMA, "variants")):
            schema = json.loads(Path(schema_path).read_text())
            for e in sorted(Draft7Validator(schema).iter_errors(doc), key=lambda e: list(e.path)):
                err(f"{label}: {'.'.join(str(p) for p in e.path) or '(root)'}: {e.message}")
        if self.errors:
            return self.errors
        models, variants = self.models, self.variants.get("variants", {})

        # identities: model ids and previous ids are unique across the catalog
        seen = {}
        for key, m in models.items():
            for name in [key] + list(m.get("previous_ids") or []):
                if name in seen:
                    err(f"model id {name} used by both {seen[name]} and {key}")
                seen[name] = key
        file_owner = {}
        for key, m in models.items():
            for akey, art in m.get("artifacts", {}).items():
                for f in art.get("files") or []:
                    if f["name"] in file_owner and file_owner[f["name"]] != (key, akey):
                        err(f"artifact file {f['name']} listed by {file_owner[f['name']]} and {(key, akey)} (device names must be unique)")
                    file_owner[f["name"]] = (key, akey)

        # variants: model exists, ids unique (incl. previous ids), stages resolve
        per_model_ids = {}
        for ref, v in variants.items():
            model, var = ref.split("/", 1)
            if model not in models:
                err(f"variant {ref}: no model {model} in the catalog")
                continue
            ids = per_model_ids.setdefault(model, {})
            for name in [var] + list(v.get("previous_ids") or []):
                if name in ids:
                    err(f"variant id {model}/{name} used by both {ids[name]} and {ref}")
                ids[name] = ref
            arts = models[model].get("artifacts", {})
            for st in v.get("stages", []):
                if st["accelerator"] == "host":
                    if st.get("artifact"):
                        err(f"variant {ref}: host stage {st['name']} can't name an artifact")
                    continue
                if not st.get("artifact"):
                    err(f"variant {ref}: stage {st['name']} on {st['accelerator']} needs an artifact")
                    continue
                art = arts.get(st["artifact"])
                if art is None:
                    err(f"variant {ref}: stage {st['name']} references unknown artifact {st['artifact']}")
                elif v["status"] != "rejected" and not art.get("files"):
                    err(f"variant {ref}: artifact {st['artifact']} has no files (name + sha256) recorded")
            fb = v.get("internal_fallback")
            if fb and fb not in variants:
                err(f"variant {ref}: internal_fallback {fb} is not a variant")
            for rec in self._records(v):
                problem = self._check_record(rec)
                if problem:
                    err(f"variant {ref}: {problem}")
            if v.get("serving_blocked") and (v["status"] in SERVED or v.get("serving")):
                err(f"variant {ref}: serving_blocked ({v['serving_blocked']}) but status {v['status']}{' with serving' if v.get('serving') else ''}")
            if v["status"] in SERVED and v.get("selectable", True):
                for problem in self._check_serving(ref, v, models[model], check_files):
                    err(f"variant {ref}: {problem}")
            elif v.get("serving") and v["status"] != "validated":
                err(f"variant {ref}: status {v['status']} can't carry serving")

        # aliases: each points at a selectable, non-rejected variant of the model
        for key, m in models.items():
            for alias, target in (m.get("aliases") or {}).items():
                v = variants.get(f"{key}/{target}")
                if v is None:
                    err(f"model {key}: alias {alias} -> unknown variant {target}")
                elif v["status"] == "rejected" or v.get("selectable") is False:
                    err(f"model {key}: alias {alias} -> {target}, which is {'rejected' if v['status'] == 'rejected' else 'not selectable'}")
            if m.get("variants"):
                err(f"model {key}: variants belong in models/variants.yaml, not the catalog")
            served = [r for r, v in variants.items() if r.startswith(key + "/") and v["status"] in SERVED]
            if served and "worker" not in m:
                err(f"model {key}: has served variants but no worker")
            if served and not (m.get("serving") or {}).get("mlserver_model") and key not in ("mobilenetv1", "smollm2-135m-instruct"):
                err(f"model {key}: has served variants but no serving.mlserver_model")

        # tasks: selections resolve; default and fallback must be servable (not
        # serving_blocked); an available task's default and fallback are production with serving
        for task, sel in self.tasks.items():
            for key in ("default", "quality", "fallback"):
                if key not in sel:
                    continue
                try:
                    ref = self.resolve(sel[key])
                except KeyError as exc:
                    err(f"tasks.{task}.{key}: {sel[key]} does not resolve ({exc})")
                    continue
                v = variants[ref]
                if v["status"] == "rejected" or v.get("selectable") is False:
                    err(f"tasks.{task}.{key}: {ref} is {'rejected' if v['status'] == 'rejected' else 'not selectable'}")
                if key in ("default", "fallback") and v.get("serving_blocked"):
                    err(f"tasks.{task}.{key}: {ref} is serving_blocked ({v['serving_blocked']}); a task's default and fallback must be servable")
                if sel.get("available") and key in ("default", "fallback") and (v["status"] != "production" or not v.get("serving")):
                    err(f"tasks.{task}.{key}: {ref} is {v['status']} without production serving, but the task is advertised as available")

        # guest-side assets ship in the repo next to the adapter: present, hashes match
        if check_files:
            for key, m in models.items():
                for akey, art in m.get("artifacts", {}).items():
                    if art.get("target") != "guest":
                        continue
                    for fl in art.get("files") or []:
                        p = GUEST_ASSETS_DIR / fl["name"]
                        if not p.exists():
                            err(f"model {key}: guest asset {fl['name']} not in {rel(GUEST_ASSETS_DIR)}")
                        elif sha256_file(p) != fl["sha256"]:
                            err(f"model {key}: guest asset {fl['name']} sha256 differs from the catalog")
        # profile names must fit the supervisor's 31-character backend field
        for prof in list(compiled_supervisor()[1]) + list(parse_profiles_file(PROFILES_FILE)[1]):
            if len(prof) > 31:
                err(f"supervisor profile name {prof} is longer than 31 characters")

        # one serving policy, generated: the profiles file and the adapter's
        # policy file match the registry; nothing sets residency or an idle
        # window per model
        # (generation assumes an otherwise consistent registry: checked last)
        if not self.errors:
            try:
                if PROFILES_FILE.read_text() != self.generate_profiles_file():
                    err(f"{rel(PROFILES_FILE)} is out of date: run scripts/cerebrate-models generate")
            except (ValueError, KeyError, StopIteration, IndexError) as exc:
                err(f"capacity: cannot generate the profiles file: {exc}")
        if not POLICY_FILE.exists() or POLICY_FILE.read_text() != self.generate_policy_json():
            err(f"{rel(POLICY_FILE)} is out of date: run scripts/cerebrate-models generate")
        for folder in (MLSERVER_MODELS_DIR, HELD_MODELS_DIR):
            for ms in sorted(folder.glob("*/model-settings.json")):
                extra = (json.loads(ms.read_text()).get("parameters") or {}).get("extra") or {}
                for k in extra:
                    if k.endswith("_idle_stop_s") or k.endswith("_residency"):
                        err(f"{rel(ms)}: {k} -- idle window and residency are system-wide (catalog serving_policy)")

        for inv in self.variants.get("investigations", []):
            problem = self._check_record(inv.get("record"))
            if problem:
                err(f"investigation {inv['topic']}: {problem}")
        return self.errors

    @staticmethod
    def _records(v):
        recs = [(v.get("validation") or {}).get("record")]
        recs += [b.get("record") for b in v.get("benchmarks") or []]
        return [r for r in recs if r]

    @staticmethod
    def _check_record(rec):
        if not rec:
            return None
        path, _, anchor = rec.partition("#")
        target = REPO_ROOT / path
        if not target.exists():
            return f"record {rec}: file not found"
        if anchor and target.suffix == ".md" and anchor not in markdown_anchors(target):
            return f"record {rec}: no heading with that anchor"
        return None

    def _check_serving(self, ref, v, model, check_files):
        problems = []
        s = v.get("serving") or {}
        c_slots, c_profiles = compiled_supervisor()
        f_slots, f_profiles = parse_profiles_file(PROFILES_FILE)
        slots = {**c_slots, **f_slots}
        if s.get("slot") in slots and slots[s["slot"]]["binary"] != "cerebrate-hetero":
            # A direct worker slot (cerebrate-infer, -generate): the client
            # names the model file itself; no profile or worker config.
            if s.get("profile") or s.get("worker_config"):
                problems.append(f"slot {s['slot']} runs {slots[s['slot']]['binary']}, which has no profiles")
            if "worker" in model and slots[s["slot"]]["port"] != model["worker"]["port"]:
                problems.append(f"slot {s['slot']} port {slots[s['slot']]['port']} != catalog worker port {model['worker']['port']}")
            ml = s.get("mlserver_model")
            if ml and not (MLSERVER_MODELS_DIR / ml / "model-settings.json").exists():
                problems.append(f"MLServer model {ml}: model-settings.json not found")
            return problems
        for key in ("slot", "profile", "worker_config"):
            if not s.get(key):
                problems.append(f"status {v['status']} needs serving.{key}")
        if problems:
            return problems
        profiles = {**c_profiles, **f_profiles}
        prof = profiles.get(s["profile"])
        if prof is None:
            problems.append(f"supervisor profile {s['profile']} not defined (compiled or {PROFILES_FILE.name})")
        elif prof["slot"] != s["slot"]:
            problems.append(f"supervisor profile {s['profile']} belongs to slot {prof['slot']}, not {s['slot']}")
        if s["slot"] not in slots:
            problems.append(f"supervisor slot {s['slot']} not defined")
        elif "worker" in model and slots[s["slot"]]["port"] != model["worker"]["port"] and v["status"] == "production":
            problems.append(f"slot {s['slot']} port {slots[s['slot']]['port']} != catalog worker port {model['worker']['port']}")
        conf_path = REPO_ROOT / s["worker_config"]
        if not conf_path.exists():
            problems.append(f"worker config {s['worker_config']} not found")
            return problems
        if prof is not None and Path(s["worker_config"]).name != prof["config"]:
            problems.append(f"worker config {Path(s['worker_config']).name} != profile's {prof['config']}")
        stage_files = set()
        for st in v.get("stages", []):
            for f in model.get("artifacts", {}).get(st.get("artifact"), {}).get("files") or []:
                stage_files.add(f["name"])
        fb = v.get("internal_fallback")
        if fb and self.variant(fb):
            for st in self.variant(fb).get("stages", []):
                for f in model.get("artifacts", {}).get(st.get("artifact"), {}).get("files") or []:
                    stage_files.add(f["name"])
        allowed = stage_files | set(s.get("runtime_files", []))
        conf_files = config_device_files(parse_worker_config(conf_path))
        missing = sorted(conf_files - allowed)
        if missing:
            problems.append(f"worker config refers to files that are not this variant's artifacts: {missing}")
        unused = sorted(stage_files - conf_files)
        if unused:
            problems.append(f"variant artifacts not referenced by its worker config: {unused}")
        if prof is not None and prof["model"] not in conf_files | stage_files:
            problems.append(f"profile {s['profile']} declares model {prof['model']}, which isn't one of this variant's files")
        ml = s.get("mlserver_model")
        if ml:
            # Production endpoints live in mlserver/models/ (loaded at startup);
            # staged ones in mlserver/held-models/ (never loaded by production).
            ms_path = (MLSERVER_MODELS_DIR if v["status"] == "production" else HELD_MODELS_DIR) / ml / "model-settings.json"
            other = (HELD_MODELS_DIR if v["status"] == "production" else MLSERVER_MODELS_DIR) / ml / "model-settings.json"
            if other.exists():
                problems.append(f"MLServer model {ml} also in {other.parent.parent.name}/ (a {v['status']} endpoint belongs only in {ms_path.parent.parent.name}/)")
            if not ms_path.exists():
                problems.append(f"MLServer model {ml}: {rel(ms_path)} not found")
            else:
                extra = (json.loads(ms_path.read_text()).get("parameters") or {}).get("extra") or {}
                if extra.get("cerebrate_graph_worker") != s["slot"]:
                    problems.append(f"MLServer model {ml} uses slot {extra.get('cerebrate_graph_worker')}, not {s['slot']}")
                if s["slot"] in slots and extra.get("cerebrate_graph_port") != slots[s["slot"]]["port"]:
                    problems.append(f"MLServer model {ml} port {extra.get('cerebrate_graph_port')} != slot port {slots[s['slot']]['port']}")
                if prof is not None and extra.get("cerebrate_graph_model_path") != f"{DEVICE_DIR}/{prof['model']}":
                    problems.append(f"MLServer model {ml} model_path {extra.get('cerebrate_graph_model_path')} != profile model")
                if extra.get("cerebrate_graph_backend") != s["profile"]:
                    problems.append(f"MLServer model {ml} serves profile {extra.get('cerebrate_graph_backend')}, not {s['profile']}")
        return problems

    # ---- generated serving configuration ---------------------------------
    def served_configurations(self):
        """(ref, variant) for every configuration the supervisor may start:
        staged or production, selectable, with serving, not serving_blocked."""
        return [(ref, v) for ref, v in sorted(self.variants.get("variants", {}).items())
                if v.get("status") in SERVED and v.get("serving") and v.get("selectable", True)
                and not v.get("serving_blocked")]

    def generate_profiles_file(self, port_offset=0):
        """cerebrate-supervisor's profiles file from the registry: the reserve
        (serving_policy), the file slots and profiles of every served
        configuration (compiled-in ones excluded), and every configuration's
        capacity cost (resources.load_mb). Raises ValueError on missing data."""
        policy = self.catalog["serving_policy"]
        c_slots, c_profiles = compiled_supervisor()
        slots, profiles, costs = {}, {}, {}
        for ref, v in self.served_configurations():
            model_key = ref.split("/", 1)[0]
            m, s = self.models[model_key], v["serving"]
            slot = s["slot"]
            if slot not in c_slots:
                port = m["worker"]["port"] + port_offset
                if slots.setdefault(slot, (port, m["worker"]["binary"])) != (port, m["worker"]["binary"]):
                    raise ValueError(f"slot {slot}: conflicting ports or binaries")
            prof = s.get("profile")
            if prof and prof not in c_profiles:
                first = next(st for st in v["stages"] if st.get("artifact"))
                declared = m["artifacts"][first["artifact"]]["files"][0]["name"]
                profiles[prof] = (slot, declared, Path(s["worker_config"]).name)
            key = prof or slot
            load = (v.get("resources") or {}).get("load_mb")
            if load is None:
                raise ValueError(f"{ref}: resources.load_mb (capacity cost) not measured")
            costs[key] = (load, ref)
        port_of = {**{n: c["port"] + port_offset for n, c in c_slots.items()}, **{n: p for n, (p, _) in slots.items()}}
        slot_of = {k: (profiles[k][0] if k in profiles else (c_profiles[k]["slot"] if k in c_profiles else k)) for k in costs}
        out = ["# cerebrate-supervisor profiles file. GENERATED by `scripts/cerebrate-models generate`",
               "# from models/catalog.yaml (serving_policy) and models/variants.yaml (serving,",
               "# resources.load_mb): edit the registry and regenerate, never this file.",
               "# Deployed as /data/local/tmp/cerebrate-profiles.conf and read once at",
               "# supervisor startup; format and capacity rule: cerebrate-supervisor.cc.",
               "", f"reserve_mb {policy['reserve_mb']}", ""]
        for name, (port, binary) in sorted(slots.items(), key=lambda kv: kv[1][0]):
            out.append(f"slot {name} {port} {binary}")
        out.append("")
        for name, (slot, declared, conf) in sorted(profiles.items(), key=lambda kv: (port_of[kv[1][0]], kv[0])):
            out.append(f"profile {name} {slot} {declared} {conf}")
        out.append("")
        for key, (load, ref) in sorted(costs.items(), key=lambda kv: (port_of.get(slot_of[kv[0]], 0), kv[0])):
            out.append(f"cost {key} {load}  # {ref}")
        return "\n".join(out) + "\n"

    def generate_policy_json(self):
        p = self.catalog["serving_policy"]
        return json.dumps({"_generated_by": "scripts/cerebrate-models generate, from models/catalog.yaml serving_policy",
                           "idle_stop_s": p["idle_stop_s"], "capacity_wait_s": p["capacity_wait_s"]}, indent=2) + "\n"

    # ---- artifact store (overmind-01, models/README.md) -------------------
    def store_path(self, model, akey, f, root=STORE_ROOT):
        """Where the verified copy of a recorded file lives in the artifact
        store: published files in the Hugging Face cache (pinned snapshot),
        derived files (our conversions) under derived/<model>/, plain
        downloads under direct/<model>/."""
        art = self.models[model]["artifacts"][akey]
        src = art["source"]
        root = Path(root)
        if "repo" in src and not art.get("derived"):
            org, name = src["repo"].split("/", 1)
            return root / "huggingface" / "hub" / f"models--{org}--{name}" / "snapshots" / src["revision"] / f.get("upstream_name", f["name"])
        if art.get("derived"):
            return root / "derived" / model / f["name"]
        return root / "direct" / model / f["name"]

    # ---- artifact hashes ------------------------------------------------
    def artifact_files(self, model=None):
        """(model, artifact key, file dict) for every recorded file."""
        for key, m in self.models.items():
            if model and key != model:
                continue
            for akey, art in m.get("artifacts", {}).items():
                for f in art.get("files") or []:
                    yield key, akey, f
