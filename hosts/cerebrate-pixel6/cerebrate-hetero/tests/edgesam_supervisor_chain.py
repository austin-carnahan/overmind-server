"""EdgeSAM through cerebrate-supervisor's hetero2 slot (a test supervisor on
its own control port): error paths (each slot refuses the other model's
profiles, model/profile mismatch), edgesam3x-fast START (cold or from the
NNAPI compilation cache, timed), DESCRIBE, all 8 photos x their boxes
(outputs saved per box for edgesam_decoder_accuracy.py), STOP + START again
(cache), edgesam3x-default, idempotent START, conflict, STOP.
usage: edgesam_supervisor_chain.py <host> <control port> <edgesam dir (photo*.npz)> <out dir>"""
import sys, os, socket, time
import numpy as np
sys.path.insert(0, "/home/droid/cg-test/mlserver/models/cerebrate-graph")
import cerebrate_graph_protocol as protocol
HOST, CP, D, OUT = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
T = "/data/local/tmp/"
FAST = dict(worker="hetero2", model=T + "edgesam3x-enc-tpu-fp32.tflite", backend="edgesam3x-fast")
DEFAULT = dict(worker="hetero2", model=T + "edgesam3x-enc-gpu.tflite", backend="edgesam3x-default")
photos = [dict(np.load(f"{D}/photo{i}.npz")) for i in range(8)]

def sup(cmd, **f):
    msg = ("\n".join([cmd] + [f"{k}: {v}" for k, v in f.items()]) + "\n\n").encode()
    with socket.create_connection((HOST, CP), timeout=5) as s:
        s.settimeout(150); s.sendall(msg); s.shutdown(socket.SHUT_WR); b = b""
        while (c := s.recv(4096)): b += c
    return b.decode().strip()

def check(name, resp, want):
    ok = resp.startswith(want); print(f"{'PASS' if ok else 'FAIL'} {name}: {resp[:140]}", flush=True); return ok

def serve(prof, outdir):
    os.makedirs(outdir, exist_ok=True)
    s = socket.create_connection((HOST, 8773)); s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    desc, _ = protocol.call(s, {})
    ok = desc["model"] == prof["model"] and desc["backend"] == prof["backend"]
    print(f"  DESCRIBE model={desc['model']} backend={desc['backend']} tpu={desc['tpu']} fallback={desc['fallback']} nnapi_cache={desc['nnapi_cache']} "
          f"load {desc['load_us']/1e6:.1f} s (TPU {desc['tpu_load_us']/1e6:.1f} s)", flush=True)
    k, inf1, backends = 0, [], set()
    for i, p in enumerate(photos):
        out, done = protocol.call(s, {"image": p["image"], "image_id": np.array([i], np.int64), "boxes": p["boxes"]}); backends.add(done["backend"])
        for j in range(len(p["boxes"])):
            out["mask_logits"][j].tofile(f"{outdir}/{k}_o0.bin"); out["iou"][j].tofile(f"{outdir}/{k}_o1.bin"); k += 1
    for _ in range(5):
        _, done = protocol.call(s, {"image": photos[0]["image"], "image_id": np.array([0], np.int64), "boxes": photos[0]["boxes"][:1]}); inf1.append(done["inference_us"] / 1000)
    _, dc = protocol.call(s, {"image_id": np.array([0], np.int64), "boxes": photos[0]["boxes"][:1]})
    print(f"  {k} boxes served, backend codes {sorted(backends)}; image + 1 box {np.median(inf1):.0f} ms (worker), cached + 1 box {dc['inference_us']/1000:.0f} ms", flush=True)
    s.close()
    return ok

r = [check("hetero2 refuses a YOLOE profile", sup("START", worker="hetero2", model=T + "yoloe-v8s-pf-backbone-tpu-fp32.tflite", backend="yoloe-v8s-fast"), "ERROR"),
     check("hetero1 refuses an EdgeSAM profile", sup("START", worker="hetero1", model=FAST["model"], backend="edgesam3x-fast"), "ERROR"),
     check("profile/model mismatch", sup("START", **dict(FAST, model=DEFAULT["model"])), "ERROR")]
for label, prof in (("edgesam3x-fast", FAST), ("edgesam3x-fast again (cache)", FAST), ("edgesam3x-default", DEFAULT)):
    t = time.time(); r.append(check(f"START {label}", sup("START", **prof), "OK")); print(f"  START took {time.time() - t:.1f} s", flush=True)
    r.append(serve(prof, f"{OUT}/{prof['backend']}{'-restart' if 'again' in label else ''}"))
    if "default" in label:
        r.append(check("START again (idempotent)", sup("START", **prof), "OK"))
        r.append(check("START other profile (conflict)", sup("START", **FAST), "ERROR"))
    r.append(check("STOP", sup("STOP", worker="hetero2"), "OK"))
print(f"{sum(map(bool, r))}/{len(r)} checks passed")
