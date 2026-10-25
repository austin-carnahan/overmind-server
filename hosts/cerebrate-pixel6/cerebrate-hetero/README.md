# cerebrate-hetero

**Status:** DEPLOYMENT PREPARED, SCHEDULED (2026-10-24) — supervisor slot
`hetero1` (port 8772, fixed profiles `yoloe-v8s-fast`/`yoloe-v8s-default`),
MLServer model `yoloe-v8s-pf` (on demand) and the catalog entry are built and
tested side by side with production; the production swap waits for its
window ([runbook](../cerebrate-supervisor/README.md#scheduled-deploy-runbook)).
The staged deployment uses the first build (`bfcb8e8b`); the **serving-worker
build below (`86e1c006`) adds prompt models, per-image caching, compilation
caching and health, and serves YOLOE bit-identically** — whether the
scheduled deploy takes it is open.

Heterogeneous inference worker for the Pixel 6: one model served as a
pipeline of accelerator stages — **stage 1 on the Edge TPU, stage 2 on the
GPU** — or as a single GPU model. Built for YOLOE-v8s prompt-free
(TPU fp16-relaxed backbone + GPU head, 4,585 classes), but nothing in it is
YOLOE-specific: any model split into a TPU-friendly trunk and a GPU stage,
connected by tensors of matching byte size, fits. Sibling of
[`cerebrate-graph`](../cerebrate-graph/README.md) and speaks **its wire
protocol unchanged**, so the same MLServer adapter and `graph-client` serve it.

```text
cerebrate-hetero <port> tpu+gpu <libtensorflowlite_jni.so> <stage1.tflite> <stage2.tflite> <fp32|fp16acc32> [<fallback.tflite> <fp32|fp16acc32>]
cerebrate-hetero <port> gpu <model.tflite> <fp32|fp16acc32>
```

| Mode | Stage 1 | Stage 2 | Fallback |
| --- | --- | --- | --- |
| `tpu+gpu` | Edge TPU: TFLite 2.16.1 + NNAPI delegate pinned to `google-edgetpu`, NNAPI CPU fallback disallowed, **fp16 relaxation** (`allow_fp16`) | GPU: LiteRT 2.3 `CompiledModel`, fp32 or fp16 + fp32 accumulation | optional GPU-only model with the same interface: serves if the TPU stage fails to load, and any request whose TPU stage fails |
| `gpu` | — | GPU (LiteRT 2.3) | — |

**Two runtimes, one process.** The TPU stage needs TFLite 2.16's NNAPI
delegate, which LiteRT 2.3 doesn't ship; both libraries export the same
`TfLite*` C names. [`tpu_stage.cc`](tpu_stage.cc) loads
`libtensorflowlite_jni.so` privately (`dlopen(RTLD_LOCAL)`) and calls it
through function pointers; the library has no dynamic relocations against
the shared names (checked with `llvm-readelf -r`), so its internal calls stay
bound to itself. The worker links LiteRT normally.

**Interface.** One float32 input (`CEREBRATE_HETERO_INPUT`, default
`images`; for YOLOE NHWC `[1,640,640,3]`, letterboxed RGB in 0–1) and named
float32 outputs (`CEREBRATE_HETERO_OUTPUTS`, default
`boxes,score,cls,coef,protos`). Models, buffers and compiled graphs are
created once; stage-1 outputs are matched to stage-2 inputs by byte size.
DESCRIBE (an empty request) returns the configuration as JSON, including
`model` and `backend` for the MLServer adapter's check: the supervisor's
`CEREBRATE_HETERO_MODEL`/`CEREBRATE_HETERO_PROFILE` when set, else the
stage-1 (or only) model path and the mode. DONE carries
`request_id inference_us handle_us backend tpu_us gpu_us`, every value an
integer (the shared protocol parser requires it): `backend` 1 = tpu+gpu,
2 = gpu-fallback (TPU configured but unavailable or failed), 3 = gpu.
Binds only after loading (supervisor readiness = ready to serve);
`SO_RCVTIMEO` 30 s and `TCP_NODELAY` per client, like its siblings.

## YOLOE-v8s configurations (models from spikes/yoloe-tpu)

| Catalog variant | Command | Inference (worker) | Accuracy vs Ultralytics (132 detections) |
| --- | --- | --- | --- |
| `default` | `gpu yoloe-v8s-pf-gpu-nhwc.tflite fp32` | 202 ms | exact (132/132, box/mask IoU 1.0000) |
| **`fast`** | `tpu+gpu <tflite_jni> yoloe-v8s-pf-backbone-tpu-fp32.tflite yoloe-v8s-pf-head-gpu.tflite fp16acc32 yoloe-v8s-pf-gpu-nhwc.tflite fp16acc32` | **73.9 ms** (TPU 12.8 + GPU 60.3) | 132/132, no extras; box IoU ≥ 0.965, mask IoU mean 0.996 |
| GPU-only mixed (internal fallback) | the fallback above, or `gpu yoloe-v8s-pf-gpu-nhwc.tflite fp16acc32` | 107 ms | 132/132 + 1 extra |

Load: `fast` 5.1–5.2 s (TPU compile ~3.8 s); `default` 1.2 s. Resident:
~713 MB for `fast` with its fallback.

## Integration tests (2026-10-24; scripts in [`tests/`](tests/))

- **Served outputs** for the eight photos equal the validated pipeline's
  (132/132). **Startup fallback**: an unloadable TPU model → serves from the
  GPU-only mixed model (logged; 107 ms, its usual accuracy).
- **Contention with production MobileNet** (`cerebrate-infer`, same TPU),
  30 s per phase ([`hetero_contention.py`](tests/hetero_contention.py)):
  MobileNet correct on every response (class 795: 914/914 alone,
  7,338/7,338 concurrent, 1,129/1,129 serialized); its round-trip p99 4.9 ms
  alone → 14.1 ms concurrent (max 36 ms) → 8.1 ms with a client-side
  serializing lock. `cerebrate-hetero` unaffected (inference p50 73 ms, p99
  ≤ 76 ms), outputs identical to its solo outputs (325/325), **no TPU
  recompiles**. A plain lock or bounded queue is enough if MobileNet's tail
  matters; not needed for correctness.
- **Sustained** ([`hetero_sustained.py`](tests/hetero_sustained.py)): 3
  minutes back to back, 1,024 requests — inference p50 72.9–73.2 ms per
  30 s window, p99 ≤ 76 ms (two one-off spikes, 103 and 170 ms), all on
  TPU + GPU, outputs identical throughout; TPU 30 → 55 °C, GPU → 56 °C, big
  CPU cores → 71 °C, back to 35 °C within 30 s; RSS flat at 713 MB, free
  memory ~2.8 GB.
- **Transport**: guest round trip ≈ 175 ms vs 73 ms inference — the fp32
  NHWC image (4.9 MB) in and ~5 MB of outputs out over the AVF path. Sending
  a uint8 image and returning only what post-processing needs would cut it;
  not done yet.
- **Under the supervisor and MLServer** (side by side with production):
  both profiles bit-identical to the runs above, on-demand start, idle
  stop, kill recovery and unload —
  [`hetero_supervisor_chain.py`](tests/hetero_supervisor_chain.py),
  [`hetero_ondemand.py`](tests/hetero_ondemand.py); results in the
  supervisor and MLServer READMEs.
- **Pre-existing, unrelated:** a single connection driven at ~400
  requests/s (≈60 MB/s) to `cerebrate-infer` gets reset roughly once per
  30 s — reproduced with this worker stopped. Clients should reconnect on
  reset.

## Serving worker: prompt models, image cache, compilation cache, health (2026-10-24)

One worker for both validated heterogeneous pipelines (YOLOE-v8s, EdgeSAM),
not a framework: the positional forms above are unchanged; a config file
(`--config`, see the source header; examples in [`configs/`](configs/))
adds:

- **NNAPI compilation caching** for the TPU stage (`nnapi_cache_dir`; token =
  file name + FNV-1a 64 of the model's contents + precision + runtime, so a
  changed model never reaches an old blob — the G1 driver also rejects stale
  ones). EdgeSAM's trunk: cold load 42.7 s, then **0.1 s**; the whole
  worker (TPU + three GPU models) is ready in 2.2 s.
- **A prompt model** run once per prompt against the pipeline's outputs,
  each input sourced from a pipeline output, the request (stacked
  `[N, ...]`), or a constant file (written into its resident buffer once at
  load; pipeline outputs once per request). For EdgeSAM: the box decoder
  against the image embedding, `boxes [N,1,4]` in, `mask_logits
  [N,1,256,256]` + `iou [N,1,1]` out.
- **Per-image cache** of pipeline outputs under a caller's `image_id`
  (int64), LRU, `cache_entries`: `{image, image_id, boxes}` encodes, caches
  and decodes; `{image_id, boxes}` decodes against the cache (refused with
  "send the image again" when evicted); `{image, image_id}` just encodes.
- **Health** in DESCRIBE: requests, pipeline runs, TPU failures, fallback
  runs, prompt runs, cache hits/misses, cached images, errors, last error;
  plus real input shapes and the prompt interface.
- **Readiness** unchanged: binds only after every model is compiled.
- **`tpu_lock`** (optional flock around TPU runs among workers sharing the
  path). Measured: no benefit — the driver already serializes TPU jobs —
  so the example configs leave it off.

The box decoder takes the box itself (prompt encoding in the graph), with
the prompt encoder's 2×128 Gaussian matrix and corner embeddings fed as
**inputs**: baked into the graph, even these tiny constants made the G1 GPU
wrong (mean mask IoU 0.35; exact on the CPU) — lane §4.5 rule 3 holds at any
size.

### Tests (Pixel 6, hand-launched on spare ports; [`tests/`](tests/))

| Test | Result |
| --- | --- |
| EdgeSAM fast, 8 photos × all 132 YOLOE boxes ([`edgesam_worker_test.py`](tests/edgesam_worker_test.py)) | masks vs the original EdgeSAM: worst IoU 0.9441, mean 0.99830 — identical to the validated chain (same 7,392 px); outputs bit-identical across builds |
| single-process latency, worker side (round trip from the guest) | image + 1 box **194 ms** (470), image + 10 boxes **692 ms** (1,006), cached + 1 box 54 ms (58), cached + 10 boxes 646 ms (688); decoder ~55–58 ms per box |
| cache | the 4 most recent images served from the cache, bit-identical; evicted ones refused |
| fallback (TPU model missing) | warning, then every request on the exact GPU fp32 encoder (backend 2): masks exact (1 px), image + 1 box 312 ms |
| YOLOE fast on this build, positional mode ([`yoloe_regression.py`](tests/yoloe_regression.py)) | 8/8 photos bit-identical to the validated outputs |
| contention: EdgeSAM + YOLOE + production MobileNet, 30 s phases, with and without `tpu_lock` ([`hetero_contention3.py`](tests/hetero_contention3.py)) | every output identical to solo, MobileNet 795 on every response, no fallbacks; EdgeSAM p50 195 → 250 ms concurrent (mostly GPU sharing with YOLOE's head; its TPU p50 stays 128 ms), YOLOE p50 78 → 84–115 ms, MobileNet p99 5 → 37 ms (queued behind EdgeSAM's 128 ms TPU job); the lock changes nothing material |
| sustained, 3 min of image + 4 boxes ([`edgesam_sustained.py`](tests/edgesam_sustained.py)) | p50 352–353 ms in every 30 s window, all outputs identical, backend 1 throughout; TPU ≤ 47 °C, GPU ≤ 48 °C, big cores ≤ 76 °C; worker RSS 593 MB afterwards (YOLOE's 708 MB), 2.4 GB free with both running |

The ~260 ms between worker time and round trip is the 12.6 MB fp32 image over
the AVF path — the transport item (uint8 input) is still open.

## Build

See [`CMakeLists.fragment.txt`](CMakeLists.fragment.txt). Push the binary,
the three `.tflite` files, and run with
`LD_LIBRARY_PATH=/data/local/tmp/litert-2.3.0:/data/local/tmp` (LiteRT 2.3
libraries plus `libtensorflowlite_jni.so`, the same TFLite 2.16.1 library
`cerebrate-infer` uses).
