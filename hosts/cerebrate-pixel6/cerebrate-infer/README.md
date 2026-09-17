# cerebrate-infer

Minimal persistent inference worker for `cerebrate-pixel6` (Stage 4C — see
[the design notes](../../../design-notes/2026-09-16-pixel6-inference-node.md)
for the full narrative and thermal/latency findings). Loads a TFLite model
and creates the NNAPI delegate (forcing `google-edgetpu`) **once**, then
serves TCP requests one at a time: run inference, return
`request_id`, `top_class`, `top_score`, `inference_us`.

Deliberately narrow: no concurrency, no auth, no model registry. Real
image input as of Stage 5 Phase 3 (see below) — no dummy input anymore.
`InferenceEngine` is a real seam (see `cerebrate-infer.cc`) —
`NnapiTfliteEngine` is implemented; a future `LiteRtEngine` is declared in
the design notes but not implemented, since the LiteRT v2 spike found it
~13× slower on this specific (Tensor G1) hardware — see the design notes'
"Backend decision" section before assuming this should move to LiteRT.

## Build (no Bazel — AAR extraction only)

The legacy TFLite C API + NNAPI delegate ships inside the **Android AAR**
for `org.tensorflow:tensorflow-lite`, not as a standalone download.
**2.17.0 dropped native AAR publishing to Maven Central — use 2.16.1.**

```bash
# 1. Get the AAR and extract headers + the arm64-v8a native library
curl -sL -o tflite.aar \
  "https://repo1.maven.org/maven2/org/tensorflow/tensorflow-lite/2.16.1/tensorflow-lite-2.16.1.aar"
unzip -o tflite.aar -d tflite_aar
# jni/arm64-v8a/libtensorflowlite_jni.so
# headers/tensorflow/lite/...

# 2. The AAR's bundled headers are missing two files — pull them from the
#    matching v2.16.1 tag (not master, to keep ABI/version consistent)
mkdir -p tflite_aar/headers/tensorflow/lite/core/async/c
curl -sL -o tflite_aar/headers/tensorflow/lite/core/async/c/types.h \
  "https://raw.githubusercontent.com/tensorflow/tensorflow/v2.16.1/tensorflow/lite/core/async/c/types.h"
curl -sL -o tflite_aar/headers/tensorflow/lite/core/c/registration_external.h \
  "https://raw.githubusercontent.com/tensorflow/tensorflow/v2.16.1/tensorflow/lite/core/c/registration_external.h"

# 3. Compile as C++ (nnapi_delegate_c_api.h uses C++-only nested-enum
#    syntax despite its extern "C" wrapper — a plain C compile fails)
NDK=~/Library/Android/sdk/ndk/27.1.12297006   # any recent NDK works
CLANGXX=$NDK/toolchains/llvm/prebuilt/darwin-x86_64/bin/aarch64-linux-android24-clang++
"$CLANGXX" -o cerebrate-infer cerebrate-infer.cc \
  -I tflite_aar/headers \
  -L tflite_aar/jni/arm64-v8a -ltensorflowlite_jni \
  -Wl,-rpath,/data/local/tmp \
  -O2
```

Verify the delegate symbols are actually exported before trusting any of
this (confirmed once already, worth re-checking after a version bump):

```bash
$NDK/toolchains/llvm/prebuilt/darwin-x86_64/bin/llvm-nm -D \
  tflite_aar/jni/arm64-v8a/libtensorflowlite_jni.so | grep NnapiDelegate
```

## Deploy

```bash
adb push cerebrate-infer /data/local/tmp/
adb push tflite_aar/jni/arm64-v8a/libtensorflowlite_jni.so /data/local/tmp/
# C++ runtime — needed because we compile with clang++, not plain clang
adb push $NDK/toolchains/llvm/prebuilt/darwin-x86_64/sysroot/usr/lib/aarch64-linux-android/libc++_shared.so /data/local/tmp/
adb push mobilenet_v1_1.0_224_quant.tflite /data/local/tmp/
adb shell chmod +x /data/local/tmp/cerebrate-infer
```

**Run as a kept-alive background task, not `adb shell 'cmd &'`** — a
process backgrounded with `&` inside a single transient `adb shell`
invocation dies when that invocation's connection ends (hit this twice
across this project already). Keep the `adb shell` process itself alive
instead:

```bash
adb shell 'LD_LIBRARY_PATH=/data/local/tmp /data/local/tmp/cerebrate-infer /data/local/tmp/mobilenet_v1_1.0_224_quant.tflite 8765'
```

## Wire protocol (changed in Stage 5 Phase 3)

Each request over the persistent connection is **exactly `input_size`
raw bytes** — the real input tensor (currently: 224×224×3 = 150528
bytes, RGB, uint8, no encoding) — not a bare trigger byte. Framing is
implicit from that fixed, known-at-startup size; there's no length
prefix or delimiter. A client that sends a partial payload and closes
is treated as a dropped connection, not an error response — this
remains a deliberately minimal protocol with no malformed-input
handling. Response format is unchanged: one line,
`request_id=... top_class=... top_score=... inference_us=... handle_us=...`.

## Real bug found and fixed: a dead peer can wedge the whole worker (Stage 5 Phase 4)

Discovered while testing Phase 4's VM-restart recovery path — the first
time this project restarted the guest VM *while an active connection to
`cerebrate-infer` was open*. When the AVF guest is force-stopped or
restarted, its virtual network interface disappears without a clean
FIN/RST — so from the host side, that connection stays **ESTABLISHED
forever** at the TCP level, even though the peer is permanently gone.
Since `cerebrate-infer` is single-threaded and strictly serial (it only
calls `accept()` again after the current client's inner loop exits), a
blocking `read()` on that dead connection never returns and the whole
worker is wedged — every future client, including a fresh one from the
newly-booted guest, queues in the listen backlog forever. Confirmed via
`/proc/<pid>/net/tcp` on the Android host: one `ESTABLISHED` socket to
the guest's old (pre-restart) address, plus several older `CLOSE_WAIT`
entries — almost certainly residue from the same underlying issue during
Stage 4D's earlier, unexplained spontaneous VM deaths, never diagnosed
as a root cause at the time.

Fixed with `SO_RCVTIMEO` (30s) on each accepted client socket: a stalled
read now times out, that one connection is dropped, and the worker loops
back to `accept()` — bounding the damage to one stale request instead of
wedging permanently. Verified empirically: triggered a real VM
force-stop/restart with an active MLServer connection open, and the full
external path (`inference.home.arpa` → Caddy → tunnel → MLServer →
adapter → this worker) recovered automatically, no manual intervention,
in ~16 seconds — a real classification (`"military uniform"`, correct
confidence) succeeded again without anyone touching either service.

## Why this still binds `0.0.0.0` (LAN-reachable by design, investigated and accepted)

`cerebrate-infer`'s port is directly reachable from any LAN device
(`192.168.68.60:8765`), not just from Debian over the AVF gateway. Two
narrower alternatives were investigated and empirically ruled out before
accepting this:

1. **`SO_BINDTODEVICE` on the host-side AVF interface** — would work only
   if that interface's *name* (not its IP) were stable across VM
   restarts. Tested directly: force-stopped and relaunched the VM, and
   the interface name changed from `avf_tap_2051` to `avf_tap_2052`
   (named after the VM's CID, which is documented to change every boot),
   while the IP address happened to stay the same. The opposite of what
   this fix needs — there is no stable device name to bind to.
2. **`AF_VSOCK`** (AVF/crosvm's native host↔guest transport, no IP
   networking at all) — the Debian guest has `/dev/vsock` and Python
   `AF_VSOCK` support, but the host-side device node is
   `crw------- root root`. Confirmed empirically as the unprivileged
   `shell` user (the same user ADB always launches processes as, with no
   root available on this device): `cat /dev/vsock` → `Permission
   denied`. Blocked at the basic file-permission level, before any
   AVF/SELinux ownership layer even applies.

With both ruled out, and OS-level firewalling unavailable without
rooting a device this project has deliberately kept stock (see Stage 1),
the `0.0.0.0` bind stays. This is treated as an accepted architectural
looseness, not a security gap in this project's actual threat model:
Stage 5 Phase 4 already established that LAN/Tailscale reachability
*is* the intended trust boundary (no auth was added at the MLServer
layer for the same reason). A LAN device reaching this port directly
bypasses the intended "always go through Overmind" architecture — which
matters for future multi-node routing — but does not cross into an
untrusted network the rest of this project's design doesn't already
assume is trusted.

This breaks the old "any bytes triggers one inference on a fixed dummy
pattern" behavior from Stage 4C/4D — those throwaway `/tmp` load-test
scripts were never committed to this repo and aren't expected to keep
working. See
[hosts/cerebrate-pixel6/mlserver](../mlserver/README.md#phase-3--real-image-classification-done-2026-09-16)
for the MLServer adapter that does real image decode/resize and speaks
this protocol.

## Test from Debian (raw bytes, not through MLServer)

```python
import socket
s = socket.create_connection(("10.70.217.78", 8765))
s.sendall(bytes(150528))  # a real 224x224x3 uint8 tensor in production
print(s.recv(512))
# b'request_id=1 top_class=... top_score=... inference_us=... handle_us=...\n'
```

`10.70.217.78` is the guest's current AVF NAT gateway address — not
assumed stable across VM restarts (the guest's whole networking stack is
AVF-managed); re-check `ip route` inside the guest if this stops working.
