"""cerebrate-hetero through cerebrate-supervisor's hetero1 slot (a test
supervisor on its own control port): error paths, both fixed profiles,
DESCRIBE, outputs vs the earlier hand-launched runs, idempotent START,
configuration conflict, STOP.
usage: hetero_supervisor_chain.py <host> <control port> <inputs/refs dir>"""
import sys, socket, time
import numpy as np
sys.path.insert(0, "/home/droid/cg-test/mlserver/models/cerebrate-graph")
import cerebrate_graph_protocol as protocol
HOST, CP, D = sys.argv[1], int(sys.argv[2]), sys.argv[3]
T = "/data/local/tmp/"
FAST = dict(worker="hetero1", model=T + "yoloe-v8s-pf-backbone-tpu-fp32.tflite", backend="yoloe-v8s-fast")
DEFAULT = dict(worker="hetero1", model=T + "yoloe-v8s-pf-gpu-nhwc.tflite", backend="yoloe-v8s-default")

def sup(cmd, **f):
    msg = ("\n".join([cmd] + [f"{k}: {v}" for k, v in f.items()]) + "\n\n").encode()
    with socket.create_connection((HOST, CP), timeout=5) as s:
        s.settimeout(150); s.sendall(msg); s.shutdown(socket.SHUT_WR); b = b""
        while (c := s.recv(4096)): b += c
    return b.decode().strip()

def check(name, resp, want):
    ok = resp.startswith(want); print(f"{'PASS' if ok else 'FAIL'} {name}: {resp[:150]}"); return ok

imgs = [dict(np.load(f"{D}/in{i}.npz")) for i in range(8)]
def run(profile, refdir):
    s = socket.create_connection((HOST, 8772)); s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    desc, _ = protocol.call(s, {})
    print(f"  DESCRIBE model={desc.get('model')} backend={desc.get('backend')} mode={desc.get('mode')} load_us={desc.get('load_us')}")
    ok = desc.get("model") == profile["model"] and desc.get("backend") == profile["backend"]
    worst = {}; same_cls = 0; ms = []; backends = set()
    for i, x in enumerate(imgs):
        t = time.perf_counter(); out, done = protocol.call(s, x); ms.append((time.perf_counter() - t) * 1000)
        backends.add(done["backend"]); ref = np.load(f"{D}/{refdir}/out{i}.npz")
        for n in ref.files: worst[n] = max(worst.get(n, 0), float(np.abs(out[n] - ref[n]).max()))
        same_cls += bool(np.array_equal(out["cls"], ref["cls"]))
    s.close()
    print(f"  vs {refdir}: cls identical {same_cls}/8, max |diff| " + ", ".join(f"{k} {v:.1e}" for k, v in worst.items()))
    print(f"  backend codes {sorted(backends)}; round trip ms (first, median of rest) {ms[0]:.0f}, {np.median(ms[1:]):.0f}")
    return ok

r = [check("unknown profile", sup("START", worker="hetero1", model=FAST["model"], backend="nope"), "ERROR"),
     check("profile/model mismatch", sup("START", **dict(FAST, model=DEFAULT["model"])), "ERROR"),
     check("subdirectory path", sup("START", **dict(FAST, model=T + "hetero/yoloe-v8s-pf-backbone-tpu-fp32.tflite")), "ERROR"),
     check("graph slot refuses a hetero profile", sup("START", worker="graph1", model=T + "mobilenet_v1_1.0_224_quant.onnx", backend="yoloe-v8s-fast"), "ERROR")]
for prof, refdir in ((FAST, "out-fast"), (DEFAULT, "out-8793")):
    t = time.time(); r.append(check(f"START {prof['backend']}", sup("START", **prof), "OK")); print(f"  START took {time.time() - t:.1f} s")
    r.append(check("STATUS", sup("STATUS", worker="hetero1"), "hetero1 RUNNING"))
    r.append(run(prof, refdir))
    r.append(check("START again (idempotent)", sup("START", **prof), "OK"))
    other = DEFAULT if prof is FAST else FAST
    r.append(check("START other profile (conflict)", sup("START", **other), "ERROR"))
    r.append(check("STOP", sup("STOP", worker="hetero1"), "OK"))
print(sup("LIST"))
print(f"{sum(map(bool, r))}/{len(r)} checks passed")
