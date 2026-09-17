# cerebrate-generate

Minimal persistent generation worker for `cerebrate-pixel6` — the
**Session Execution** sibling to [`cerebrate-infer`](../cerebrate-infer/README.md)'s
Graph Execution, per the
[Multi-Runtime Execution Plane](../../../design-notes/Cerebrate%20Pixel%206%20%E2%80%94%20Multi-Runtime%20Execution%20Plane.md).
A deliberately separate process, not a mode of `cerebrate-infer` — the
two have materially different lifecycles (millisecond stateless calls
there vs. seconds-long stateful generation here) and are composed
together only at the MLServer layer, never sharing a binary.

Loads a `.litertlm` model and creates the LiteRT-LM `Engine` **once**,
then serves TCP requests one at a time: create a `Session`, generate
content, return the result text + timing. Deliberately narrow, matching
`cerebrate-infer`'s own scope discipline: no concurrency, no auth, no
streaming yet (synchronous `generate_content`, not
`generate_content_stream` — real chunked streaming is deferred to the
Debian-adapter phase, once the whole pipeline actually needs it).

## Build (no Bazel — prebuilt C API release, not AAR extraction this time)

Unlike the legacy TFLite C API, LiteRT-LM ships a **versioned C API
shared-library prebuilt** directly as a GitHub release asset (as of
v0.16.0) — no AAR unzip trick needed, just download and extract.

```bash
# 1. Get the release asset (multi-platform bundle; only android_arm64 is needed)
curl -sL -o litert_lm_c_api.zip \
  "https://github.com/google-ai-edge/LiteRT-LM/releases/download/v0.16.0/litert_lm_c_api-0.1.0.zip"
unzip -o litert_lm_c_api.zip "lib/android_arm64/*" "include/*" -d litertlm_c
# lib/android_arm64/liblitert-lm.so (39MB)
# include/engine.h, include/conversation.h

# 2. Verify the C API symbols are actually exported before trusting any of
#    this (same discipline as cerebrate-infer's NNAPI delegate check)
NDK=~/Library/Android/sdk/ndk/27.1.12297006
$NDK/toolchains/llvm/prebuilt/darwin-x86_64/bin/llvm-nm -D \
  litertlm_c/lib/android_arm64/liblitert-lm.so | grep litert_lm_engine_create

# 3. Compile as C++ (matches cerebrate-infer.cc's own convention; this
#    file is plain C but named .cc and compiled with clang++)
CLANGXX=$NDK/toolchains/llvm/prebuilt/darwin-x86_64/bin/aarch64-linux-android24-clang++
"$CLANGXX" -o cerebrate-generate cerebrate-generate.cc \
  -I litertlm_c/include \
  -L litertlm_c/lib/android_arm64 -llitert-lm \
  -Wl,-rpath,/data/local/tmp \
  -O2
```

`liblitert-lm.so`'s only `NEEDED` entries are stock Android system
libraries (`libandroid`, `libz`, `libGLESv2/v3`, `libEGL`, `libdl`,
`liblog`, `libm`, `libc`) — nothing extra to push, unlike the legacy
TFLite C API's `libc++_shared.so` dependency.

## Model

Any `.litertlm` file works; validated with
[`litert-community/SmolLM2-135M-Instruct`](https://huggingface.co/litert-community/SmolLM2-135M-Instruct)
(142MB) as the canary — small enough that a failure to initialize would
clearly be a runtime/integration problem, not a "model too large"
problem.

## Deploy

```bash
adb push cerebrate-generate /data/local/tmp/
adb push litertlm_c/lib/android_arm64/liblitert-lm.so /data/local/tmp/
adb push SmolLM2_135M_Instruct.litertlm /data/local/tmp/
adb shell chmod +x /data/local/tmp/cerebrate-generate
```

Same keep-alive caveat as `cerebrate-infer`: run as a kept-alive
background task (`run_in_background: true` on the `adb shell`
invocation itself), never backgrounded with `&` inside a transient
`adb shell` call.

```bash
adb shell 'LD_LIBRARY_PATH=/data/local/tmp /data/local/tmp/cerebrate-generate /data/local/tmp/SmolLM2_135M_Instruct.litertlm cpu 8766'
```

`cerebrate-infer` uses port `8765`; `cerebrate-generate` uses **`8766`**.

## Wire protocol

Each request and response is a **4-byte big-endian length prefix**
followed by that many bytes of UTF-8 text — unlike `cerebrate-infer`'s
fixed-size image tensor, prompt/response text is variable-length and
may contain arbitrary bytes (including newlines), so a length prefix is
used instead of line-delimited or fixed-size framing. This is a
native-worker validation protocol, not the final Debian-facing wire
format — designing that is explicitly a later (Debian-adapter) phase.
Max prompt size is capped at 64KB as a sanity guard.

Same `SO_RCVTIMEO` (30s) protection as `cerebrate-infer` picked up
after Stage 5 Phase 4's wedged-worker bug: a client's network path can
vanish without a clean FIN/RST, and without a timeout a blocking
`read()` on a dead connection would wedge this single-threaded, serial
worker forever.

## Verified (2026-09-17)

Tested from the real Debian guest, over the real production path (AVF
gateway, not a loopback/ADB shortcut), against the persistent worker
(engine loaded once, not per-request):

- Two requests over one reused connection: `"Reply with the word
  hello."` → coherent greeting (3.75s); `"What is the capital of
  France? ..."` → **"The capital of France is Paris."** — correct, not
  just coherent.
- A third request on a fresh new connection (after the first closed)
  succeeded too, confirming the outer `accept()` loop works across
  multiple connections, not just multiple requests within one.
- `request_id` incremented correctly across all three; worker PID
  unchanged throughout (no crash, no restart needed).
- Server-side logged timing matched client-observed elapsed time
  closely (e.g. `generate_us=3751214` vs. 3.75s client-side).
- CPU backend (`cpu` argument) only, this pass — GPU backend was
  already validated functional for this exact model in the throwaway
  feasibility spike (see the design notes' Progress Notes); not
  re-tested against the persistent worker specifically, since that
  wouldn't teach anything new about the worker's own design.

## Not yet done

- GPU backend against the persistent worker specifically (low priority
  — already proven functional in the spike).
- Streaming (`generate_content_stream`) — deferred until the
  Debian-adapter/MLServer phase actually needs incremental output.
- systemd-style supervision, health checks, restart policy — this is
  still a manually-launched foreground `adb shell` process, same as
  `cerebrate-infer` before its own later phases.
- A real MLServer adapter dialing this worker (the Debian-adapter
  phase).
