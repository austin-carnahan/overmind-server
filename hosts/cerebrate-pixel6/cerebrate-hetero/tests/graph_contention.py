"""GPU contention: a graph-mode model (Depth Anything fast, GPU only), a
YOLOE-v8s fast worker (TPU + GPU head) and production MobileNet
(cerebrate-infer, Edge TPU), from the guest. Every output checked: Depth and
YOLOE against their validated outputs bit for bit, MobileNet's probe class.
Phases: each alone, then all three concurrently; then Depth alone sustained,
reported per 10 s window. usage:
  graph_contention.py <host> <depth port> <yoloe port> <infer port> <seconds per phase> <sustained seconds> <data dir> <hetero dir>"""
import sys, socket, threading, time
import numpy as np
sys.path.insert(0, "/home/droid/cg-test/stage/code/cerebrate-graph")
import cerebrate_graph_protocol as protocol
HOST, DP, YP, IP, SECS, SUS, D, HD = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), float(sys.argv[5]), float(sys.argv[6]), sys.argv[7], sys.argv[8]
probe = bytes(i % 256 for i in range(150528))
din = [np.fromfile(f"{D}/depth/inputs/{i}.bin", np.float32).reshape(1, 3, 518, 686) for i in range(8)]
dref = [np.fromfile(f"{D}/depth/pulled/out-fp32-gpu-fp16acc32/{i}_o0.bin", np.float32) for i in range(8)]
yin = [dict(np.load(f"{HD}/in{i}.npz")) for i in range(8)]
yref = [np.load(f"{HD}/out-fast/out{i}.npz") for i in range(8)]


def depth(stop, rec):
    s = socket.create_connection((HOST, DP)); s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1); k = 0
    while not stop.is_set():
        i = k % 8; k += 1
        t = time.perf_counter(); out, done = protocol.call(s, {"pixel_values": din[i]}); dt = (time.perf_counter() - t) * 1000
        rec.append((time.time(), dt, done["inference_us"] / 1000, bool(np.array_equal(out["depth"].ravel(), dref[i]))))


def yoloe(stop, rec):
    s = socket.create_connection((HOST, YP)); s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1); k = 0
    while not stop.is_set():
        i = k % 8; k += 1
        t = time.perf_counter(); out, done = protocol.call(s, yin[i]); dt = (time.perf_counter() - t) * 1000
        rec.append((time.time(), dt, done["inference_us"] / 1000, all(np.array_equal(out[n], yref[i][n]) for n in yref[i].files) and done["backend"] == 1))


def mobilenet(stop, rec):
    s = socket.create_connection((HOST, IP)); s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1); f = s.makefile("rb")
    while not stop.is_set():
        t = time.perf_counter()
        try:
            s.sendall(probe); line = f.readline().decode().strip()
        except (ConnectionError, OSError):
            line = ""
        dt = (time.perf_counter() - t) * 1000
        kv = dict(x.split("=", 1) for x in line.split() if "=" in x)
        if "inference_us" not in kv:   # cerebrate-infer's known reset under sustained load: reconnect, count it
            rec.append((time.time(), dt, 0, None)); s.close()
            s = socket.create_connection((HOST, IP)); s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1); f = s.makefile("rb")
            continue
        rec.append((time.time(), dt, int(kv["inference_us"]) / 1000, int(kv["top_class"]) == 795))


def pct(v, p): v = sorted(v); return v[min(len(v) - 1, int(p * len(v)))]


def run(names, secs):
    fns = {"depth": depth, "yoloe": yoloe, "mobilenet": mobilenet}
    stop = threading.Event(); recs = {n: [] for n in names}
    th = [threading.Thread(target=fns[n], args=(stop, recs[n])) for n in names]
    for t in th: t.start()
    time.sleep(secs); stop.set()
    for t in th: t.join()
    for n in names:
        r = recs[n]; ok = [x[3] for x in r if x[3] is not None]
        print(f"  {n:9s} {len(r):5d} req | round trip p50 {pct([x[1] for x in r], .5):7.1f} p99 {pct([x[1] for x in r], .99):7.1f} ms | "
              f"worker p50 {pct([x[2] for x in r], .5):6.1f} p99 {pct([x[2] for x in r], .99):6.1f} ms | correct {sum(ok)}/{len(ok)}"
              + (f" | resets {sum(1 for x in r if x[3] is None)}" if n == "mobilenet" else ""), flush=True)
    return recs


for n in ("depth", "yoloe", "mobilenet"):
    print(f" alone: {n}"); run([n], SECS)
print(" all three concurrently"); run(["depth", "yoloe", "mobilenet"], SECS * 2)
print(f" depth alone, sustained {SUS:.0f} s (worker inference per 10 s window)")
r = run(["depth"], SUS)["depth"]; t0 = r[0][0]
print("  windows p50 ms:", [round(float(np.median([x[2] for x in r if w <= x[0] - t0 < w + 10])), 1) for w in range(0, int(SUS) - 9, 10)])
