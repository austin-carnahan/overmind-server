"""Sustained execution check for cerebrate-hetero: back-to-back requests over
the eight photos for a fixed time; per window: inference / TPU / GPU / round
trip percentiles, backend, and whether outputs still equal the first pass.
Thermals and memory are sampled separately on the host side.
usage: sustained.py <host> <port> <seconds> <window seconds> <inputs dir>"""
import sys, socket, time
import numpy as np
sys.path.insert(0, "/home/droid/cg-test/mlserver/models/cerebrate-graph")
import cerebrate_graph_protocol as protocol
HOST, PORT, SECS, WIN, IND = sys.argv[1], int(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4]), sys.argv[5]
imgs = [dict(np.load(f"{IND}/in{i}.npz")) for i in range(8)]
s = socket.create_connection((HOST, PORT)); s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
ref = {}; t0 = time.time(); w0 = t0; rows = []; k = 0; total = 0; same_all = 0
def pct(v, p): v = sorted(v); return v[min(len(v) - 1, int(p * len(v)))]
while time.time() - t0 < SECS:
    i = k % 8; k += 1
    t = time.perf_counter(); out, done = protocol.call(s, imgs[i]); rt = (time.perf_counter() - t) * 1000
    if i not in ref: ref[i] = (out["cls"].copy(), out["score"].copy())
    same = np.array_equal(out["cls"], ref[i][0]) and np.abs(out["score"] - ref[i][1]).max() < 1e-6
    rows.append((done["inference_us"] / 1000, done["tpu_us"] / 1000, done["gpu_us"] / 1000, rt, done["backend"], same)); total += 1; same_all += same
    if time.time() - w0 >= WIN:
        inf = [r[0] for r in rows]; tpu = [r[1] for r in rows]; gpu = [r[2] for r in rows]; rts = [r[3] for r in rows]
        print(f"t={time.time() - t0:5.0f}s n={len(rows):3} inference p50 {pct(inf, .5):5.1f} p99 {pct(inf, .99):5.1f} max {max(inf):5.1f} | TPU p50 {pct(tpu, .5):4.1f} "
              f"| GPU p50 {pct(gpu, .5):4.1f} | round trip p50 {pct(rts, .5):5.1f} p99 {pct(rts, .99):5.1f} | backends {sorted(set(r[4] for r in rows))} "
              f"| identical {sum(r[5] for r in rows)}/{len(rows)}", flush=True)
        rows = []; w0 = time.time()
print(f"total {total} requests; outputs identical to first pass on {same_all}/{total}")
