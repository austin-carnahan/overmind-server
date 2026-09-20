# Doclet Service — Implementation Design V2

## Goal

Deploy a production document → Markdown service on Overmind using:

- **Docling Serve** for the public API, async jobs, conversion orchestration, and results;
- **Docling standard parsing** for text/layout/tables/figures;
- **Cerebrate Pixel 6** for selective VLM enrichment;
- **MLServer** for model lifecycle and serving;
- **llama.cpp / libmtmd** as a reusable GGUF execution backend.

Guiding separation:

```text
Docling Serve = document service
MLServer      = model service
Android       = inference execution
```

## Architecture

```text
client
  ↓
doclet.home.arpa
  ↓
Caddy
  ↓
Docling Serve — Overmind
  │
  ├── standard Docling pipeline
  │     ├── native text
  │     ├── layout
  │     ├── tables
  │     └── figures
  │
  └── selective Cerebrate enrichment plugin
          ↓
    inference.home.arpa
          ↓
       MLServer
          ↓
   llama_cpp runtime
          ↓
 cerebrate-supervisor
          ↓
   cerebrate-llama
          ↓
 Granite-Docling GGUF
```

Do not use `llama-server` for Granite-Docling; its multimodal serving path was experimentally confirmed incorrect. Build the Android worker around the proven `libmtmd` / `llama-mtmd-cli` inference path.

## Overmind Deployment

Keep the operating system on microSD and Doclet application state on SSD.

```text
/srv/doclet/
├── venv/
├── config/
├── plugins/
├── cache/
├── scratch/
└── results/
```

Continue using the existing shared model cache separately:

```text
/mnt/models/huggingface/
```

Configure caches onto SSD:

```text
UV_CACHE_DIR=/srv/doclet/cache/uv
XDG_CACHE_HOME=/srv/doclet/cache/xdg
TORCH_HOME=/srv/doclet/cache/torch
HF_HOME=/mnt/models/huggingface
```

Run Docling Serve under systemd and expose it through Caddy at:

```text
https://doclet.home.arpa
```

Use Docling Serve's existing async job, status, result, retention, and API machinery rather than creating a parallel Doclet REST API.

## Document Processing Policy

Normal Docling remains authoritative for document parsing.

Do **not** use full-page VLM conversion by default.

Selective enrichment should initially target:

- formulas/equations Docling cannot decode;
- figures and diagrams;
- charts/graphs;
- other explicitly difficult visual elements.

Ordinary embedded PDF text should remain on Docling's deterministic path.

Initial enrichment behavior should be:

```text
best_effort
```

If Cerebrate is unavailable, conversion should still succeed with the normal Docling result plus a warning.

## Docling Extension

Add one small external Docling enrichment plugin.

Responsibilities:

```text
typed Docling element
      ↓
should this be enriched?
      ↓ yes
render/crop required image
      ↓
call Cerebrate document-vision capability
      ↓
attach structured result
```

Keep model choice and Android lifecycle out of this plugin.

The plugin should call the stable Cerebrate capability surface, not ADB or Android processes directly.

## llama.cpp Backend

Establish `llama.cpp` as a generic Cerebrate execution backend.

Create:

```text
cerebrate-llama
```

Responsibilities:

- load a configured GGUF model;
- load an optional multimodal projector;
- accept bounded text/image requests;
- execute through `libllama` / `libmtmd`;
- return generated output;
- contain no Docling-specific workflow logic.

Granite-Docling is the first model using this backend:

```yaml
backend: llama_cpp
capability: document-vision

artifacts:
  model: granite-docling-258M-bf16.gguf
  mmproj: mmproj-model-f16.gguf

modality:
  - text
  - image

residency: on_demand
```

Future compatible GGUF language or multimodal models should reuse the same worker.

## MLServer Integration

Add a generic `llama_cpp` MLServer runtime.

Lifecycle:

```text
MLServer load
  ↓
supervisor START
  ↓
cerebrate-llama
  ↓
load GGUF/mmproj
  ↓
health/readiness probe
  ↓
READY
```

Unload:

```text
MLServer unload
  ↓
supervisor STOP
```

Docling therefore interacts with the same Cerebrate serving/lifecycle layer as other models.

The AVF Debian guest should contain only lightweight control-plane components:

```text
MLServer
llama_cpp adapter
existing model adapters
configuration
```

PDFs, caches, and GGUF model storage should not live in the guest.

## Android Layout

Use the existing staged-artifact convention, e.g.:

```text
/data/local/tmp/cerebrate/
├── bin/
│   └── cerebrate-llama
└── models/
    └── granite-docling/
        ├── model.gguf
        └── mmproj.gguf
```

Images cross the AVF boundary only for inference and do not become durable Android state.

## Implementation Sequence

1. Install and configure Docling Serve in `/srv/doclet`.
2. Expose it through Caddy at `doclet.home.arpa`.
3. Confirm normal PDF → Markdown/JSON conversion through its real API.
4. Build generic `cerebrate-llama` from the already-proven `libmtmd` path.
5. Add MLServer `llama_cpp` runtime and supervisor lifecycle support.
6. Implement one Docling enrichment plugin calling Cerebrate.
7. Start with the demonstrated math/figure failure cases from the benchmark PDF.
8. Verify graceful fallback when Pixel enrichment is unavailable.
9. Run the existing research PDF end-to-end and compare output/runtime with the baseline.

## Non-Goals

For this implementation:

- no custom Doclet REST API;
- no full-page VLM conversion by default;
- no Granite ONNX/NNAPI work;
- no LiteRT-LM multimodal workaround;
- no Vulkan work;
- no `docling.rs` migration;
- no debugging the upstream Granite `llama-server` defect;
- no larger Substrate ingestion/indexing pipeline yet.

## Success Criteria

`doclet.home.arpa` provides a reliable Docling Serve API that converts real documents to useful Markdown/JSON and can selectively enrich difficult visual elements through a managed Pixel-hosted Granite model.

The implementation also establishes `llama.cpp` as a reusable Cerebrate backend for future GGUF-compatible models without creating a parallel model-serving architecture.