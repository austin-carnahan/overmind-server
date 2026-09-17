# Cerebrate Pixel 6 model catalog

Stages 1-2 of Phase A from the
[Operational Model Catalog v4](../design-notes/cerebrate_pixel6_operational_model_catalog_v4.md).

- [`schema.json`](schema.json) — JSON Schema (draft-07) for the catalog.
- [`catalog.yaml`](catalog.yaml) — the catalog itself, keyed by model.
- [`../scripts/validate-model-catalog`](../scripts/validate-model-catalog) —
  validates the catalog against the schema. Needs `pyyaml` + `jsonschema` in
  a venv (not stdlib; see the script's docstring), since both this Mac and
  every host here treat their system Python as externally managed (PEP 668).

## Artifact cache: `/mnt/models/` on overmind-01

Per catalog v4 §7.3, artifacts live on Overmind's SSD before ever reaching
the Pixel — re-downloadable, not irreplaceable, so this directory can be
treated as a cache rather than backed up like project state.

`/mnt/models` is a sibling of `/mnt/substrate`, not a subdirectory of it
(moved there 2026-09-17, having initially been placed under Substrate) —
Substrate is a project workspace that may eventually consume services this
cache powers, and a runtime's own downloaded weight cache is a service
internal, not project-owned Substrate content (see
[storage-layout.md](../design-notes/storage-layout.md)). Bind-mounted from
`/mnt/disks/ssd1/models`, matching the existing physical/logical split used
for `/mnt/substrate`, `/mnt/library`, and `/mnt/downloads`.

```text
/mnt/models/
  huggingface/     # HF_HOME — the standard huggingface_hub cache, for
                    # artifacts whose catalog `source` is `repo`+`revision`
  direct/<key>/    # verified plain downloads, for artifacts whose catalog
                    # `source` is `url`+`sha256` — the schema supports both
                    # shapes (models/schema.json#/definitions/source), but
                    # v4 only actually designed the Hugging Face case. This
                    # is Stage 2's answer for the other one: a parallel
                    # directory, named by catalog key, holding exactly the
                    # checksummed artifact and nothing else (e.g. not the
                    # surrounding .tgz or unrelated checkpoint/eval files a
                    # source archive might bundle).
```

Both are populated today and verified against `catalog.yaml`:

| Catalog key | Cache path | Verified against |
| --- | --- | --- |
| `smollm2-135m-instruct` | `huggingface/hub/models--litert-community--SmolLM2-135M-Instruct/snapshots/8111e0a6.../` | fetched via `huggingface_hub.snapshot_download(revision=...)` pinned to the catalog's exact commit SHA |
| `mobilenetv1` | `direct/mobilenetv1/mobilenet_v1_1.0_224_quant.tflite` | downloaded fresh from the catalog's `url`, extracted from the upstream `.tgz`, sha256 and size (4276352 bytes) matched the catalog's recorded values exactly |

`huggingface_hub` itself lives in a `uv`-managed venv at
`~/hf-cache-venv` on overmind-01 (Ubuntu's system Python is 3.14 and
externally managed; `uv venv --python 3.12` sidesteps both problems without
an apt/sudo step, the same approach used for the guest's MLServer venv —
see [hosts/cerebrate-pixel6/mlserver/README.md](../hosts/cerebrate-pixel6/mlserver/README.md)).
To refresh or add an entry:

```bash
export PATH="$HOME/.local/bin:$PATH"
export HF_HOME=/mnt/models/huggingface
~/hf-cache-venv/bin/python3 -c "
from huggingface_hub import snapshot_download
snapshot_download(repo_id='<repo>', revision='<pinned sha>')
"
```

Not yet built (later stages of Phase A): a script that reads `catalog.yaml`
directly instead of a one-off snapshot_download call, and the ADB-push
staging step (catalog v4 §7.4) that gets an artifact from this cache onto
the Pixel itself. Today, `CACHED` (this cache) is populated for both
models; `STAGED` (on-device) reflects whatever was manually pushed earlier
in the project, not anything this cache step drove.
