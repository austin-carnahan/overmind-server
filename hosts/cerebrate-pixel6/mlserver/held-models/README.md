# held-models

MLServer model folders that are prepared and tested but deliberately **not
served**: MLServer loads every folder under `models/` at startup, so a
model waits here until its release. Empty at the moment.

History: `edgesam3x-box` waited here from 2026-10-24 (MLServer 1.7 turned
every tensor into a Python list: +196 MB per EdgeSAM image request, +3.6 MB
per box) until the image-transport work (photo in, uint8 to the worker,
compact JSON results out) brought that to a flat +28 MB; released with it on
2026-10-25.
