# Stage 5 — Standardized Pixel Inference Service

## Objective

Complete the current Pixel 6 inference-node expansion by turning the hardware acceleration work already proven on the device into **one real, reusable network service**.

The goal is deliberately narrow:

> Expose a working image-classification service from `cerebrate-pixel6`, using MLServer as the standard serving layer around the existing Pixel-specific Android inference implementation, and make that service accessible to Overmind and clients operating through Overmind.

Do not broaden this stage into a general distributed inference platform, fleet scheduler, model registry, or workflow engine.

---

# Guiding Principle

## Compose existing infrastructure instead of building our own platform

Prefer established serving, health, metrics, and model-management primitives wherever possible.

For Stage 5, use **MLServer** rather than implementing our own:

- inference API;
- health/readiness endpoints;
- model metadata;
- request metrics;
- batching;
- model load/unload semantics.

Pixel-specific code should exist only where the unusual Android/AVF/TPU boundary requires it.

The intended separation is:

```text
Overmind / authorized clients
             │
             │ standard V2 inference interface
             ▼
         MLServer
       Debian guest
             │
             │ thin Pixel runtime adapter
             ▼
      cerebrate-infer
       Android host
             │
             │ NNAPI
             ▼
      google-edgetpu
             │
             ▼
       Tensor G1 TPU
```

MLServer is the serving layer.

`cerebrate-infer` remains the hardware-facing implementation detail.

---

# Scope

## 1. Deploy MLServer in the Debian guest

Install and run MLServer as a normal managed Debian service.

Prefer:

- a reproducible Python environment;
- pinned or explicitly documented dependency versions;
- systemd supervision;
- predictable filesystem locations;
- configuration committed to the existing `cerebrate-pixel6` repository.

Measure and document baseline resource usage because the guest remains memory-constrained.

---

## 2. Implement a thin MLServer custom runtime

Create a custom runtime that translates between:

```text
MLServer / V2 request
```

and:

```text
cerebrate-infer request
```

over the existing AVF host/guest network boundary.

Keep the adapter small.

It should not reimplement:

- TensorFlow Lite;
- NNAPI behavior;
- accelerator selection;
- inference-engine logic;
- generalized workflow orchestration.

Treat it primarily as a protocol and data-shape adapter.

---

## 3. Expose image classification as the first service

Use the already-proven MobileNet path as the first production service.

This stage is about validating the serving architecture, not testing another uncertain model.

The service should accept a real image and return useful classification output such as labels and confidence scores.

Use MLServer's standard V2 representation rather than inventing a Pixel-specific HTTP API.

Image preprocessing and classification postprocessing should live at the most appropriate reusable layer, while accelerator-specific behavior remains behind `cerebrate-infer`.

---

## 4. Expose the service through Overmind

The intended accessibility model is:

```text
authorized client
      │
      ▼
   Overmind
      │
      ▼
cerebrate-pixel6
    MLServer
```

The service should be directly usable by Overmind and reachable remotely through the existing Overmind access architecture.

Do not expose the Pixel directly to the public Internet.

---

# Health, Readiness, Metadata, and Metrics

Use MLServer's built-in facilities wherever possible.

We should be able to determine at least:

- whether MLServer is alive;
- whether the classification model is ready;
- which model/version is being served;
- request success/failure;
- request count and latency where available.

Pixel-specific telemetry may supplement this with:

- TPU temperature;
- Android thermal status;
- `cerebrate-infer` liveness;
- battery temperature.

Keep this supplementation small. Do not create a parallel monitoring framework.

---

# Model Lifecycle

Use MLServer's existing model concepts wherever they fit naturally.

For this stage, establish a reproducible convention for:

```text
model artifact
model name
model version
runtime configuration
labels / metadata
```

and demonstrate it with MobileNet.

If MLServer's load/unload or model-repository behavior maps cleanly onto `cerebrate-infer`, use it.

If the persistent Android worker creates an impedance mismatch with MLServer's lifecycle model, document that mismatch rather than hiding it behind premature abstraction.

Do not introduce a separate model registry yet.

Keep model storage organized so it can later be moved onto a dedicated SSD or other local volume without changing the serving API. Additional storage should initially be treated as a **model/cache tier**, allowing many models to reside locally while only active models consume RAM.

---

# Success Criteria

Pixel inference-node expansion is considered **complete for this pass** when the following are true.

## Functional

From Overmind, we can:

1. query MLServer health/readiness;
2. query model metadata;
3. submit a real image through the standard inference interface;
4. receive useful classification labels/scores;
5. verify that the request executes through:

```text
MLServer
→ custom Pixel runtime
→ cerebrate-infer
→ NnapiTfliteEngine
→ NNAPI
→ google-edgetpu
→ Tensor G1 TPU
```

## Operational

The service:

- runs under normal service supervision;
- starts reproducibly;
- recovers appropriately after a Debian service restart;
- produces useful logs;
- exposes enough health and metrics information to diagnose normal failures;
- requires no USB-connected development workstation for normal operation.

## Reproducibility

The repository contains enough configuration and documentation to recreate the service.

Document:

- dependencies and versions;
- MLServer configuration;
- custom runtime implementation;
- systemd/service definitions;
- model placement;
- network assumptions;
- test commands;
- known lifecycle limitations.

## Scope Discipline

Completion means:

> We have a real, standardized Pixel inference appliance service.

It does **not** require solving future multi-node scheduling, centralized model management, or workflow orchestration.

Those should be introduced only when an actual workload or additional node creates the requirement.

---

# Implementation Philosophy

1. Prefer mature existing components over bespoke infrastructure.
2. Keep Pixel-specific glue as small as possible.
3. Preserve `cerebrate-infer` as the hardware abstraction boundary.
4. Standardize the interface outside that boundary.
5. Measure real services before optimizing them.
6. Add infrastructure only when a demonstrated requirement justifies it.
7. Keep storage and model layout portable so local SSD caching can be added later without redesigning the service.
8. Preserve compatibility with future heterogeneous inference nodes without building that fleet today.

The desired end state is intentionally modest:

> A stock Pixel 6 acts as a stable, remotely accessible Tensor G1 inference appliance on the Overmind network, exposing a standard image-classification service backed by real on-device TPU acceleration.

Once that works reproducibly, declare this round of Pixel inference-node expansion complete.