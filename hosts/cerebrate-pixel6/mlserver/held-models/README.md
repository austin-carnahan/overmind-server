# held-models

MLServer model folders that are prepared and tested but deliberately **not
served**: MLServer loads every folder under `models/` at startup, so a
model waits here until its release.

- `edgesam3x-box/` — EdgeSAM-3x box refinement on `cerebrate-hetero`'s
  `hetero2` slot (supervisor, worker and staged files are deployed with the
  combined YOLOE release and inert without this folder). Held on 2026-10-24
  because MLServer 1.7 converts every tensor to a Python list: an EdgeSAM
  request peaks at +196 MB (+3.6 MB per box) in the guest's MLServer, so
  overlapping requests could get production MLServer OOM-killed. Released
  after the image-transport work (compressed image as a BYTES tensor,
  compact mask outputs): `git mv held-models/edgesam3x-box models/` (the
  symlinks resolve from both places), then restart MLServer. Tests and
  numbers: the supervisor README's "Combined deployment".
