# cerebrate-graph

**Status:** PARTIAL — worker built and verified on the Pixel 6 by manual
launch; supervisor slots and the MLServer canary are written and tested on
the Mac, not yet deployed to the device.

General-purpose ONNX Runtime graph worker, Step 1 of the
[Segmentation and Labeling Lane](../../../design-notes/Cerebrate%20Pixel%206%20%E2%80%94%20Segmentation%20and%20Labeling%20Lane.md).
Loads one `.onnx` model once, with one execution provider chosen at launch,
then serves requests one at a time: any set of named input tensors in, every
output tensor back, plus timing.

A sibling of [`cerebrate-infer`](../cerebrate-infer/README.md), not a
replacement. `cerebrate-infer` stays the production MobileNet/TFLite path;
this worker exists because every model in the segmentation lane needs
arbitrary named inputs and several outputs, which `cerebrate-infer`'s
fixed-size, single-argmax protocol can't carry. Same posture as its siblings:
serial, one model per process, fixed port, `SO_RCVTIMEO` against dead peers
(see `cerebrate-infer`'s README for why), no auth, binds `0.0.0.0` for the
same accepted reasons.

```text
cerebrate-graph <model.onnx> <backend> <port>
```

| Backend | Execution provider |
| --- | --- |
| `cpu` | ORT's CPU provider, 4 intra-op threads |
| `nnapi` | NNAPI with `NNAPI_FLAG_CPU_DISABLED`: NNAPI's slow reference CPU device is off; nodes NNAPI can't take still run on ORT's CPU provider |
| `nnapi16` | `nnapi` plus `NNAPI_FLAG_USE_FP16` |
| `xnnpack` | XNNPACK, with the session's own pool at 1 thread per ORT's guidance |
| `webgpu` | WebGPU (Dawn on Vulkan, the Mali GPU) — compiled into the stock 1.30.0 Android AAR |

Characterization-only environment variables (for hand launches, not the
supervisor): `CEREBRATE_GRAPH_VERBOSE=1` (ORT node placement),
`CEREBRATE_GRAPH_OPT_LEVEL` (0/1/2/99), `CEREBRATE_GRAPH_THREADS`.

Dynamic input shapes are fixed during model preparation (ORT's
`python -m onnxruntime.tools.make_dynamic_shape_fixed`), not by this worker.

## Wire protocol

All integers big-endian.

```text
request  := u32 num_inputs, then num_inputs × tensor
            num_inputs == 0 is a DESCRIBE request
tensor   := u16 name_len, name, u8 dtype, u8 rank, rank × i64 dims,
            u32 data_len, data
```

`dtype` is ONNX Runtime's `ONNXTensorElementDataType` value (1 float32,
2 uint8, 3 int8, 6 int32, 7 int64, 9 bool, 10 float16, ...). `data` is the raw
little-endian elements, row-major, exactly `product(dims) × element_size`
bytes.

Responses use `cerebrate-generate`'s typed frames,
`[u8 type][u32 length][payload]`:

- `DATA` (0) — one frame: `u32 num_outputs` plus that many tensors, in the
  model's output order. For DESCRIBE, a UTF-8 JSON object: model path,
  backend, ORT version, load time, and each input and output's name, dtype,
  and shape (symbolic dims as `-1`, named in `dim_params`).
- `DONE` (1) — `request_id=.. inference_us=.. handle_us=..`. Terminal.
- `ERROR` (2) — failure description. Terminal; no `DONE` follows.

A malformed header (rank over 8, unknown dtype, a tensor over 64 MB, a request
over 128 MB, `data_len` not matching the dims) gets an `ERROR` and the
connection is closed, since framing can't be trusted after it. A well-formed
request that ORT rejects (unknown input name, wrong shape or dtype) gets an
`ERROR` and the connection stays usable.

The Python side of the protocol is
[`cerebrate_graph_protocol.py`](../mlserver/models/cerebrate-graph/cerebrate_graph_protocol.py),
shared by the MLServer adapter and [`graph-client`](graph-client).

## Build (no Bazel — AAR extraction only)

Same approach as the
[onnxruntime-characterization spike](../spikes/onnxruntime-characterization/README.md),
same ORT version.

```bash
curl -sL -o onnxruntime-android.aar \
  "https://repo1.maven.org/maven2/com/microsoft/onnxruntime/onnxruntime-android/1.30.0/onnxruntime-android-1.30.0.aar"
unzip -o onnxruntime-android.aar -d ort_aar
# sha256 of ort_aar/jni/arm64-v8a/libonnxruntime.so:
# df5d25c72a868dca773597c71e2000756d43fe4d70ade516d3693c54e12e0ada

NDK=~/Library/Android/sdk/ndk/27.1.12297006
CLANGXX=$NDK/toolchains/llvm/prebuilt/darwin-x86_64/bin/aarch64-linux-android24-clang++
"$CLANGXX" -std=c++17 -Wall -Wextra -O2 -o cerebrate-graph cerebrate-graph.cc \
  -I ort_aar/headers \
  -L ort_aar/jni/arm64-v8a -lonnxruntime \
  -Wl,-rpath,/data/local/tmp
```

The source also builds on macOS against ORT's `onnxruntime-osx-arm64-1.30.0`
release (the NNAPI backends are compiled out there), which is how the protocol,
error paths, supervisor slots, and MLServer adapter were tested before
touching the device:

```bash
clang++ -std=c++17 -O2 -o cerebrate-graph-macos cerebrate-graph.cc \
  -I onnxruntime-osx-arm64-1.30.0/include -L onnxruntime-osx-arm64-1.30.0/lib \
  -lonnxruntime -Wl,-rpath,$PWD/onnxruntime-osx-arm64-1.30.0/lib
```

## Deploy

The Mac isn't assumed to be on the Pixel's LAN; `overmind-01`'s own
wireless-ADB pairing (`adb -s 192.168.68.60:5555`) is the transport. Push to a
temporary name, then rename, and verify checksums on the device:

```bash
D="adb -s 192.168.68.60:5555"
for f in cerebrate-graph libonnxruntime.so; do
  $D push "$f" "/data/local/tmp/$f.tmp" && $D shell mv "/data/local/tmp/$f.tmp" "/data/local/tmp/$f"
done
$D shell chmod 755 /data/local/tmp/cerebrate-graph
$D shell 'cd /data/local/tmp && sha256sum cerebrate-graph libonnxruntime.so'
```

`libc++_shared.so` is already staged from `cerebrate-infer`'s deploy.
Under supervision the worker runs in one of the `graph1`–`graph3` slots
(ports 8769–8771); see [cerebrate-supervisor](../cerebrate-supervisor/README.md).
For characterization, launch it by hand on a port outside those (18769 was
used), detached the same way the supervisor is:

```bash
$D shell 'cd /data/local/tmp && LD_LIBRARY_PATH=/data/local/tmp nohup setsid ./cerebrate-graph /data/local/tmp/rfdetr-seg-nano.onnx cpu 18769 > graph-test.log 2>&1 < /dev/null &'
```

## Testing

[`graph-client`](graph-client) talks to the worker directly. `local` runs a
model with ORT's Python CPU provider on the Mac to produce reference outputs;
`run --reference` compares the worker's outputs against them element-wise
(max/mean absolute difference, cosine, exact matches, all-zero check — the
discipline that caught the LiteRT GPU readback bug).

```bash
# Mac: reference outputs
uvx --with numpy --with onnxruntime==1.30.0 python -I graph-client local model.onnx --inputs in.npz --save ref.npz
# Debian guest (numpy is in the MLServer venv); the worker is at the AVF gateway
GW=$(ip route show default | awk '{print $3}')
/home/droid/mlserver17-venv/bin/python graph-client describe "$GW" 18769
/home/droid/mlserver17-venv/bin/python graph-client run "$GW" 18769 --inputs in.npz --reference ref.npz --repeat 5
```

The AVF gateway was `10.17.107.249` on 2026-10-23, not the `10.70.217.78`
recorded in earlier READMEs; it changes across VM boots, which is why every
adapter discovers it from the default route.

## Results (2026-10-23)

Run from the Debian guest over the production AVF path, against references
from ORT 1.30.0's Python CPU provider on the Mac. Times are steady-state
medians of 5 (the first one or two requests after a launch are slower).

### MobileNet v1 (quantized canary)

Regenerated from the cataloged `.tflite` (checksum verified) with the spike's
exact `tf2onnx` command — the spike's converted file wasn't kept. Same
deterministic `i % 256` input, class 795 everywhere.

| Backend | Result | Inference | Round trip |
| --- | --- | --- | --- |
| `cpu` | bit-exact (1001/1001) | 9.7 ms | — |
| `nnapi` | bit-exact; logcat: 146/149 nodes, compiled on `google-edgetpu` | 3.4 ms | 4.4 ms |

Load time under `nnapi` is ~1 s (Darwinn compilation) versus 39 ms on CPU,
matching the spike.

### RF-DETR Seg Nano (fp32, 123 MB, browser-perception's pinned file)

Input: browser-perception's `hotel-twin-beds.jpg`, preprocessed as its
adapter does (312×312, ImageNet mean/std). Outputs: `dets` 1×100×4, `labels`
1×100×91, `masks` 1×100×78×78.

| Backend | Result | Inference |
| --- | --- | --- |
| `cpu` | correct: cosine 1.000000 on every output; max abs diff 2.3e-2 in mask logits (ARM vs Apple CPU kernels, not bit-exact across architectures) | **483 ms** |
| `xnnpack` | correct, no crash (the known crash was on a quantized graph) | 1,334 ms — slower, likely because nodes XNNPACK doesn't take run on the single-threaded session pool |
| `nnapi` | refuses to load: ORT would hand NNAPI 879/1,021 nodes in 77 partitions, but the `google-edgetpu` driver reports `Ops supported = 0, not supported = 19` — **the TPU takes no fp32 work** | — |
| `nnapi16` | refuses to load: the driver now reports `Ops supported = 19, not supported = 0`, but **the vendor Darwinn compiler subprocess crashes** inside `libdarwinn_hal.so` (tombstone) and compilation fails. The NNAPI service itself survived; production `cerebrate-infer` verified unaffected right after (class 795, ~1 ms). | — |
| `webgpu` | loads (Dawn initializes on the Mali, Vulkan), then the first run fails with `[Device] is lost` about 11 s in. The worker survives and returns a clean `ERROR`. No GPU driver message in logcat explains the loss. | — |

For comparison, the macOS build on the M1: `cpu` 293 ms, `webgpu` (Metal)
131 ms, both matching the reference.

## Bug found and fixed: Nagle stall on small response frames

The first build wrote each frame header and payload as separate small
writes. Over the AVF path that interacted with the client's delayed ACK:
MobileNet's round trip was ~48 ms for 3.5 ms of handling. `TCP_NODELAY` on
each accepted socket (and in the blocking Python client; asyncio streams
already set it) brought the round trip to 4.4 ms.
