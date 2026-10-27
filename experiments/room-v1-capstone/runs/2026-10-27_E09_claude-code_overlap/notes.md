# E09 — Object overlap and ordering (2026-10-27_E09_claude-code_overlap)

## Attempt

The bed placed four ways so its silhouette crosses the rug and the nightstand, relying on
`overmind-place-on-floor`'s depth stacking; after each placement, the scene with the bed hidden compared
with the original.

## Observed

- **Ordering:** right whenever the placement was physically possible.
  - **P2:** the bed in front of the nightstand.
  - **P4:** the bed over the rug when its front is ahead of it.
  - **P3:** the rug over the skirt's hem when both are about equally near, as in the photo.
- **Stationary pixels:** unchanged in every case (0 px).
- **P1:** a placement mistake. The bed landed inside the nightstand's footprint, and the lamp floats over
  the bed.

## What helped or failed

- **The tie margin (5%) matters:** it kept the rug's existing order in P3, which is the photographed truth.
- **I expected flat rugs to break the lowest-point rule.** In practice they don't here: a cutout rug only
  has its visible pixels, and those lie in front of whatever stands near it.
- **Stacking can't prevent collisions:** nothing checks that the floor at the destination is free.
- **Multi-group undoable moves:** already demonstrated in Experiment 3 (one `gimp_edit_batch`, one Ctrl+Z).

## Reusable rule or open question

Before placing, check the destination footprint is free of other objects (render with a `points` overlay).
Open: a collision warning in the placement procedure.
