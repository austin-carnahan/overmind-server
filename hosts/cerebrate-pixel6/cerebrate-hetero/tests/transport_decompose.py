"""Where the time outside the worker goes, from the guest: DESCRIBE (tiny
request and reply: base latency), EdgeSAM uint8 image alone ({image, extent,
image_id}: 3.15 MB up, 8 bytes back), and the client-side cost of encoding
that request without sending it. usage: transport_decompose.py <host> <edgesam port> <photos dir> <photo file> [edgesam photo npz with boxes]"""
import sys, socket, time, io
import numpy as np
sys.path.insert(0, "/home/droid/cg-test/mlserver/models/cerebrate-graph")
import cerebrate_graph_protocol as protocol
import photo_preprocess as pp
HOST, EP, PD, F = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
bgr = pp.decode(open(f"{PD}/{F}", "rb").read()); s8, (eh, ew) = pp.sam_resize(bgr)
req = {"image": s8[None], "extent": np.array([eh, ew], np.int64), "image_id": np.array([0], np.int64)}
s = socket.create_connection((HOST, EP)); s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
def med(fn, n=12):
    v = []
    for _ in range(n + 1):
        a = time.perf_counter(); r = fn(); v.append(((time.perf_counter() - a) * 1000, r))
    return v[1:]
d = med(lambda: protocol.call(s, {}))
print(f"DESCRIBE round trip: median {np.median([x[0] for x in d]):.1f} ms")
im = med(lambda: protocol.call(s, req))
print(f"uint8 image only (3.15 MB up): round trip {np.median([x[0] for x in im]):.0f} ms, worker {np.median([x[1][1]['inference_us'] for x in im]) / 1000:.0f} ms")
ph = np.load(sys.argv[5]) if len(sys.argv) > 5 else None
if ph is not None:
    for label, extra in (("uint8 image + 1 box", {"boxes": ph["boxes"][:1]}), ("cached image + 1 box", None)):
        r = req | extra if extra else {"image_id": np.array([0], np.int64), "boxes": ph["boxes"][:1]}
        v = med(lambda: protocol.call(s, r))
        rt, wk = np.median([x[0] for x in v]), np.median([x[1][1]["inference_us"] for x in v]) / 1000
        print(f"{label}: round trip {rt:.0f} ms, worker {wk:.0f} ms, outside {rt - wk:.0f} ms")
enc = med(lambda: len(protocol.encode_request(req)) if hasattr(protocol, "encode_request") else 0)
print(f"client-side encode of that request (no send): {np.median([x[0] for x in enc]):.1f} ms ({enc[0][1] / 1e6:.2f} MB)")
