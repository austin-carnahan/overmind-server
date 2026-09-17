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
then serves TCP requests one at a time: create a `Session`,
stream-generate content, relay each chunk as it's produced. There is
exactly one native generation code path — `generate_content_stream` —
used both when a caller wants the full response buffered and when it
wants real incremental output; that choice lives entirely in the
Debian adapter, not duplicated here.

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
  litertlm_c/lib/android_arm64/liblitert-lm.so | grep litert_lm_session_generate_content_stream

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
TFLite C API's `libc++_shared.so` dependency. pthreads are part of
Android's bionic libc, so no separate threading library is needed
either, despite this worker now using real threads (see below).

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

## Wire protocol: typed frames (changed for streaming)

Each request is still a bare 4-byte big-endian length prefix + UTF-8
prompt bytes (unchanged). **Responses changed**: instead of one bare
length-prefixed response, the server now sends a sequence of typed
frames — `[1-byte type][4-byte BE length][payload]`:

- `DATA` (0) — one generated text chunk.
- `DONE` (1) — successful end-of-stream, empty payload.
- `ERROR` (2) — failure description as the payload; terminal, no `DONE`
  follows.

This replaced the original bare-length-prefix response protocol
(one request → one response) from the first Phase 2/3 pass. Breaking
the wire protocol was judged cheap here deliberately: `cerebrate-generate`
is brand new, has exactly one known consumer (the MLServer adapter),
and MLServer is the actual public seam — an internal protocol between
two processes we control is exactly what should be cheap to change,
before it has more than one consumer.

### Why threading, now

`litert_lm_session_generate_content_stream` is **non-blocking and
invokes its callback from a LiteRT-LM-owned background thread**, once
per chunk — the first real multi-threading in this worker (everything
before this was single-threaded and serial, matching `cerebrate-infer`).
A `pthread` mutex/condvar hands control back to the accept-loop thread
once a chunk reports `is_final()` or an error:

```text
accept-loop thread                 LiteRT-LM callback thread
  generate_content_stream() ─────▶   (returns immediately)
  lock, wait on condvar              chunk 1 → DATA frame
                                     chunk 2 → DATA frame
                                     ...
                                     final chunk → DONE frame
                                     lock, set done, signal condvar
  wakes up, continues  ◀─────────────┘
```

Each `LiteRtLmStreamChunk` is **only valid for the duration of the
callback** — its text/error/final-ness are read out immediately, never
held past the call.

Same `SO_RCVTIMEO` (30s) protection as `cerebrate-infer` on the read
side. Max prompt size is capped at 64KB as a sanity guard.

## Verified (2026-09-17)

Real, end-to-end token-by-token streaming from the actual LiteRT-LM
engine, over the typed-frame protocol, from the real Debian guest, over
the real production AVF path — tested with the raw protocol directly
(before touching the Python adapter): chunks arrived at real per-token
decode latency (~20-30ms apart, not artificial delays), correctly
terminated with `DONE`. Worker PID unchanged throughout (no crash, no
deadlock from the new threading).

Full pipeline verification (adapter, MLServer 1.7.1, Caddy,
`inference.home.arpa`) is recorded in the
[MLServer adapter's README](../mlserver/models/cerebrate-generate/README.md)
and the design notes' Progress Notes.

## Real bug found and fixed: generation never terminated on a genuinely fresh process (2026-09-17)

Found via Phase B Stage 2's own lifecycle testing (the first time
anything in this project restarted `cerebrate-generate` fresh and sent
it a request, rather than reusing an already-running, previously-warmed
process): a trivial prompt like "Reply with just the word OK." returned
`Max number of tokens reached` from the very first request. Chased
through three distinct, real fixes rather than stopping at the first
plausible one:

1. **First hypothesis (wrong, but not baseless): the engine's default
   `max_num_tokens` context budget is too small.** Set it explicitly to
   8192 — SmolLM2-135M-Instruct's own real `max_position_embeddings`,
   verified against its published `config.json`, not guessed. The
   failure still happened, just later (~243s of real decode time
   instead of near-instantly) — confirming the ceiling itself wasn't
   the actual problem, generation was running all the way to whatever
   ceiling existed.
2. **Second hypothesis (also real, also insufficient alone): the
   default session doesn't apply the chat/instruct template.** Made
   `apply_prompt_template` explicit (`true`) instead of trusting
   `litert_lm_engine_create_session(engine, NULL)`'s undocumented
   default. No behavior change — ruled out.
3. **Actual root cause, found by capturing the raw generated text
   directly off the wire (bypassing MLServer, which discards partial
   output on an error frame)**: the default sampler is pure greedy
   (argmax) decoding, and this small model gets stuck in a
   deterministic repetition loop — confirmed literally, the model
   repeated "I'm glad you found the information helpful." verbatim for
   over 8,000 tokens straight, never reaching its own EOS token (the
   engine does report exactly one configured stop token — it's real,
   the model just never samples it under pure greedy decoding here).
   Fixed by configuring an actual sampler: `kLiteRtLmSamplerTypeTopP`,
   `top_k=40`, `top_p=0.9`, `temperature=0.7` — conventional values, not
   tuned. `top_p` mode still validates `top_k > 0` internally (confirmed
   via `INVALID_ARGUMENT: k must be positive` when left unset).

Re-verified after the real fix: two different fresh-process requests
both completed in single-digit seconds (not 200+) with a natural `DONE`,
no error, across a genuinely new PID each time. Response *quality* is a
separate, known limitation of a 135M-parameter model (e.g. answered
"What is 2+2?" incorrectly) — not something this fix claims to solve.

This C API (v0.1.0) exposes `RepetitionPenaltyConfig`/`NoRepeatNgramConfig`
constructors and field setters, but no function anywhere that attaches
either one to a session, sampler, or engine — unfinished bindings as of
this release, not a path available here. If a future LiteRT-LM C API
release wires those in, an explicit repetition penalty would likely be a
more principled fix than tuning `top_p`/`temperature` further.

## Not yet done

- No error-path testing (worker down, malformed prompt, oversized
  frame) — only the success path has been verified so far.
- No watchdog timeout on the condvar wait if the callback thread never
  reports done (e.g. an internal engine hang) — same posture as the
  earlier synchronous design's unbounded block, not a new regression,
  but worth hardening if it's ever observed in practice rather than
  guarded against speculatively now.
- GPU backend not re-tested against the streaming path specifically
  (proven functional for this model on the synchronous path in the
  earlier feasibility spike).
