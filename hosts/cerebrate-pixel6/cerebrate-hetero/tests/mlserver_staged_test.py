"""The staged GPU models through the whole serving path, beside production: a
test cerebrate-supervisor (control port 8777, its own staging directory and
cerebrate-profiles.conf) and a test MLServer (gRPC) loading the held-models
settings with the test supervisor's port. Checks, per model: READY before any
worker runs; the first request starts the worker on demand (cold start), the
second is warm; raw outputs bit-identical to the validated device outputs
(where they fit gRPC's 32 MiB); final results as the direct runs; then
admission (a profile refused while EfficientSAM3 holds memory, the model stays
READY and serves once memory is back), unload. The idle-stop check (OWLv2's
worker stops after its test idle window) waits up to 150 s and runs only with
IDLE_STOP_CHECK=1: a checkpoint check, not a routine one (runbook).
With --only <model>[,<model>...] it is the promotion gate for endpoints
already loaded (production: gRPC 8081, HTTP 8080, SUPERVISOR_PORT=8767), per
model: the fidelity checks; unload stops the worker and the model is not
READY, load makes it READY again with no worker; then contention -- the
model's result while CONTENTION_MODEL (default yoloe-v8s-pf, the production
YOLOE) and MobileNet (the cerebrate-infer endpoint, mobilenet_probe.py) serve
concurrently through the same MLServer: every result equal to its solo
result, MobileNet class 795, YOLOE's median latency reported. Memory is read on the phone (runbook).
No admission or idle-stop test.
usage: [SUPERVISOR_PORT=8777] mlserver_staged_test.py <grpc host:port> <http host:port> <gateway> <data dir> [--only <models>]"""
import sys, os, json, time, socket, base64, urllib.request
import numpy as np, grpc, cv2
from mlserver.grpc import dataplane_pb2 as pb, dataplane_pb2_grpc as pbg

GRPC, HTTP, GW, D = sys.argv[1:5]
ONLY = sys.argv[6].split(",") if len(sys.argv) > 6 and sys.argv[5] == "--only" else None
SUP_PORT = int(os.environ.get("SUPERVISOR_PORT", "8777"))
CONTENTION_MODEL = os.environ.get("CONTENTION_MODEL", "yoloe-v8s-pf")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mobilenet_probe  # noqa: E402
PROBE_PNG = base64.b64encode(mobilenet_probe.probe_png())
stub = pbg.GRPCInferenceServiceStub(grpc.insecure_channel(GRPC, options=[("grpc.max_send_message_length", 33554432), ("grpc.max_receive_message_length", 33554432)]))
MODELS = ["depth-anything-v2-small", "mi-gan-512", "dinov2-s14", "yoloe-11s-pf", "sam2.1-hiera-tiny", "rf-detr-seg-nano", "efficientsam3-rvm", "owlv2-b16"]
SLOT = {"depth-anything-v2-small": "gpu-depth", "mi-gan-512": "gpu-migan", "dinov2-s14": "gpu-dinov2", "yoloe-11s-pf": "gpu-yoloe11s",
        "sam2.1-hiera-tiny": "gpu-sam2", "rf-detr-seg-nano": "gpu-rfdetr", "efficientsam3-rvm": "gpu-esam3", "owlv2-b16": "gpu-owlv2"}
results = []


def check(name, ok, note=""):
    results.append((name, bool(ok))); print(f"{'PASS' if ok else 'FAIL'} {name}{': ' + note if note else ''}", flush=True)


def supervisor(cmd, **fields):
    with socket.create_connection((GW, SUP_PORT), timeout=200) as s:
        s.sendall(("\n".join([cmd] + [f"{k}: {v}" for k, v in fields.items()]) + "\n\n").encode()); s.shutdown(socket.SHUT_WR)
        return b"".join(iter(lambda: s.recv(4096), b"")).decode()


def slot_state(slot):
    return supervisor("STATUS", worker=slot).split()[1]


def want(model):
    return ONLY is None or model in ONLY


def load(model):
    urllib.request.urlopen(urllib.request.Request(f"http://{HTTP}/v2/repository/models/{model}/load", data=b"{}", method="POST"), timeout=180)


def unload(model):
    urllib.request.urlopen(urllib.request.Request(f"http://{HTTP}/v2/repository/models/{model}/unload", data=b"{}", method="POST"), timeout=60)


def ready(model):
    try:
        return urllib.request.urlopen(f"http://{HTTP}/v2/models/{model}/ready", timeout=10).status == 200
    except Exception:
        return False


def infer(model, raw=False, params=None, **inputs):
    req = pb.ModelInferRequest(model_name=model)
    if raw:
        req.parameters["output"].string_param = "raw"
    for k, v in (params or {}).items():
        req.parameters[k].string_param = str(v)
    for name, v in inputs.items():
        if isinstance(v, list):   # BYTES elements
            req.inputs.add(name=name, datatype="BYTES", shape=[len(v)])
            req.raw_input_contents.append(b"".join(len(x).to_bytes(4, "little") + x for x in v))
        else:
            req.inputs.add(name=name, datatype={np.dtype("float32"): "FP32", np.dtype("int64"): "INT64"}[v.dtype], shape=list(v.shape))
            req.raw_input_contents.append(np.ascontiguousarray(v).tobytes())
    t = time.perf_counter(); r = stub.ModelInfer(req, timeout=300); ms = (time.perf_counter() - t) * 1000
    out = {}
    for o, b in zip(r.outputs, r.raw_output_contents):
        out[o.name] = json.loads(b[4:]) if o.datatype == "BYTES" else np.frombuffer(b, {"FP32": np.float32, "INT64": np.int64, "INT32": np.int32}[o.datatype]).reshape(list(o.shape))
    return out, ms


photo = lambda i, d="stage-photos": open(f"{D}/{d}/photo{i}.jpg", "rb").read()
same = lambda ref_dir, i, outs: all(np.array_equal(np.fromfile(f"{ref_dir}/{i}_o{k}.bin", v.dtype), v.ravel()) for k, v in enumerate(outs))

# 1. READY with no workers
if ONLY is None:
    check("all eight READY, no worker started", all(ready(m) for m in MODELS) and all(slot_state(SLOT[m]) == "STOPPED" for m in MODELS))
else:
    check(f"{','.join(ONLY)} READY", all(ready(m) for m in ONLY))

# 2. per model: cold start, warm, fidelity
lat = {}
if want("depth-anything-v2-small"):
    o, cold = infer("depth-anything-v2-small", raw=True, photo=[photo(0)])
    ok = 0; warm = []
    for i in range(8):
        o, ms = infer("depth-anything-v2-small", raw=True, photo=[photo(i)]); warm.append(ms); ok += same(f"{D}/depth/pulled/out-fp32-gpu-fp16acc32", i, [o["depth"]])
    res, _ = infer("depth-anything-v2-small", photo=[photo(0)]); d = res["result"]["depth"]
    check("depth: raw 8/8 bit-identical to the validated fast outputs", ok == 8, f"{ok}/8; cold {cold:.0f} ms, warm median {np.median(warm):.0f} ms; result png16 {d['width']}x{d['height']}")
    lat["depth-anything-v2-small"] = (cold, np.median(warm))
    if ONLY is None: unload("depth-anything-v2-small"); check("unload depth-anything-v2-small: worker stopped", slot_state(SLOT["depth-anything-v2-small"]) == "STOPPED")

if want("mi-gan-512"):
    ps, warm = [], []
    for i in range(8):
        res, ms = infer("mi-gan-512", photo=[photo(i)], mask=[open(f"{D}/migan-serve/mask{i}.png", "rb").read()]); warm.append(ms)
        got = cv2.imdecode(np.frombuffer(base64.b64decode(res["result"]["result"]), np.uint8), cv2.IMREAD_COLOR)[..., ::-1].astype(np.float64)
        ref = np.load(f"{D}/migan-serve/ref{i}.npy").astype(np.float64)
        region = cv2.imdecode(np.frombuffer(open(f"{D}/migan-serve/mask{i}.png", "rb").read(), np.uint8), cv2.IMREAD_GRAYSCALE) >= 128
        ps.append(10 * np.log10(255 ** 2 / max(((got - ref) ** 2)[region].mean(), 1e-12)))
    check("mi-gan: removed-region PSNR vs the author's pipeline as direct (fast >= 44.6 dB)", min(ps) >= 44.5, f"worst {min(ps):.1f} dB; first (cold) {warm[0]:.0f} ms, warm median {np.median(warm[1:]):.0f} ms")
    lat["mi-gan-512"] = (warm[0], np.median(warm[1:]))
    if ONLY is None: unload("mi-gan-512"); check("unload mi-gan-512: worker stopped", slot_state(SLOT["mi-gan-512"]) == "STOPPED")

if want("dinov2-s14"):
    ok, warm = 0, []
    for i in range(8):
        o, ms = infer("dinov2-s14", raw=True, photo=[photo(i)]); warm.append(ms); ok += same(f"{D}/dino448/pulled/out-erf-gpu-fp32", i, [o["patch_tokens"]])
    res, _ = infer("dinov2-s14", photo=[photo(0)])
    e = np.frombuffer(base64.b64decode(res["result"]["embedding"]["data"]), "<f4")
    check("dinov2: raw 8/8 bit-identical; embedding = mean of the patch tokens", ok == 8 and e.size == 384, f"{ok}/8; cold {warm[0]:.0f} ms, warm {np.median(warm[1:]):.0f} ms")
    lat["dinov2-s14"] = (warm[0], np.median(warm[1:]))
    if ONLY is None: unload("dinov2-s14"); check("unload dinov2-s14: worker stopped", slot_state(SLOT["dinov2-s14"]) == "STOPPED")

if want("yoloe-11s-pf"):
    ok, warm = 0, []
    for i in range(8):
        o, ms = infer("yoloe-11s-pf", raw=True, photo=[photo(i)]); warm.append(ms)
        ok += same(f"{D}/yoloe/gpu/out-11s-gpu", i, [o[n] for n in ("boxes", "score", "cls", "coef", "protos")])
    res, _ = infer("yoloe-11s-pf", photo=[photo(0)])
    check("yoloe-11s: raw 8/8 bit-identical", ok == 8, f"{ok}/8; {len(res['result']['detections'])} detections on photo 0; cold {warm[0]:.0f} ms, warm {np.median(warm[1:]):.0f} ms")
    lat["yoloe-11s-pf"] = (warm[0], np.median(warm[1:]))
    if ONLY is None: unload("yoloe-11s-pf"); check("unload yoloe-11s-pf: worker stopped", slot_state(SLOT["yoloe-11s-pf"]) == "STOPPED")

if want("sam2.1-hiera-tiny"):
    ref, k, worst, flipped, warm, cached_same = np.load(f"{D}/sam-photos/ref_masks.npy"), 0, 1.0, 0, [], True
    for i in range(4):
        w, h = __import__("PIL.Image").Image.open(f"{D}/sam-photos/photo{i}.jpg").size
        boxes = np.array([[b[0] * w, b[1] * h, b[2] * w, b[3] * h] for b in [[0.25, 0.35, 0.75, 0.95], [0.05, 0.05, 0.55, 0.60]]], np.float32)
        o, ms = infer("sam2.1-hiera-tiny", raw=True, photo=[photo(i, "sam-photos")], image_id=np.array([i], np.int64), boxes=boxes); warm.append(ms)
        for j in range(2):
            g, r = o["masks"][j, 0] > 0, ref[k] > 0; k += 1
            for c in range(3):
                u = (g[c] | r[c]).sum(); worst = min(worst, (g[c] & r[c]).sum() / u if u else 1); flipped += int((g[c] != r[c]).sum())
        oc, _ = infer("sam2.1-hiera-tiny", raw=True, image_id=np.array([i], np.int64), boxes=boxes)
        cached_same &= np.array_equal(oc["masks"], o["masks"])
    check("sam2.1 (default): masks exact vs the original (8 boxes x 3), cached image identical", worst == 1.0 and flipped == 0 and cached_same, f"worst IoU {worst:.4f}, {flipped} px; cold {warm[0]:.0f} ms, warm {np.median(warm[1:]):.0f} ms")
    lat["sam2.1-hiera-tiny"] = (warm[0], np.median(warm[1:]))
    if ONLY is None: unload("sam2.1-hiera-tiny"); check("unload sam2.1-hiera-tiny: worker stopped", slot_state(SLOT["sam2.1-hiera-tiny"]) == "STOPPED")

if want("rf-detr-seg-nano"):
    ok_a = ok_b = 0; warm = []; ndet = 0
    for i in range(8):
        o, ms = infer("rf-detr-seg-nano", raw=True, photo=[photo(i)]); warm.append(ms)
        ok_a += same(f"{D}/rf-check-fp16acc32/outA", i, [o["a_enc_cls"], o["a_delta"], o["a_memory2"]])
        ok_b += same(f"{D}/rf-check-fp16acc32/outB", i, [o["boxes"], o["logits"], o["masks"]])
        res, _ = infer("rf-detr-seg-nano", photo=[photo(i)]); ndet += len(res["result"]["detections"])
    check("rf-detr (fast): graph A and B 8/8 bit-identical to the validated outputs", ok_a == 8 and ok_b == 8, f"A {ok_a}/8, B {ok_b}/8, {ndet} detections; cold {warm[0]:.0f} ms, warm {np.median(warm[1:]):.0f} ms")
    lat["rf-detr-seg-nano"] = (warm[0], np.median(warm[1:]))
    if ONLY is None: unload("rf-detr-seg-nano"); check("unload rf-detr-seg-nano: worker stopped", slot_state(SLOT["rf-detr-seg-nano"]) == "STOPPED")

if want("efficientsam3-rvm"):
    exp = json.load(open(f"{D}/../esam3_expect.json"))
    counts = [1, 1, 2, 2, 3, 2, 2, 1, 4, 1, 1]; got_counts, warm = [], []
    for n, smp in enumerate(exp["samples"]):
        res, ms = infer("efficientsam3-rvm", photo=[photo(smp["photo"])], image_id=np.array([smp["photo"]], np.int64), prompts=[smp["prompt"].encode()]); warm.append(ms)
        got_counts.append(len(res["result"]["prompts"][0]["detections"]))
    res2, ms2 = infer("efficientsam3-rvm", image_id=np.array([7], np.int64), prompts=[b"laptop", b"bed"])
    check("efficientsam3 (fast): 20 detections as the validated chain; a cached image takes 2 more prompts", got_counts == counts and len(res2["result"]["prompts"]) == 2,
          f"{sum(got_counts)} detections; photo + 1 prompt: cold {warm[0]:.0f} ms, warm {np.median(warm[1:]):.0f} ms; cached 2 prompts {ms2:.0f} ms")
    lat["efficientsam3-rvm"] = (warm[0], np.median(warm[1:]))

# 3. admission: EfficientSAM3 still resident -> OWLv2 refused (needs 3000 MB free), model stays READY
VOCAB = [b"a bed", b"a pillow", b"a lamp", b"a wall sconce", b"a suitcase", b"a backpack", b"a handbag", b"a towel", b"a chair", b"a sofa", b"a table", b"a curtain",
         b"a window", b"a picture frame", b"a mirror", b"a television", b"a person", b"a dog", b"a potted plant", b"a rug", b"a laptop", b"a blanket", b"a door", b"a cabinet"]
if ONLY is None:
    try:
        infer("owlv2-b16", photo=[photo(0)], queries=VOCAB); refused = False; msg = "served"
    except grpc.RpcError as exc:
        refused, msg = True, exc.details()
    check("admission: OWLv2 refused while EfficientSAM3 holds memory; still READY", refused and ready("owlv2-b16") and slot_state("gpu-owlv2") != "RUNNING", msg[:160])
    print("  LIST:", " | ".join(l for l in supervisor("LIST").splitlines() if "RUNNING" in l))
    # free it: unload EfficientSAM3 through MLServer (its worker STOPs)
    unload("efficientsam3-rvm")
    check("unload: EfficientSAM3's worker stopped, model not ready", slot_state("gpu-esam3") == "STOPPED" and not ready("efficientsam3-rvm"))
if want("owlv2-b16"):
    total, warm = 0, []
    for i in range(8):
        res, ms = infer("owlv2-b16", photo=[photo(i)], queries=VOCAB); warm.append(ms)
        total += sum(len(q["detections"]) for q in res["result"]["queries"])
    check("owlv2: serves once memory is back; 75 detections as the validated run", total == 75, f"{total}; cold {warm[0]:.0f} ms, warm {np.median(warm[1:]):.0f} ms")
    lat["owlv2-b16"] = (warm[0], np.median(warm[1:]))
if ONLY is None and os.environ.get("IDLE_STOP_CHECK") == "1":
    # 4. idle stop (the test settings use 60 s for OWLv2)
    t0 = time.time()
    while slot_state("gpu-owlv2") == "RUNNING" and time.time() - t0 < 150:
        time.sleep(5)
    check("idle stop: OWLv2's worker stopped after its idle window, model still READY", slot_state("gpu-owlv2") == "STOPPED" and ready("owlv2-b16"), f"after {time.time() - t0:.0f} s")
# 5. promotion gate: unload/load cycle and contention with production YOLOE + MobileNet
if ONLY is not None:
    import threading
    sw, sh = __import__("PIL.Image").Image.open(f"{D}/sam-photos/photo0.jpg").size
    sam_boxes = np.array([[b[0] * sw, b[1] * sh, b[2] * sw, b[3] * sh] for b in [[0.25, 0.35, 0.75, 0.95], [0.05, 0.05, 0.55, 0.60]]], np.float32)
    ONE = {"depth-anything-v2-small": lambda: dict(photo=[photo(0)]),
           "mi-gan-512": lambda: dict(photo=[photo(0)], mask=[open(f"{D}/migan-serve/mask0.png", "rb").read()]),
           "dinov2-s14": lambda: dict(photo=[photo(0)]),
           "yoloe-11s-pf": lambda: dict(photo=[photo(0)]),
           "sam2.1-hiera-tiny": lambda: dict(photo=[photo(0, "sam-photos")], image_id=np.array([0], np.int64), boxes=sam_boxes),
           "rf-detr-seg-nano": lambda: dict(photo=[photo(0)]),
           "efficientsam3-rvm": lambda: dict(photo=[photo(0)], image_id=np.array([0], np.int64), prompts=[b"bed"]),
           "owlv2-b16": lambda: dict(photo=[photo(0)], queries=VOCAB)}
    for m in ONLY:
        unload(m)
        check(f"{m}: unload stops its worker, model not READY", slot_state(SLOT[m]) == "STOPPED" and not ready(m))
        load(m)
        check(f"{m}: load: READY again, no worker until a request", ready(m) and slot_state(SLOT[m]) == "STOPPED")
        solo, _ = infer(m, **ONE[m]())
        y_solo, _ = infer(CONTENTION_MODEL, photo=[photo(1)])
        y_ms_solo = [infer(CONTENTION_MODEL, photo=[photo(1)])[1] for _ in range(3)]
        stop, y_rec, mn_rec = threading.Event(), [], []

        def yoloe_loop():
            while not stop.is_set():
                r, ms = infer(CONTENTION_MODEL, photo=[photo(1)]); y_rec.append((r == y_solo, ms))

        def mobilenet_loop():
            while not stop.is_set():
                mn_rec.append(mobilenet_probe.classify(stub, PROBE_PNG)[0] == 795)

        threads = [threading.Thread(target=yoloe_loop), threading.Thread(target=mobilenet_loop)]
        for t in threads:
            t.start()
        same_m = [infer(m, **ONE[m]())[0] == solo for _ in range(3)]
        stop.set()
        for t in threads:
            t.join()
        check(f"{m}: contention with {CONTENTION_MODEL} + MobileNet: all results unchanged",
              all(same_m) and y_rec and all(ok for ok, _ in y_rec) and mn_rec and all(mn_rec),
              f"{m} {sum(same_m)}/3, {CONTENTION_MODEL} {sum(ok for ok, _ in y_rec)}/{len(y_rec)} "
              f"(median {np.median(y_ms_solo):.0f} ms alone, {np.median([ms for _, ms in y_rec]):.0f} ms contended), MobileNet {sum(mn_rec)}/{len(mn_rec)}")
print("LATENCY (cold first request incl. worker start, warm median), ms:", json.dumps({k: [round(a), round(b)] for k, (a, b) in lat.items()}))
print(f"{sum(ok for _, ok in results)}/{len(results)} checks passed")
