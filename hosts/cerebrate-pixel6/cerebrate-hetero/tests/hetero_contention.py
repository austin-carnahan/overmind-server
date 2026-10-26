"""Accelerator contention: cerebrate-hetero (YOLOE-v8s fast: TPU backbone +
GPU head) and the production cerebrate-infer (MobileNet on the TPU) under
concurrent demand, from the guest. Phases: MobileNet alone, hetero alone,
both concurrently, both serialized by a client-side lock. MobileNet uses its
deterministic i%256 probe (must classify 795); hetero's outputs are compared
with its solo outputs for the same photo (score and class arrays).
usage: contention.py <host> <hetero port> <infer port> <seconds per phase> <inputs dir>"""
import sys, socket, threading, time, statistics, json
import numpy as np
sys.path.insert(0, "/home/droid/cg-test/mlserver/models/cerebrate-graph")
import cerebrate_graph_protocol as protocol
HOST, HP, IP, SECS, IND = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), float(sys.argv[4]), sys.argv[5]
probe = bytes(i % 256 for i in range(150528))
imgs = [dict(np.load(f"{IND}/in{i}.npz")) for i in range(8)]

def mobilenet(stop, lock, rec):
    s = socket.create_connection((HOST, IP)); s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1); f = s.makefile("rb")
    while not stop.is_set():
        if lock: lock.acquire()
        t = time.perf_counter(); s.sendall(probe); line = f.readline().decode().strip(); dt = time.perf_counter() - t
        if lock: lock.release()
        kv = dict(x.split("=") for x in line.split())
        rec.append((dt * 1000, int(kv["top_class"]), int(kv["inference_us"]) / 1000))

def hetero(stop, lock, rec, ref):
    s = socket.create_connection((HOST, HP)); s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1); k = 0
    while not stop.is_set():
        i = k % 8; k += 1
        if lock: lock.acquire()
        t = time.perf_counter(); out, done = protocol.call(s, imgs[i]); dt = time.perf_counter() - t
        if lock: lock.release()
        same = None
        if ref is not None:
            same = bool(np.array_equal(out["cls"], ref[i]["cls"]) and np.abs(out["score"] - ref[i]["score"]).max() < 1e-6)
        else:
            if i not in rec_ref: rec_ref[i] = {n: out[n].copy() for n in ("cls", "score")}
        rec.append((dt * 1000, done["backend"], done["tpu_us"] / 1000, done["gpu_us"] / 1000, done["inference_us"] / 1000, same))

def pct(v, p): v = sorted(v); return v[min(len(v) - 1, int(p * len(v)))]
def summary(name, xs):
    return f"{name}: n={len(xs)} p50 {pct(xs, .5):.1f} p95 {pct(xs, .95):.1f} p99 {pct(xs, .99):.1f} max {max(xs):.1f} ms"

rec_ref = {}
def phase(label, run_m, run_h, serialize=False, ref=None):
    stop = threading.Event(); lock = threading.Lock() if serialize else None; rm, rh = [], []; ts = []
    if run_m: ts.append(threading.Thread(target=mobilenet, args=(stop, lock, rm)))
    if run_h: ts.append(threading.Thread(target=hetero, args=(stop, lock, rh, ref)))
    for t in ts: t.start()
    time.sleep(SECS); stop.set()
    for t in ts: t.join()
    print(f"== {label}")
    if rm:
        print("   MobileNet round trip", summary("", [r[0] for r in rm])[1:], "| worker inference", summary("", [r[2] for r in rm])[1:],
              f"| class 795 on {sum(r[1] == 795 for r in rm)}/{len(rm)}")
    if rh:
        print("   hetero round trip", summary("", [r[0] for r in rh])[1:], "| inference", summary("", [r[4] for r in rh])[1:])
        print("   hetero TPU stage", summary("", [r[2] for r in rh])[1:], "| GPU stage", summary("", [r[3] for r in rh])[1:],
              f"| backends {sorted(set(r[1] for r in rh))}", (f"| outputs identical to solo on {sum(1 for r in rh if r[5])}/{len(rh)}" if ref is not None else ""))
    sys.stdout.flush()
    return rh

phase("MobileNet alone", True, False)
phase("hetero alone (reference outputs recorded)", False, True)
ref = dict(rec_ref)
phase("concurrent (simultaneous requests)", True, True, ref=ref)
phase("serialized (client-side lock: one request on the TPU at a time)", True, True, serialize=True, ref=ref)
