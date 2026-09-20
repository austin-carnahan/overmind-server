# cerebrate-gguf MLServer adapter

Doclet Service V3 Stage 3. Follows the same shape as
[`cerebrate-generate`'s adapter](../cerebrate-generate/README.md) and
[`cerebrate-infer`'s](../cerebrate-infer/cerebrate_infer_runtime.py) —
deliberately a separate, standalone module, no shared base class — but
talks to a worker with a materially different profile: a single request
that takes ~100 seconds, almost entirely vision encoding on this device
(see [`cerebrate-gguf`'s own README](../../cerebrate-gguf/README.md)),
not a millisecond-scale classification or a token-by-token stream.

## Request/response shape

```json
{"inputs": [
  {"name": "image", "shape": [1], "datatype": "BYTES", "data": ["<base64 PNG>"], "parameters": {"content_type": "base64"}},
  {"name": "prompt", "shape": [1], "datatype": "BYTES", "data": ["Convert this page to docling."]}
]}
```

```json
{"outputs": [
  {"name": "text", "datatype": "BYTES", "data": ["<doctag>...</doctag>"]},
  {"name": "elapsed_us", "datatype": "INT64", "data": [102467627]}
]}
```

`image` is optional (matching `cerebrate-gguf`'s own wire protocol,
which supports a text-only request) — omitting it sends no `--image`
flag to `llama-mtmd-cli`. Every real caller today (Docling Serve, via
`doclet-vlm-adapter`) always sends one.

## Verified end to end (2026-09-18)

- `POST /v2/repository/models/cerebrate-gguf/load` genuinely drives
  `cerebrate-supervisor`'s `START` for the `gguf` worker (confirmed via
  the Android host's own `ps`/supervisor `LIST` showing a real new
  `cerebrate-gguf` process on port 8768, not just MLServer reporting
  success).
- `POST /v2/models/cerebrate-gguf/infer` with the real test image from
  [experiments/docling](../../../../experiments/docling/README.md)
  returned the byte-identical DocTags result already proven at every
  earlier layer (`<doctag><picture>...<line_chart></picture></doctag>`),
  in **102.5s** — consistent with every other measurement of this exact
  request throughout this project.

## Real finding: a long-lived connection can drop mid-flight, and recovery needs an explicit reload

Immediately after the first successful ~102s request above, a second
request (from [`doclet-vlm-adapter`](../../../../services/doclet/vlm-adapter/doclet_vlm_adapter.py)'s
Stage 3 test) failed with `cerebrate-supervisor`/`cerebrate-gguf` both
confirmed still healthy and reachable on the Android side, but MLServer's
own log showed:

```text
ConnectionError: cerebrate-gguf at 10.17.107.249:8768 unreachable mid-request
```

Root cause: this adapter reuses one persistent TCP connection across
requests (same pattern as `cerebrate_generate_runtime.py`), and that
connection was dropped somewhere along the AVF virtual network path
during (or between) the two ~100-second-long requests — confirmed **not**
a stale-gateway-address problem, since a fresh raw TCP probe from the
guest to the same address:port succeeded immediately afterward. The
adapter's existing single-retry-then-`self.ready = False` behavior (the
same Phase B Stage 3 pattern already documented for `cerebrate-infer`/
`cerebrate-generate`) did exactly what it's designed to do: reported
reality (`ready=False`, `/v2/models/cerebrate-gguf/ready` → `400`)
instead of silently serving a broken connection.

Recovery is a plain `POST /v2/repository/models/cerebrate-gguf/load`
(confirmed: restored `READY` immediately, and the very next request
succeeded in 104.1s). Not a new bug to fix in this stage — but worth
recording as real, observed behavior specific to this worker's much
longer request duration: a connection sitting open across a ~100s+
request has more opportunity to hit whatever transient AVF network issue
caused this than `cerebrate-infer`'s millisecond-scale or even
`cerebrate-generate`'s multi-second requests do. If this turns out to
recur often in practice, the next step would be characterizing frequency
before deciding whether per-request reconnection (trading a small
latency cost for the drop's blast radius) is worth it over the current
reuse-and-retry-once approach — not attempted here since one occurrence
isn't enough data to justify a design change.

## Stage 4 fix: a transient connection loss shouldn't latch the model unready (2026-09-18)

A real 29-minute, 14-item Docling Serve production run (see
[experiments/doclet-service](../../../../experiments/doclet-service/production-run-2026-09-18))
found that a single transient transport failure early in the job
silently killed every enrichment call after it: `self.ready = False` was
set on *any* connection failure, including an ordinary timeout or a
dropped socket — and MLServer's own REST layer refuses to even attempt
`predict()` once `ready=False`, returning "Model not ready" before this
adapter's own reconnect logic ever got a chance to run. An explicit
external `/load` was the only way to recover.

Fixed by separating three concepts that had been conflated into one flag
(see the module docstring for the full writeup):

- **LOADED** — the supervisor-managed worker exists and the model config
  is valid. Set once in `load()`/`unload()`; this is the only thing
  `self.ready` (MLServer's own visible flag) tracks now.
- **CONNECTED** — this adapter currently holds a usable socket. Transient,
  never externally visible.
- **READY** — a connection can be re-established when needed. Not a
  stored flag at all; `_ensure_connected()` already reconnects lazily on
  the next request once the stale connection is dropped.

A timeout specifically does **not** imply the worker died — the
`llama-mtmd-cli` subprocess may still be genuinely running (confirmed
directly: after a deliberately-forced 15s timeout on a real ~100s
request, `ps` showed `llama-mtmd-cli` still actively computing at 125%
CPU). The fix drops that one connection (so a late response can't be
misread as a later request's response) and fails that one item, without
touching the worker's lifecycle at all — no restart, no supervisor call.
Only a *confirmed* dead worker (checked via the supervisor's own crash
detection) should ever affect LOADED.

**Verified with two real scenarios, not simulated:**

1. **Idle-timeout disconnect, no `/load`.** A real connection went idle
   past `cerebrate-gguf`'s own 30s `SO_RCVTIMEO` between two test calls,
   producing a genuine "unreachable mid-request" error on the next
   request — confirmed `/v2/repository/index` still reported `gguf` as
   `READY` immediately after (no latch), and the *very next* request,
   with zero manual intervention, reconnected automatically and
   succeeded (115.7s, correct DocTags output).
2. **Worker genuinely killed mid-request.** `kill -9` on the Android-side
   worker while `llama-mtmd-cli` was actively running, confirmed via
   `cerebrate-supervisor`'s `STATUS` reporting `EXITED`, restarted
   directly via the supervisor (bypassing MLServer entirely, matching
   how a human operator would recover a genuinely dead worker) — the
   next request succeeded with **no explicit `/load` call**, since
   `self.ready` was never touched and `_ensure_connected()` simply opened
   a fresh connection to the new worker on the same fixed port.

Also fixed in the same pass: `REQUEST_TIMEOUT_S` raised from an initial
240s (Stage 3) to **600s**, after this same production run found real
formula-enrichment calls genuinely exceeding 240s — not a hang, just
less margin than assumed. Overridable per-instance via
`model-settings.json`'s `cerebrate_gguf_request_timeout_s` (used to run
the 15s-timeout test above without waiting out 600 real seconds).
Structured logging (`request_id`, connect/reconnect/timeout/success,
elapsed time) added throughout `_generate()` specifically because this
bug was only diagnosable at all by reading raw log lines after the fact.

## Known operational constraint (timeout layering)

`REQUEST_TIMEOUT_S = 600` (this adapter's own read from `cerebrate-gguf`)
must stay comfortably below `doclet-vlm-adapter`'s own outbound timeout
(630s), which must stay below whatever timeout Docling Serve's job
config uses for `picture_description_api`/`code_formula_custom_config`
(660s recommended) — each outer layer needs margin above the one it
wraps, so the innermost timeout always fires first and produces a clean,
attributable error instead of an outer layer giving up mid-request.
