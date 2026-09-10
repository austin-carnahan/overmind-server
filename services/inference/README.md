# Inference

Status: deferred capability; no model runtime or hardware requirement is selected.

Expose inference through a configured service endpoint so a later Overmind host
can handle compute without changing project ownership. Validate RAM, architecture,
performance, model requirements, and service isolation before deployment on Pi.

Curated reusable models may live under `/mnt/substrate/models`; project-specific
experimental checkpoints belong to their project. A runtime's private downloaded
weight cache, process state, and service configuration use its supported paths.
Generated custom weights may be irreplaceable and need backup.

Before implementation, record the actual runtime/version, model provenance,
credentials, content/state permissions, required mounts, limits, health checks,
recovery, and rollback. No model-serving daemon is assumed by the scaffold.
