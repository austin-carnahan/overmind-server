# Cerebrate Pixel 6 models: operations

Status: written 2026-10-25. The staged procedures were tested side by side
with production:

- a test supervisor on control port 8777, with its own staging directory;
- a test MLServer on ports 18080–18082.

The registry-serving deployment and the first promotion have not run in
production yet. A real Android reboot has not been rehearsed (see
[Recovery after a reboot](#recovery-after-a-reboot)).

Below, "the phone" is Android on `cerebrate-pixel6`, and "the guest" is its
Debian VM, which runs MLServer. Commands that talk to the phone run on
overmind-01, which holds the adb pairing `192.168.68.60:5555`. From the Mac,
`ssh overmind-01` first.

## How a request reaches a model

```text
models/catalog.yaml        what the model is: artifacts and their sha256, aliases, interface, tasks
models/variants.yaml       how one configuration runs: stages, validation, benchmarks, serving
  serving.worker_config  -> hosts/cerebrate-pixel6/cerebrate-hetero/configs/<model>-<alias>.conf
  serving.slot/profile   -> cerebrate-supervisor (compiled in, or cerebrate-profiles.conf)
  serving.mlserver_model -> hosts/cerebrate-pixel6/mlserver/{models,held-models}/<endpoint>/
client --gRPC/REST--> MLServer (guest) --hook--> supervisor START (on demand) --> cerebrate-hetero worker (phone)
```

A model is served only when every link exists. The validator checks the links
it can see:

- the profile exists in the right slot;
- the worker config names only the variant's own artifacts;
- the endpoint folder serves that profile;
- a staged endpoint is in `held-models/`, a production one in `models/`;
- guest assets match their hashes.

YAML alone never makes a model served.

| Layer | Where | Reference |
| --- | --- | --- |
| Registry, CLI, validator | `models/`, `scripts/cerebrate-models`, `scripts/validate-model-catalog` | [models/README.md](../models/README.md) |
| Model files | `/mnt/models/` on overmind-01, staged flat to `/data/local/tmp/` | [artifact store](../models/README.md#artifact-store-mntmodels-on-overmind-01) |
| Worker | `cerebrate-hetero`; graph mode for the registry models | [cerebrate-hetero](../hosts/cerebrate-pixel6/cerebrate-hetero/README.md#graph-mode-declarative-model-chains-registry-serving-staged-2026-10-25) |
| Supervisor | slots, profiles, admission | [cerebrate-supervisor](../hosts/cerebrate-pixel6/cerebrate-supervisor/README.md#registry-serving-profiles-file-admission-eight-gpu-slots-prepared-2026-10-25-deploy-scheduled) |
| MLServer | adapter, hooks, contracts | [mlserver](../hosts/cerebrate-pixel6/mlserver/README.md#registry-endpoints-eight-gpu-models-staged-in-held-models-prepared-2026-10-25) |
| Watchdogs | overmind-01 timers | [overmind-01](../hosts/overmind-01/README.md) |

## Discover models

```bash
scripts/cerebrate-models                          # every model: aliases, variant statuses, endpoint
scripts/cerebrate-models show owlv2-b16           # artifacts + hashes, every variant, limitations
scripts/cerebrate-models variants --status staged
scripts/cerebrate-models tasks                    # task selections and whether each is available
scripts/cerebrate-models resolve relative-depth@default   # a task selection; <model>@<alias> resolves a model alias
scripts/cerebrate-models endpoints                # staged + production MLServer endpoints only
scripts/cerebrate-models investigations           # closed work: read before reopening anything
```

They run from any checkout with `pyyaml`. The validator and the tests also
need `jsonschema`; [models/README.md](../models/README.md) has the venv
command.

## Health and readiness

Run on overmind-01:

```bash
A="adb -s 192.168.68.60:5555"
curl -s -f localhost:8500/v2/health/ready && echo MLServer ready      # reverse tunnel to the guest's HTTP port
curl -s -X POST -H 'Content-Type: application/json' -d '{}' localhost:8500/v2/repository/index   # every model and its state
printf 'LIST\n\n' | timeout 5 $A shell nc -w 3 127.0.0.1 8767         # slots: RUNNING / STOPPED, pid, profile
$A shell grep MemAvailable /proc/meminfo
$A shell dumpsys thermalservice | sed -n '/Current temperatures from HAL/,/cooling devices/p' | grep -E 'mName=(TPU|G3D|VIRTUAL-SKIN),'
```

**Healthy at rest:**

- Every model in `models/` is READY.
- The pinned workers (`infer`, `generate`, `gguf`, `graph3`) are RUNNING.
- Every on-demand slot (`hetero*`, `gpu-*`) is STOPPED unless it served a
  request in the last 10 minutes (5 for OWLv2).
- At least 3 GB is free.
- TPU and GPU are below 45 °C.

**READY and RUNNING are different things.** An on-demand model is READY with
no worker. READY means it *can* start one. The real test is a request: the
first one starts the worker, which takes 1.4–9.5 s depending on the model.

A worker's own view comes from DESCRIBE, an empty request on its port. The
`cerebrate-graph` client in the guest sends it.

## Add a new model

The full walkthrough, with a template, is
[models/README.md → Onboarding](../models/README.md#onboarding-a-validated-model).
In short:

1. Register.
2. Store.
3. Stage.
4. Write the worker config.
5. Prove fidelity at the worker.
6. Write the adapter hook.
7. Add the profile.
8. Hold the endpoint.
9. Run the side-by-side MLServer test.
10. Promote in a window.

Each step leaves the registry valid.

## Validate a variant

**Prerequisites:**

- The validated model files are in the store and staged.
- The reference outputs exist. The spike that produced the model also
  produced them.
- The phone has at least 3 GB free and nothing heavy running.

**Steps:**

1. Start a test worker on a test port. Production is unaffected.

   ```bash
   hosts/cerebrate-pixel6/cerebrate-hetero/tests/worker_launch.sh <port> <config>
   ```

2. Run the raw fidelity check against the validated device outputs:
   [`graph_fidelity.py`](../hosts/cerebrate-pixel6/cerebrate-hetero/tests/graph_fidelity.py).
   The expected result is bit-identical. If it isn't, the difference must be
   explained and within the validation's metric.
3. Run the photo-path check:
   - [`photo_models_check.py`](../hosts/cerebrate-pixel6/cerebrate-hetero/tests/photo_models_check.py);
   - or the model's `*_photo_check.py`, against the original model's outputs
     on the same photos.

   This proves the guest preprocessing reproduces the reference.
4. Sample resources while the checks run:
   [`resource_sampler.sh <port> <stop-file>`](../hosts/cerebrate-pixel6/cerebrate-hetero/tests/resource_sampler.sh).
   It records:
   - the free-memory drop;
   - the worker's RSS;
   - its peak.
5. Record the results:
   - a dated section in `experiments/pixel6/results.md`;
   - the variant's `validation`, `benchmarks` and `resources` in
     `models/variants.yaml`, each with `record:
     experiments/pixel6/results.md#<heading-anchor>`.

   Use `measure: worker` for the worker's own time and `round-trip` through
   MLServer. Anything not measured stays `null`.

**Verification:**

- `scripts/validate-model-catalog` passes.
- `python3 -m unittest discover -s models/tests` passes.
- The variant shows `validated` in `scripts/cerebrate-models show <model>`.

**Rollback:** revert the registry edit. A test worker leaves nothing behind
once it is killed.

A numerically different configuration of an already validated variant is
always a **new variant id**, never an edit. Changing the numerics of a
production variant requires a regression run against its validation set
first.

## Enable serving: stage an endpoint beside production

**Prerequisites:**

- The variant is `validated`.
- Its worker config and hook exist.
- Its files are staged (`scripts/stage-model <model>`).

**Steps:**

1. Add its slot and profile to
   [`cerebrate-profiles.conf`](../hosts/cerebrate-pixel6/cerebrate-supervisor/cerebrate-profiles.conf):
   - one slot per model, on the next free port above 8782;
   - the floor = the measured drop + 1000 MB.
2. Create `hosts/cerebrate-pixel6/mlserver/held-models/<endpoint>/`, copying a
   neighbour:
   - `model-settings.json`;
   - the symlinks `cerebrate_graph_runtime.py` and
     `cerebrate_graph_protocol.py` → `../../models/cerebrate-graph/…`.
3. Set the variant to `status: staged` with `serving: {worker_config, slot,
   profile, mlserver_model}`.
4. Run the validator.
5. Test side by side:
   1. Run the test supervisor build (`-DCONTROL_PORT=8777
      -DSTAGING_DIR="/data/local/tmp/cerebrate-stage"`) from
      `/data/local/tmp/cerebrate-stage/`. That directory holds the profiles
      file, configs, and symlinks to the staged models.
   2. Run a test MLServer in the guest on ports 18080–18082 from a copy of the
      held settings, with `cerebrate_graph_supervisor_port: 8777`.
   3. Run [`mlserver_staged_test.py`](../hosts/cerebrate-pixel6/cerebrate-hetero/tests/mlserver_staged_test.py).

   The test MLServer command:

   ```bash
   cd ~/cg-test/stage/mlserver && nohup env MLSERVER_PARALLEL_WORKERS=0 MLSERVER_HOST=127.0.0.1 \
     MLSERVER_HTTP_PORT=18080 MLSERVER_GRPC_PORT=18081 MLSERVER_METRICS_PORT=18082 \
     MLSERVER_GZIP_ENABLED=false MLSERVER_GRPC_MAX_MESSAGE_LENGTH=33554432 \
     /home/droid/mlserver17-venv/bin/mlserver start models > mlserver.log 2>&1 < /dev/null &
   ```

**Verification:** the staged test passes for the model, and production is
unchanged: its MLServer MainPID and `NRestarts`, and `LIST` on port 8767.

**Rollback:** delete the held folder and the profile lines, and revert the
variant. Nothing has reached production.

## Promote a staged endpoint

This needs a window. It runs one endpoint at a time, and only after the
[registry-serving deployment](../hosts/cerebrate-pixel6/cerebrate-supervisor/README.md#deployment-runbook-window-required-nothing-below-has-run-in-production).
That deployment puts the new supervisor, worker, profiles file and Pillow 13
in place.

**Order** (decided 2026-10-25):

1. `depth-anything-v2-small`, then `mi-gan-512`. These are the simplest GPU
   paths: one graph, prepare/finish hooks.
2. The rest one at a time: `dinov2-s14`, `yoloe-11s-pf`, `rf-detr-seg-nano`,
   `sam2.1-hiera-tiny` (FP32 only), `efficientsam3-rvm` (fast only),
   `owlv2-b16`.

Never more than one per step. Never activate several at once: separate GPU
processes serialize, and YOLOE's median went from 78 to 248 ms beside Depth.
On-demand residency with idle stops keeps few workers resident, and the
admission floors bound memory. Two configurations are `serving_blocked` and
are never promoted: EfficientSAM3 FP32 (memory) and SAM 2.1 reduced precision
(unresolved 0.963).

**Prerequisites:**

- Push authorized.
- At least 3 GB free on the phone.
- No other heavy job on the phone.

**Steps:**

1. In the repo:
   1. `git mv hosts/cerebrate-pixel6/mlserver/held-models/<m> hosts/cerebrate-pixel6/mlserver/models/<m>`.
   2. In the moved folder, re-point both symlinks:
      `ln -sf ../cerebrate-graph/cerebrate_graph_runtime.py` (and `_protocol.py`).
   3. Set the variant to `status: production`.
   4. If the model is now a task's served `default` and `fallback`, set the
      task to `available: true`.
   5. Run the validator and the tests, then commit and push.
2. In the guest: `git pull --ff-only`.
3. Load the endpoint:
   `curl -s -X POST localhost:8500/v2/repository/models/<m>/load` (from
   overmind-01) → HTTP 200. No restart is needed; MLServer picks up the new
   folder. This was tested on the test MLServer.

**Verification:**

- `/v2/models/<m>/ready` returns 200 and the slot is still STOPPED.
- Record the phone's free memory (`grep MemAvailable /proc/meminfo` over adb)
  before the gate.
- Run the promotion gate in the guest:

  ```bash
  SUPERVISOR_PORT=8767 ~/mlserver17-venv/bin/python3 \
    mlserver_staged_test.py 127.0.0.1:8081 127.0.0.1:8080 10.61.209.60 ~/cg-test/stage/data --only <m>
  ```

  It checks, in order:
  - **correctness:** the model's fidelity checks;
  - **unloading:** unload stops the worker and the model isn't READY; load
    makes it READY again with no worker;
  - **contention:** the model's result is unchanged while production YOLOE
    and MobileNet run concurrently, and so are theirs. It reports YOLOE's
    median alone and contended.

  Every check must pass. The endpoint ends loaded.
- **Memory:** run `resource_sampler.sh <port> <stop-file>` on overmind-01
  beside the gate. The worker's peak and the free-memory drop should be close
  to the staged figures (results), and free memory must stay above 1 GB.
- Record the gate's output in the lane plan's progress notes.
- 10 minutes later (5 for OWLv2), the slot is STOPPED and the model is READY.

**Rollback (demote):**

1. `curl -X POST localhost:8500/v2/repository/models/<m>/unload`. Its worker
   STOPs.
2. Revert the commit and pull in the guest.

The production endpoints are untouched either way.

## Disable serving

**To disable temporarily:** unload the endpoint, as in the demotion above. It
stays unloaded until the next MLServer restart or a load.

**To disable permanently:** demote it, then set the variant back to
`validated` and drop its `serving` block. The profile can stay; an unused
profile is inert.

Either way, the task selections must still validate.

## Recovery after a reboot

> **Not unattended, and not yet rehearsed.** After an Android reboot,
> `adb tcpip` mode is off, and every automatic step below depends on it.
> Someone has to re-enable it by hand (step 1). Only then do the watchdogs
> recover the VM and the supervisor. Don't describe this node as
> self-recovering after a reboot until that adb prerequisite is solved (for
> example, by an on-device service). Test the sequence in a maintenance
> window before relying on it.

What survives an Android reboot:

- `/data/local/tmp`: the staged models, binaries, configs, the profiles file,
  and the NNAPI compilation cache. Workers load from the cache, so a TPU
  stage's first load is about 2 s instead of minutes.
- The guest's disk.

What doesn't survive:

- `adb tcpip` mode;
- the Debian VM (the Terminal app);
- the supervisor and every worker.

1. **adb.** Re-enable tcpip mode from a machine with USB or wireless-debugging
   access: `adb tcpip 5555`. `pixel-adb-reconnect.timer` on overmind-01 then
   reconnects within 30 s. Until this step nothing below can happen; nothing
   is automatic before it.
2. **VM.** `pixel-vm-watchdog` relaunches the Terminal app once MLServer has
   been unreachable for 3 minutes and `crosvm` isn't running. To do it by
   hand: `adb shell am start -n
   com.android.virtualization.terminal/.new2.ui.MainActivity`. MLServer
   starts under systemd when the guest boots.
3. **Supervisor.** Once the registry deployment installs it,
   `pixel-supervisor-watchdog` starts the supervisor within a minute.
   - If MLServer came up first, its pinned models failed to load. The watchdog
     reloads every model that isn't READY.
   - If MLServer comes up later, its own startup loads them.

   Without the watchdog, start the supervisor by hand with the
   [Deploy](../hosts/cerebrate-pixel6/cerebrate-supervisor/README.md#deploy)
   command, then `sudo systemctl restart cerebrate-mlserver` in the guest.

**Verification:** the [health checks](#health-and-readiness) above, plus one
request each to MobileNet and to an on-demand endpoint.

**Failure modes** the watchdog deliberately bounds:

- It starts the supervisor at most once per 2 minutes. A broken binary or
  profiles file can't turn into a loop: it logs the supervisor's last lines
  and waits (`journalctl -u pixel-supervisor-watchdog`).
- It kills only orphaned `cerebrate-hetero` workers from its own directory.
  Pinned workers left over from a crashed supervisor keep serving: their ports
  are busy, so the new supervisor reports them as unmanaged listeners rather
  than starting duplicates.
- A model is READY only when MLServer's load succeeded. The adapter checks the
  worker's DESCRIBE against the expected model and profile. An on-demand
  model is READY without a worker by design (see above).

## Benchmarks

| Script | What it measures |
| --- | --- |
| `graph_fidelity.py` | Worker time per request (`inference_us` in DONE), from the guest over the AVF path. |
| `mlserver_staged_test.py` | Round trips through MLServer, cold and warm. |
| `resource_sampler.sh` | Memory, run beside either of the above. |
| [`graph_contention.py`](../hosts/cerebrate-pixel6/cerebrate-hetero/tests/graph_contention.py) | Concurrent load: a GPU model, a TPU+GPU model and production MobileNet, each alone and then all three at once, with every output checked. Then a sustained run, reported per 10 s window. |

Bounded runs only:

- 20 s phases and at most 60 s sustained;
- a temperature reading before and after;
- stop if G3D passes 60 °C or free memory falls under 1.5 GB.

Record every run in `experiments/pixel6/results.md` and reference it from the
variant's `benchmarks` with the right `measure`:

| `measure` | Meaning |
| --- | --- |
| `device` | Synchronized on the phone. |
| `worker` | The worker's own time. |
| `round-trip` | Through MLServer. |
| `summed` | Calculated from stages. |
| `connected` | One connected pipeline. |

The current numbers:

- `scripts/cerebrate-models show <model>`;
- the [registry-serving results](../experiments/pixel6/results.md#2026-10-25--registry-serving-eight-gpu-models-staged-beside-production).

## Troubleshooting

| Symptom | Cause | Action |
| --- | --- | --- |
| `could not start gpu-… on demand: supervisor refused START: ERROR: profile … needs N MB free` | Admission: another model holds memory. | Expected under load; the model stays READY. Retry after the other model's idle stop, or unload it. Never lower a floor without a new measurement. |
| `… cerebrate-supervisor unreachable` | The supervisor is down. | Check `LIST`. The watchdog restarts it within a minute; otherwise use the Deploy command. |
| A request failed once, then works | The worker was lost (killed, or an orphan was cleared). | The adapter already retried once. A second loss fails the request. Check `supervisor.log` and `<slot>.supervisor.log` (e.g. `gpu-depth.supervisor.log`) in `/data/local/tmp`. |
| `ERROR: port … already has an unmanaged listener` | A worker survived its supervisor. | For on-demand workers the watchdog kills it on its next restart. By hand: kill the `cerebrate-hetero` whose parent is 1. Never kill a pinned worker that is serving. |
| `image_id … not cached; send the image again` | SAM 2.1 and EfficientSAM3 cache per worker, and a worker restart or idle stop clears the cache. | The client resends the photo. |
| The supervisor won't start; its log says `FATAL: profiles file line N` | A malformed `cerebrate-profiles.conf`. | Restore the repo copy; the validator parses it. |
| Outputs differ from validation | Something changed in a library or the preprocessing. | Re-run the model's photo check. Pillow must be 13.0.0 (`python3 -c 'import PIL; print(PIL.__version__)'` in the venv). |
| MLServer READY but every request fails | The guest can't reach the phone (AVF gateway). | `ip route` in the guest. The adapter discovers the gateway at load, so restart MLServer after a VM network change. |
| The phone is hot, or many slots are RUNNING | Several on-demand models are in use. | GPU work from separate processes serializes: YOLOE p50 78 → 248 ms beside Depth. Let idle stops free the slots; unload rarely used endpoints. |

## Stop conditions

Stop and roll back, don't push on, when any of these happen:

- free memory under 1 GB;
- a pinned worker or the VM restarts;
- MobileNet fails;
- G3D or the TPU stays above 60 °C;
- the same failure happens twice.
