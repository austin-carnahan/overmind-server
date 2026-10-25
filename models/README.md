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
