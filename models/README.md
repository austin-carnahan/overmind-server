# Cerebrate Pixel 6 model registry

The authoritative inventory of the models Cerebrate runs on the Pixel 6 —
what each model is, how each configuration executes, how well it was
validated, how fast it measured, and whether (and where) it is served.
Grew out of Phase A of the
[Operational Model Catalog v4](../design-notes/cerebrate_pixel6_operational_model_catalog_v4.md).

| File | Holds |
| --- | --- |
| [`catalog.yaml`](catalog.yaml) | **What** a model is and does: identity, capabilities, artifacts (upstream provenance + the exact deployed files with sha256), model-level aliases, serving interface, task selections |
| [`variants.yaml`](variants.yaml) | **How** each configuration executes: stages, precisions, validation evidence, benchmarks, resources, serving profile; rejected configurations and closed investigations |
| [`schema.json`](schema.json), [`variants.schema.json`](variants.schema.json) | JSON Schemas (draft-07) for the two files |
| [`registry.py`](registry.py) | Loading, cross-checks, alias/task resolution, artifact-store paths |
| [`tests/`](tests/test_registry.py) | Golden production resolution + one test per class of registry error |
| [`../scripts/cerebrate-models`](../scripts/cerebrate-models) | Inventory CLI |
| [`../scripts/validate-model-catalog`](../scripts/validate-model-catalog) | Validator (CI-style exit code) |
| [`../scripts/stage-model`](../scripts/stage-model) | Pushes recorded files from the artifact store to the phone, sha256-verified |

Setup (any host; the Mac's and overmind-01's system Pythons are externally
managed, PEP 668):

```bash
python3 -m venv /tmp/catalog-venv && /tmp/catalog-venv/bin/pip install pyyaml jsonschema
/tmp/catalog-venv/bin/python3 scripts/validate-model-catalog
/tmp/catalog-venv/bin/python3 -m unittest discover -s models/tests
```

## Browsing

```bash
scripts/cerebrate-models                      # models: aliases, variant statuses, endpoint
scripts/cerebrate-models show mi-gan-512      # artifacts + hashes, aliases, every variant
scripts/cerebrate-models variants --status validated
scripts/cerebrate-models tasks                # task selections, resolved, availability
scripts/cerebrate-models resolve box-refinement@fallback
scripts/cerebrate-models resolve efficientsam3-rvm@fast
scripts/cerebrate-models endpoints            # staged + production MLServer endpoints only
scripts/cerebrate-models investigations       # closed/deferred: don't repeat these
scripts/cerebrate-models check-artifacts --store    # on overmind-01: the store vs the catalog
scripts/cerebrate-models check-artifacts --device   # on overmind-01: the phone vs the catalog
```

## Conventions

**Model ids** are stable, lowercase, hyphenated and name the model, not a
role: `yoloe-v8s-pf`, `edgesam-3x`, `depth-anything-v2-small`,
`efficientsam3-rvm`, `mi-gan-512`. A rename keeps the old id in
`previous_ids` (still accepted by `resolve`); MLServer endpoint and supervisor
profile names are serving names and don't change with it (`edgesam-3x` is
served as `edgesam3x-box` with profiles `edgesam3x-*`).

**Variant ids** describe what runs where at which precision and never change
once used — `gpu-fp32`, `gpu-fp16`, `tpu-fp16r-gpu-head-fp16acc32`,
`gpu-trunk-fp32-neck-fp16acc32-grounding-fp16acc32`. Precisions: `fp32`,
`fp16acc32` (FP16 with FP32 accumulation), `fp16`, `fp16r` / `fp16-relaxed`
(an fp32 graph on the Edge TPU with NNAPI's `allow_fp16`), `int8`. A
published file with FP16 weights run at FP32 compute is `gpu-fp32` with
`weights: fp16` on the stage. Preparation details belong in `preparation`, not
the id.

**Aliases** are model-level and point at variant ids: `default` (what a caller
gets), `reference` (the exact configuration closest to the original), `fast`,
`quality`, `fallback`. **Lifecycle** is the variant's `status`:
`validated` → `staged` → `production`, or `rejected`. Roles and lifecycle are
independent: YOLOE's `default` is GPU FP32 (production, not the endpoint),
its endpoint serves `fast`.

**Task selections** (`tasks:` in the catalog) are separate from model
aliases and name immutable `<model>/<variant>` ids: the detection task selects
YOLOE's fast variant while YOLOE's own `default` stays GPU FP32. A task with
`available: true` must select production variants with serving for
`default` and `fallback`; `quality` may name a validated, unserved variant. A
validated model never becomes an endpoint by being listed: `endpoints` shows
only staged/production variants with a complete serving path.

**Servable or not.** A variant that must not be served carries
`serving_blocked: "<reason>"`:

- EfficientSAM3's FP32 default, for memory;
- SAM 2.1's reduced precision, unresolved at 0.963 worst mask IoU.

It stays registered and selectable, so model aliases and a task's `quality`
may name it. EfficientSAM3's model `default` is the blocked FP32 reference.
The validator refuses it serving, a staged or production status, and any
task's `default` or `fallback`: what a task serves must be servable.

**Benchmarks** record their measurement kind: `device` (synchronized end to
end on the phone for the named graph(s)), `worker` (cerebrate-hetero's
inference time), `round-trip` (guest → MLServer → worker → guest), `summed`
(calculated from separately measured stages), `connected` (one connected
pipeline). Validation metrics are task-level and named for what they
measure (detections retained, mask IoU, depth-order agreement, masked PSNR,
token cosine). Unmeasured memory, startup or thermal figures stay `null` —
never estimated. Every `record` is `path#heading-anchor` into a ledger; the
validator checks the heading exists.

## Artifact store: `/mnt/models/` on overmind-01

Every file a variant runs is recorded in the catalog (`files`: device name,
sha256, bytes) and kept in the store before it reaches the phone:

```text
/mnt/models/
  huggingface/   HF_HOME: published files, pinned snapshots (source: repo + revision)
  direct/<model>/   verified plain downloads (source: url + sha256)
  derived/<model>/  our own conversions (derived: true), by device file name
```

`huggingface/` and `direct/` are re-downloadable caches. **`derived/` is not**:
those files come from the spike scripts named in `produced_by`, with specific
tool versions, after hours of validation — treat them as unique generated
data (back them up; see AGENTS.md). `scripts/cerebrate-models
check-artifacts --store` verifies every recorded file (43 files, all
matching, 2026-10-25). The guest adapter's few small assets (`target:
guest`) live in the repo next to the adapter.

`huggingface_hub` lives in a `uv`-managed venv at `~/hf-cache-venv` on
overmind-01. To add published files:

```bash
export HF_HOME=/mnt/models/huggingface
~/hf-cache-venv/bin/python3 -c "
from huggingface_hub import snapshot_download
snapshot_download(repo_id='<repo>', revision='<pinned sha>', allow_patterns=['<file>'])"
```

## Staging onto the Pixel: `scripts/stage-model`

`scripts/stage-model <model>... | --all [--dry-run]` (catalog v4 §7.4)
pushes each recorded file from the store to `/data/local/tmp/<name>` — the
flat layout cerebrate-supervisor approves — checking the store copy's sha256
before the push and the device copy's after it, then renaming it into place.
Files already staged with the recorded checksum are skipped. Run it from a
checkout on overmind-01 with `~/hf-cache-venv/bin/python3` (pyyaml).
`CACHED → STAGED` stays an explicit operator action.

## Onboarding a validated model

The path from a model that passed validation in a spike to an MLServer
endpoint has ten steps. Each step leaves the registry valid, and only the
last touches production. The operational side of these steps (commands, test
ports, windows) is in the
[Pixel 6 models runbook](../runbooks/cerebrate-pixel6-models.md). Steps 1–3
need no new code.

1. **Register the model.** Add a catalog entry: id, description,
   capabilities, artifacts with every file's sha256 and bytes, and aliases.
   Add one `validated` variant per measured configuration in `variants.yaml`,
   with `validation` and `benchmarks` pointing at the spike's ledger.
   Record rejected configurations as `rejected`, with their reason in
   `limitations`; closed directions go under `investigations`.
   `scripts/cerebrate-models hash <file>` prints the `files` entry for a file.
2. **Store it.**
   - Published files go into `/mnt/models/huggingface` at a pinned revision.
   - Our conversions go into `derived/<model>/`, with `derived: true` and
     `produced_by`.

   Then run `scripts/cerebrate-models check-artifacts --store`.
3. **Stage it.** `scripts/stage-model <model>`, then
   `check-artifacts --device`.
4. **Write the worker config.** Write
   `hosts/cerebrate-pixel6/cerebrate-hetero/configs/<model>-<alias>.conf` in
   graph mode (template below), choosing the `input_uint8` mode that matches
   the reference's arithmetic. Use the pattern table in the
   [cerebrate-hetero README](../hosts/cerebrate-pixel6/cerebrate-hetero/README.md#graph-mode-declarative-model-chains-registry-serving-staged-2026-10-25).
   No new worker code is needed for one graph, a chain of graphs, a cached
   image with prompts, or mixed GPU/CPU.
5. **Prove the worker reproduces validation.** Start a test worker
   (`tests/worker_launch.sh`) and run `tests/graph_fidelity.py`. The raw
   outputs must be bit-identical to the validated device outputs. Record
   memory with `tests/resource_sampler.sh`.
6. **Write the adapter hook.** It is a class in
   `mlserver/models/cerebrate-graph/model_hooks.py`, registered in
   `cerebrate_graph_photo.HOOKS`:
   - `prepare` decodes the photo and resizes it exactly as the reference
     does;
   - `finish` turns the outputs into the interface's JSON;
   - a multi-call `run` is used only when a host step sits between graphs.

   Then prove the photo path against the original model on real photos, with
   a `tests/*_photo_check.py`. Exactness problems live here: the library
   version, resampling arithmetic, FMA contraction.
7. **Add a profile.** Add a slot (the next free port) and profile to
   `cerebrate-supervisor/cerebrate-profiles.conf`. The floor is the measured
   free-memory drop plus 1000 MB.
8. **Hold the endpoint.** Create `mlserver/held-models/<endpoint>/` (template
   below, plus the two symlinks), and set the variant to `status: staged` with
   its `serving` block. The validator now checks the whole chain:
   - the config names only this variant's files;
   - the profile is in the slot;
   - the endpoint serves the profile;
   - the folder is in the right place.
9. **Test side by side.** Run the test supervisor and test MLServer with
   `tests/mlserver_staged_test.py`, and record the results.
10. **Promote, in a window.** Move the folder to `models/`, set the variant to
    `production`, load the endpoint, and run the promotion gate
    (`mlserver_staged_test.py --only <endpoint>`). A task becomes
    `available: true` only when its `default` and `fallback` are production
    variants with serving.

**Template.** These are the minimal entries for a single-graph GPU model whose
photo is resized and normalized like the ImageNet references. Replace every
`<…>`.

```yaml
# models/catalog.yaml, under models:
  <model-id>:
    description: >-
      <what it is, which checkpoint, input/output shapes, how it was judged>
    capabilities: [<capability>]
    artifacts:
      tflite_gpu:
        source: {repo: <hf-org/repo>, revision: <40-char sha>}
        files:
          - {name: <device-file>.tflite, upstream_name: <path in repo>, sha256: <sha256>, bytes: <bytes>}
    worker: {binary: cerebrate-hetero, port: <slot port>}
    serving: {mlserver_model: <endpoint>, interface: <photo-…-v1>}
    aliases: {default: gpu-fp32, reference: gpu-fp32}
    residency: on_demand
    requirements: {disk_mb: <MB>, ram_mb: null}
```

```yaml
# models/variants.yaml, under variants:
  <model-id>/gpu-fp32:
    status: validated            # -> staged (step 8) -> production (step 10)
    stages:
      - {name: model, artifact: tflite_gpu, accelerator: gpu, precision: fp32, runtime: litert-2.3.0, phase: image}
    validation:
      reference: <original implementation + revision>
      metrics: {<task metric>: <value>}
      verdict: <exact | near-identical | …>
      record: experiments/pixel6/results.md#<heading-anchor>
    benchmarks:
      - {measure: worker, ms: <ms>, statistic: median, covers: "<what>", record: experiments/pixel6/results.md#<heading-anchor>}
    resources: {ram_mb: null, startup_ms: null}    # measured values only
    # added at step 8:
    serving:
      slot: gpu-<short>
      profile: <model-id>-default
      worker_config: hosts/cerebrate-pixel6/cerebrate-hetero/configs/<model-id>-default.conf
      mlserver_model: <endpoint>
```

```ini
# hosts/cerebrate-pixel6/cerebrate-hetero/configs/<model-id>-default.conf
# <model>, configuration gpu-fp32 (model alias default; models/variants.yaml).
input=pixel_values
input_uint8=unit_mean_std:0.485,0.456,0.406:0.229,0.224,0.225
input_layout=nchw
graph.main.model=/data/local/tmp/<device-file>.tflite
graph.main.precision=fp32
graph.main.inputs=pixel_values=input
graph.main.outputs=<output>
outputs=main.<output>
```

```text
# hosts/cerebrate-pixel6/cerebrate-supervisor/cerebrate-profiles.conf
slot    gpu-<short>  <port>  cerebrate-hetero
profile <model-id>-default  gpu-<short>  <device-file>.tflite  <model-id>-default.conf  <drop + 1000>
```

```json
// hosts/cerebrate-pixel6/mlserver/held-models/<endpoint>/model-settings.json
// (+ symlinks cerebrate_graph_runtime.py, cerebrate_graph_protocol.py -> ../../models/cerebrate-graph/)
{
  "name": "<endpoint>",
  "implementation": "cerebrate_graph_runtime.CerebrateGraphRuntime",
  "parameters": {
    "version": "v0.1.0",
    "extra": {
      "cerebrate_graph_worker": "gpu-<short>",
      "cerebrate_graph_port": <port>,
      "cerebrate_graph_model_path": "/data/local/tmp/<device-file>.tflite",
      "cerebrate_graph_backend": "<model-id>-default",
      "cerebrate_graph_residency": "on_demand",
      "cerebrate_graph_idle_stop_s": 600,
      "cerebrate_graph_request_timeout_s": 120,
      "cerebrate_graph_photo": "<hook name>"
    }
  }
}
```

```python
# hosts/cerebrate-pixel6/mlserver/models/cerebrate-graph/model_hooks.py
class <Name>Hooks:
    S = <input size>

    def prepare(self, inputs, params=None):
        if "photo" not in inputs:
            return None                       # raw tensors: passed to the worker as they are
        img = pil_rgb(_bytes(inputs["photo"]))
        u8 = np.asarray(img.resize((self.S, self.S), Image.BICUBIC), np.uint8)   # exactly the reference's resize
        return {"pixel_values": u8[None]}, {"raw": _raw(params), "size": (img.height, img.width)}

    def finish(self, outputs, ctx):
        h, w = ctx["size"]
        if ctx["raw"]:
            return {**outputs, "original_size": np.array([h, w], np.int64)}
        return {"result": _json({"image": {"width": w, "height": h}, ...})}
# and in cerebrate_graph_photo.py: HOOKS.update({"<hook name>": model_hooks.<Name>Hooks})
```
