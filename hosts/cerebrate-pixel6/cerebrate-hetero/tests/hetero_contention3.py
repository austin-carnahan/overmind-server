"""TPU contention among two cerebrate-hetero workers and production MobileNet
(cerebrate-infer, same Edge TPU), from the guest: EdgeSAM (image + 1 box per
request, photos cycled; outputs vs its solo outputs), YOLOE-v8s fast (outputs
vs the validated out-fast), MobileNet (deterministic probe, must classify
795). Phases: each alone, then all three concurrently. Whether the two
hetero workers serialize the TPU through tpu_lock depends on how they were
started (run once per configuration; the label says which).
usage: hetero_contention3.py <host> <edgesam port> <yoloe port> <infer port> <seconds per phase> <edgesam dir> <hetero dir> <label>"""
import sys, socket, threading, time
import numpy as np
sys.path.insert(0, "/home/droid/cg-test/mlserver/models/cerebrate-graph")
import cerebrate_graph_protocol as protocol
HOST, EP, YP, IP, SECS, ED, HD, LABEL = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), float(sys.argv[5]), sys.argv[6], sys.argv[7], sys.argv[8]
probe = bytes(i % 256 for i in range(150528))
eph = [dict(np.load(f"{ED}/photo{i}.npz")) for i in range(8)]
yin = [dict(np.load(f"{HD}/in{i}.npz")) for i in range(8)]
yref = [np.load(f"{HD}/out-fast/out{i}.npz") for i in range(8)]
eref = {}

def edgesam(stop, rec):
    s = socket.create_connection((HOST, EP)); s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1); k = 0
    while not stop.is_set():
        i = k % 8; k += 1
        t = time.perf_counter()
        out, done = protocol.call(s, {"image": eph[i]["image"], "image_id": np.array([i], np.int64), "boxes": eph[i]["boxes"][:1]})
        dt = (time.perf_counter() - t) * 1000
        if i not in eref: eref[i] = out["mask_logits"].copy(); same = None
        else: same = bool(np.array_equal(out["mask_logits"], eref[i]))
        rec.append((dt, done["inference_us"] / 1000, done["tpu_us"] / 1000, done["backend"], same))

def yoloe(stop, rec):
    s = socket.create_connection((HOST, YP)); s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1); k = 0
    while not stop.is_set():
        i = k % 8; k += 1
        t = time.perf_counter(); out, done = protocol.call(s, yin[i]); dt = (time.perf_counter() - t) * 1000
        rec.append((dt, done["inference_us"] / 1000, done["tpu_us"] / 1000, done["backend"], all(np.array_equal(out[n], yref[i][n]) for n in yref[i].files)))

def mobilenet(stop, rec):
    s = socket.create_connection((HOST, IP)); s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1); f = s.makefile("rb")
    while not stop.is_set():
        t = time.perf_counter(); s.sendall(probe); line = f.readline().decode().strip(); dt = (time.perf_counter() - t) * 1000
        kv = dict(x.split("=", 1) for x in line.split() if "=" in x)
        if "inference_us" not in kv:   # cerebrate-infer's known reset under sustained ~400 req/s: reconnect, count it
            rec.append((dt, 0, 0, -1, None)); s.close()
            s = socket.create_connection((HOST, IP)); s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1); f = s.makefile("rb")
            continue
        rec.append((dt, int(kv["inference_us"]) / 1000, 0, 0, int(kv["top_class"]) == 795))

def pct(v, p): v = sorted(v); return v[min(len(v) - 1, int(p * len(v)))]
def run(names):
    workers = {"edgesam": edgesam, "yoloe": yoloe, "mobilenet": mobilenet}
    stop = threading.Event(); recs = {n: [] for n in names}
    th = [threading.Thread(target=workers[n], args=(stop, recs[n])) for n in names]
    for t in th: t.start()
    time.sleep(SECS); stop.set()
    for t in th: t.join()
    for n in names:
        r = recs[n]; checked = [x[4] for x in r if x[4] is not None]
        tpu = [x[2] for x in r if x[2]]
        print(f"  {n:9s} {len(r):5d} req | round trip p50 {pct([x[0] for x in r], .5):6.1f} p99 {pct([x[0] for x in r], .99):6.1f} ms | "
              f"worker inference p50 {pct([x[1] for x in r], .5):6.1f} p99 {pct([x[1] for x in r], .99):6.1f} ms"
              + (f" | tpu p50 {pct(tpu, .5):5.1f} p99 {pct(tpu, .99):5.1f} ms" if tpu else "")
              + f" | correct {sum(checked)}/{len(checked)} | backends {sorted({x[3] for x in r})}", flush=True)

print(f"== {LABEL}")
for n in ("edgesam", "yoloe", "mobilenet"):
    print(f" alone: {n}"); run([n])
print(" all three concurrently"); run(["edgesam", "yoloe", "mobilenet"])
