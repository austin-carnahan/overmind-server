"""Input transport, fp32 tensor vs uint8, over the worker protocol from the
guest: EdgeSAM image + 1 box and YOLOE, 12 requests each per form
(alternating, first of each discarded); round trip vs worker time, so the
difference is transport + framing. usage: transport_bench.py <host> <yoloe port> <edgesam port> <photos dir> <hetero dir> <edgesam dir> <photo file>"""
import sys, socket, time
import numpy as np
sys.path.insert(0, "/home/droid/cg-test/mlserver/models/cerebrate-graph")
import cerebrate_graph_protocol as protocol
import photo_preprocess as pp
HOST, YP, EP, PD, HD, ED, F = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4], sys.argv[5], sys.argv[6], sys.argv[7]
bgr = pp.decode(open(f"{PD}/{F}", "rb").read()); y8, _ = pp.yoloe_letterbox(bgr); s8, (eh, ew) = pp.sam_resize(bgr)
ph = np.load(f"{ED}/photo0.npz"); y32 = np.load(f"{HD}/in0.npz")["images"]
reqs = {"YOLOE fp32": (YP, {"images": y32}), "YOLOE uint8": (YP, {"images": y8[None]}),
        "EdgeSAM fp32 + 1 box": (EP, {"image": ph["image"], "image_id": np.array([0], np.int64), "boxes": ph["boxes"][:1]}),
        "EdgeSAM uint8 + 1 box": (EP, {"image": s8[None], "extent": np.array([eh, ew], np.int64), "image_id": np.array([0], np.int64), "boxes": ph["boxes"][:1]})}
socks = {p: socket.create_connection((HOST, p)) for p in (YP, EP)}
for s in socks.values(): s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
res = {k: [] for k in reqs}
for _ in range(13):
    for k, (p, t) in reqs.items():
        a = time.perf_counter(); _, d = protocol.call(socks[p], t); res[k].append(((time.perf_counter() - a) * 1000, d["inference_us"] / 1000))
for k, v in res.items():
    v = v[1:]; rt = np.median([x[0] for x in v]); wk = np.median([x[1] for x in v])
    print(f"{k:24s} round trip {rt:6.0f} ms | worker {wk:6.1f} ms | outside the worker {rt - wk:6.0f} ms")
