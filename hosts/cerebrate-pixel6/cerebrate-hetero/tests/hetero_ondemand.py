"""On-demand residency of MLServer model yoloe-v8s-pf (cerebrate_graph_runtime
with cerebrate_graph_residency: on_demand), through an MLServer instance and
a supervisor: phase "first" (index, cold request starts the worker, warm
requests, outputs vs the hand-launched fast run), "idle" (after the idle
window the worker is STOPped, the next request restarts it), "after-kill"
(after the worker was killed: one failed request, then a restart),
"unload" (repository unload STOPs the slot). Run against a test MLServer
(its own ports, adapter copy pointed at a test supervisor) before deploying,
and phase "first" against production afterwards.
usage: hetero_ondemand.py <phase> <MLServer base URL> <supervisor host> <control port> <inputs/refs dir>"""
import sys, json, socket, time, urllib.request, urllib.error
import numpy as np
PHASE, URL, HOST, CP, D = sys.argv[1], sys.argv[2].rstrip("/") + "/v2", sys.argv[3], int(sys.argv[4]), sys.argv[5]

def sup(cmd, **f):
    msg = ("\n".join([cmd] + [f"{k}: {v}" for k, v in f.items()]) + "\n\n").encode()
    with socket.create_connection((HOST, CP), timeout=5) as s:
        s.settimeout(30); s.sendall(msg); s.shutdown(socket.SHUT_WR); b = b""
        while (c := s.recv(4096)): b += c
    return b.decode().strip()

def post(path, body):
    req = urllib.request.Request(URL + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read() or b"{}")

def infer(i):
    x = np.load(f"{D}/in{i}.npz")["images"]
    body = {"inputs": [{"name": "images", "shape": list(x.shape), "datatype": "FP32", "data": x.ravel().tolist()}]}
    t = time.perf_counter()
    try:
        r = post("/models/yoloe-v8s-pf/infer", body)
    except urllib.error.HTTPError as e:
        print(f"  photo {i}: HTTP {e.code} after {(time.perf_counter() - t) * 1000:.0f} ms: {e.read()[:160]}"); return False
    ms = (time.perf_counter() - t) * 1000
    ref = np.load(f"{D}/out-fast/out{i}.npz")
    out = {o["name"]: np.asarray(o["data"], np.float32).reshape(o["shape"]) for o in r["outputs"]}
    diff = max(float(np.abs(out[n] - ref[n]).max()) for n in ref.files)
    print(f"  photo {i}: {ms:.0f} ms, backend code {r['parameters'].get('backend')}, max |diff| vs out-fast {diff:.1e}")
    return diff == 0

def slot(): return next(l for l in sup("LIST").splitlines() if l.startswith("hetero1"))[:60]

if PHASE == "first":
    print("index:", [(m["name"], m["state"]) for m in post("/repository/index", {}) if m["name"] == "yoloe-v8s-pf"])
    print("before any request:", slot())
    ok = [infer(i) for i in range(4)]
    print("after:", slot()); print(f"{sum(ok)}/4 bit-identical")
elif PHASE == "idle":
    print("after idle window:", slot())
    ok = infer(4); print("after request:", slot(), "| identical" if ok else "| DIFFERENT")
elif PHASE == "after-kill":
    print("after kill:", slot())
    infer(5)
    ok = infer(6); print("after:", slot(), "| identical" if ok else "| DIFFERENT")
elif PHASE == "unload":
    for m in sys.argv[6:] or ["yoloe-v8s-pf"]:      # test instance: also its pinned canary
        post(f"/repository/models/{m}/unload", {})
    print("after unload:", sup("LIST").replace("\n", " | "))
