"""Sustained EdgeSAM load on cerebrate-hetero from the guest: back-to-back
{image, image_id, 4 boxes} requests, photos cycled, for <seconds>; per 30 s
window: requests, worker inference p50/p99, TPU p50, outputs identical to the
first pass. usage: edgesam_sustained.py <host> <port> <edgesam dir> <seconds>"""
import sys, socket, time
import numpy as np
sys.path.insert(0, "/home/droid/cg-test/mlserver/models/cerebrate-graph")
import cerebrate_graph_protocol as protocol
HOST, PORT, D, SECS = sys.argv[1], int(sys.argv[2]), sys.argv[3], float(sys.argv[4])
ph = [dict(np.load(f"{D}/photo{i}.npz")) for i in range(8)]
s = socket.create_connection((HOST, PORT)); s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
ref, win, k, t_end, w_end = {}, [], 0, time.time() + SECS, time.time() + 30
def pct(v, p): v = sorted(v); return v[min(len(v) - 1, int(p * len(v)))]
while time.time() < t_end:
    i = k % 8; k += 1
    out, done = protocol.call(s, {"image": ph[i]["image"], "image_id": np.array([i], np.int64), "boxes": np.resize(ph[i]["boxes"], (4, 1, 4)).astype(np.float32)})
    same = None
    if i not in ref: ref[i] = out["mask_logits"].copy()
    else: same = bool(np.array_equal(out["mask_logits"], ref[i]))
    win.append((done["inference_us"] / 1000, done["tpu_us"] / 1000, done["backend"], same))
    if time.time() >= w_end:
        c = [x[3] for x in win if x[3] is not None]
        print(f"{time.strftime('%H:%M:%S')} {len(win)} req | inference p50 {pct([x[0] for x in win], .5):.0f} p99 {pct([x[0] for x in win], .99):.0f} ms | "
              f"tpu p50 {pct([x[1] for x in win], .5):.0f} ms | identical {sum(c)}/{len(c)} | backends {sorted({x[2] for x in win})}", flush=True)
        win, w_end = [], time.time() + 30
