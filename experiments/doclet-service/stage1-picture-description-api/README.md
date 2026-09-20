# Doclet Service Stage 1 — picture_description_api proof

Stage 1 of the
[Doclet Service V3 implementation sequence](../../../design-notes/Doclet%20Service%20—%20Implementation%20Design%20V3.md#stage-1--prove-the-enrichment-path-end-to-end-with-a-dummy-backend-done):
prove that Docling Serve's `do_picture_description` / `picture_description_api`
config actually reaches a remote OpenAI-compatible endpoint with a real image
payload and that the response actually lands in the output document — before
building `cerebrate-gguf`, the supervisor extension, or the
`inference.home.arpa` adapter.

## Result: proven, with one real contract detail found along the way

A real async conversion job through a real, pinned Docling Serve v1.34.0
instance, converting `experiments/docling/input/sampling-variance-CFR.pdf`
with `do_picture_description=True` and `picture_description_api` pointed at
a dummy local HTTP endpoint, produced:

- 3 real HTTP POSTs to the dummy endpoint, each carrying an actual
  base64-encoded PNG crop of a real picture region from the PDF (not a
  placeholder or a health-check ping — confirmed via the dummy's own
  request logging, image sizes 69–153 KB);
- the dummy's fixed response text landing in **both** the structured
  output (`pictures[i].meta.description.text` and the legacy
  `pictures[i].annotations[].text`) **and** the final `md_content` markdown
  the client actually receives.

This confirms the whole path end to end: Docling Serve's async job API →
picture crop → real outbound HTTP call → OpenAI-compatible response parsing
→ result attached to the document → surfaced in the markdown output. No
custom Docling plugin needed, exactly as V3 concluded from reading the
source — this is Docling Serve's own already-tested mechanism.

## One real, useful discrepancy found and fixed

The first run (before the fix below) reported `do_picture_description`
completing "successfully" but every picture's description text came back
as an **empty string**, with `provenance: 'not-implemented'`. That
provenance value is a red herring, not an error — it's a fixed default
string set by `PictureDescriptionBaseModel.__init__` regardless of which
backend runs (see `docling/models/picture_description_base_model.py`), not
an indicator that this code path is unfinished.

The real cause was in Docling Serve's own log, not silently swallowed:

```text
ERROR docling.utils.api_image_request - Error, could not process request: 1 validation error for OpenAiApiResponse
created
  Field required [type=missing, input_value={'id': 'dummy-1', 'object'...
```

`docling/utils/api_image_request.py`'s `api_image_request()` validates the
remote response against `OpenAiApiResponse`
(`docling/datamodel/base_models.py`), which requires `id`, `choices`, AND
`created` (a Unix timestamp) — the dummy's first response body omitted
`created`, entirely plausible for a hand-rolled OpenAI-compatible server,
and Docling's `except Exception` handler in the same function silently
returns an empty-string result on ANY validation failure rather than
surfacing it to the job's `error_message` or failing the job. Adding
`"created": int(time.time())` to the dummy's response body fixed it
immediately, confirmed by rerunning the identical job.

**This is a real contract requirement for Stage 3's `inference.home.arpa`
adapter**, not just a test-harness bug: any OpenAI-compatible endpoint
Docling Serve talks to must return `id`, `created`, and `choices` (with
`message.role`, and either `message.content` or
`message.reasoning_content`/`tool_calls`, plus `finish_reason`) or the
enrichment silently no-ops with an empty description and no error visible
anywhere except Docling Serve's own log — worth an explicit test in Stage 3
so this isn't rediscovered by staring at empty output.

## Environment note (same fix as the earlier Docling experiment)

Docling Serve's startup failed the first time with
`ImportError: libGL.so.1: cannot open shared object file` from
`docling_ibm_models`' `cv2` import — the identical
`opencv-python`/headless issue already found and fixed in
[experiments/docling](../../docling/README.md) on this same host. Fixed by
installing `opencv-python-headless` and uninstalling `opencv-python`
(uv treats them as the same install location, so a plain `uv pip install
opencv-python-headless` alongside the existing `opencv-python` briefly
breaks `cv2` entirely until the GUI variant is explicitly removed and
headless reinstalled).

## Deployment note: `/mnt/doclet` was the wrong shape, corrected to a container

This spike originally installed Docling Serve into a bare `uv`-managed
venv at `/mnt/doclet/venv`, backed by a new SSD bind mount
(`/mnt/disks/ssd1/doclet` -> `/mnt/doclet`), reasoning by analogy to the
`/mnt/models`/`/mnt/substrate`/`/mnt/library`/`/mnt/downloads` bind-mount
convention in [storage-layout.md](../../../design-notes/storage-layout.md).

That analogy doesn't hold: those `/mnt/<name>` mounts are for **shared,
cross-service, non-Docker-owned** storage (a model cache several things
read, a media library, ...), not a single service's own runtime/state.
Every actual service in this repo (`services/<name>/`, e.g.
[paperclip](../../../services/paperclip/README.md)) deploys as a
Docker Compose fragment against a pinned upstream image, with its state
under `/var/lib/overmind/<name>/` — itself already SSD-backed via the
existing `/mnt/disks/ssd1/var-lib-overmind` bind mount, so no new mount is
needed at all. Docling Serve also publishes an official multi-arch
`ghcr.io/docling-project/docling-serve-cpu` image, so there's no reason to
build/install from source on-host either.

The corrected shape lives in the V3 design doc's "Overmind Deployment"
section: `services/doclet/compose.yaml`, pinned image, state at
`/var/lib/overmind/doclet/`. **The `/mnt/doclet` bind mount created for
this spike should be torn down** (remove the `/etc/fstab` line, `umount`,
remove the now-empty `/mnt/disks/ssd1/doclet` and `/mnt/doclet`
directories) once Stage 1's artifacts here are confirmed sufficient and
nothing still depends on the venv install — not done automatically as
part of writing this note, since it touches `/etc/fstab` and needs the
same sudo access the original setup did.

None of this affects the actual finding above: the `picture_description_api`
round trip and the `OpenAiApiResponse` contract requirement are properties
of Docling Serve's own code, verified by directly reading and exercising
it, independent of how it happens to be packaged for this test.

## Reproduce

```bash
# on overmind-01, inside /mnt/doclet
export DOCLING_SERVE_ENABLE_REMOTE_SERVICES=true
export XDG_CACHE_HOME=/mnt/doclet/cache/xdg
export TORCH_HOME=/mnt/doclet/cache/torch
export HF_HOME=/mnt/models/huggingface
venv/bin/docling-serve run --port 5001 &

venv/bin/python3 dummy_vlm_endpoint.py &   # this directory's dummy endpoint

venv/bin/python3 run_stage1_test.py sampling-variance-CFR.pdf
```

`stage1_result.json` in this directory is the actual saved result from the
real run described above (`pictures[2..4].meta.description.text` all read
`DUMMY_ENRICHMENT_MARKER: this text proves the picture_description_api
round trip works.`; `pictures[0..1]` were below
`picture_description_area_threshold` and correctly skipped).

Full conversion time on the Pi 4 for this ~15-page PDF with the standard
pipeline plus picture description: 349 seconds. Not optimized or
characterized further here — Stage 4 covers end-to-end runtime comparison
against the [experiments/docling](../../docling/README.md) baseline.

## What's next

Stage 2 ([cerebrate-supervisor extension + `cerebrate-gguf` +
acceptance test](../../../design-notes/Doclet%20Service%20—%20Implementation%20Design%20V3.md#stage-2--cerebrate-gguf--supervisor-extension--acceptance-test))
does not depend on anything here beyond this proof existing — it builds
the Android-side worker independently. Stage 3 is where this stage's
`picture_description_api` contract (the OpenAI-response-shape requirement
found above) becomes a concrete implementation requirement for
`inference.home.arpa`.
