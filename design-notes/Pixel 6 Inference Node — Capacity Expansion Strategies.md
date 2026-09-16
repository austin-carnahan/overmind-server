# Pixel 6 Inference Node — Capacity Expansion Strategies

## Purpose

The Pixel 6 inference node has a useful but constrained memory envelope:

- Debian is the control plane, with roughly 1 GB allocated RAM and less available for workloads.
- Android retains the larger host memory pool and is the only environment with access to the Pixel's native inference acceleration.
- The node therefore should not be treated as a conventional large-memory Linux inference server.

The goal is not to force larger workloads into RAM through fragile swap tricks. Instead, increase the **effective capacity** of the node by reducing what must be resident at once and composing the Pixel with Overmind and external storage.

## 1. Local SSD-backed model and artifact storage

Attach an external SSD to the Pixel through a powered USB-C hub, ideally alongside wired Ethernet and USB-PD power.

Use the SSD for:

- model libraries
- model caches
- document/image working sets
- intermediate artifacts
- embeddings and indexes where appropriate
- temporary staging data

The Pixel's DRAM remains the active working-memory tier; the SSD becomes the large local capacity tier.

Prefer inference runtimes and model formats that support memory-mapped or otherwise lazy/file-backed model loading where practical. This can allow portions of a model to remain storage-backed rather than requiring the entire model file to be permanently resident in RAM.

Conceptually:

```text
External SSD
├── model library
├── cache
└── artifacts
      │
      ▼
on-demand / mmap loading
      │
      ▼
Pixel DRAM
      │
      ▼
Android-native inference
```

This does not increase physical RAM, but it can substantially increase the size of the model library and workflows the node can support.

## 2. On-demand model residency

Treat the Pixel as a job-oriented inference node rather than a host that keeps every model loaded continuously.

The Debian control plane should eventually manage model lifecycle:

```text
job arrives
    ↓
select model
    ↓
load required model
    ↓
perform inference
    ↓
return result
    ↓
release model/resources
```

Only models needed for active work should consume the scarce Android memory budget.

This allows the node to maintain a large catalog of available capabilities while keeping its simultaneous working set small.

It also favors specialized models over a single large general-purpose model: OCR, document layout, embeddings, object detection, classification, image analysis, and similar tasks can each load only when required.

## 3. Partition high-memory workflows across Overmind and the Pixel

Overmind should perform stages that benefit primarily from general-purpose CPU, RAM, storage, or persistent state. The Pixel should perform stages that benefit from its Android-native acceleration.

Example:

```text
Overmind
├── ingest document
├── decompress/rasterize
├── maintain source corpus
└── prepare bounded inference input
         │
         ▼
Pixel 6
├── accelerated CV / ML inference
└── return compact result
         │
         ▼
Overmind
├── aggregate
├── transform
├── index
└── persist
```

This makes the two machines a heterogeneous compute system rather than attempting to make the Pixel self-sufficient.

Candidate Overmind-side responsibilities include:

- large-file ingestion
- PDF rasterization and extraction
- dataset storage
- batching and scheduling
- large intermediate representations
- result aggregation
- indexing
- long-lived databases
- model repository / distribution

Candidate Pixel-side responsibilities include:

- Tensor/GPU/NPU-compatible inference
- bounded image or tensor preprocessing closely coupled to inference
- embeddings
- OCR / vision models
- classifiers and detectors
- other small-to-medium accelerated models

The design rule should be:

> Send the smallest useful input to the Pixel and return the smallest useful result.

Avoid moving large intermediate state onto the Pixel when Overmind can retain it.

## 4. Treat Debian as a lightweight control plane

The Debian guest should remain intentionally small.

Its responsibilities are orchestration rather than heavyweight inference:

- SSH and administration
- systemd services
- job queues
- API/control endpoints
- Python/native utilities
- model selection and lifecycle management
- workload dispatch
- health and thermal monitoring
- communication with Overmind
- communication with Android-native inference services

Do not consume Debian's limited RAM with large models when Android has the larger usable memory pool and the actual accelerator access.

If a supported and reproducible mechanism to reduce the guest's configured memory becomes available later, a 768 MiB guest may be worth benchmarking. This is an optimization, not currently a requirement.

## Capacity model

The resulting node should be thought of as a hierarchy rather than a single memory pool:

```text
                    Overmind
          large RAM / storage / CPU
                       │
                 network boundary
                       │
                       ▼
              Pixel external SSD
          large local model/artifact tier
                       │
                 demand loading
                       │
                       ▼
                Android memory
          active accelerated workloads
                       │
                       ▼
             GPU / Tensor hardware


                Debian guest
           small control-plane tier
```

The important capacity limit is therefore not:

> How large is the entire workload?

It is:

> What is the maximum active working set that must exist on the Pixel at one time?

## Approaches intentionally deprioritized

Do not prioritize remote swap, network-backed swap, aggressive zram tuning, or similar techniques as primary capacity strategies.

They may increase virtual addressable memory or help survive transient pressure, but they do not provide DRAM-class performance and risk turning memory pressure into severe I/O latency.

Prefer workload partitioning, model lifecycle management, local SSD caching, and efficient model formats first.

## Near-term sequence

1. Complete Stage 4 with the simplest real Debian → Android-native inference path.
2. Measure actual Android memory use, accelerator behavior, thermals, and model-loading behavior.
3. Establish realistic active-model size limits.
4. Add workload-driven model unloading/reloading.
5. Add an external SSD only once concrete model/storage requirements justify it.
6. Introduce Overmind-side pipeline partitioning as the first workloads exceed the Pixel's comfortable active-memory envelope.

This keeps capacity improvements driven by measured constraints rather than speculative infrastructure.