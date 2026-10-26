"""uint8 photo input vs the validated fp32 input, over the worker protocol:
for each lane photo, the fp32 tensor the models were validated with and the
uint8 tensor the guest pipeline (photo_preprocess) makes from the photo file,
normalized by the worker. Outputs must be bit-identical to each other and to
the validated results; round trips compared (the transport saving).
usage: uint8_input_check.py <host> <yoloe port> <edgesam port> <photos dir> <hetero dir> <edgesam dir> <photo files in index order...>"""
import sys, socket, time
import numpy as np
sys.path.insert(0, "/home/droid/cg-test/mlserver/models/cerebrate-graph")
import cerebrate_graph_protocol as protocol
import photo_preprocess as pp
HOST, YP, EP, PD, HD, ED = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4], sys.argv[5], sys.argv[6]
files = sys.argv[7:]
def conn(p):
    s = socket.create_connection((HOST, p)); s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1); return s
ys, es = conn(YP), conn(EP)
def call(s, t):
    a = time.perf_counter(); out, done = protocol.call(s, t); return out, done, (time.perf_counter() - a) * 1000
rt = {"y32": [], "y8": [], "e32": [], "e8": []}; ok_y = ok_e = 0
for i, f in enumerate(files):
    bgr = pp.decode(open(f"{PD}/{f}", "rb").read())
    y8, _ = pp.yoloe_letterbox(bgr); s8, (eh, ew) = pp.sam_resize(bgr)
    yref = np.load(f"{HD}/out-fast/out{i}.npz")
    o32, d32, t32 = call(ys, {"images": np.load(f"{HD}/in{i}.npz")["images"]})
    o8, d8, t8 = call(ys, {"images": y8[None]})
    same = all(np.array_equal(o8[n], o32[n]) and np.array_equal(o8[n], yref[n]) for n in yref.files); ok_y += same
    rt["y32"].append(t32); rt["y8"].append(t8)
    ph = np.load(f"{ED}/photo{i}.npz")
    e32, _, s32 = call(es, {"image": ph["image"], "image_id": np.array([i], np.int64), "boxes": ph["boxes"]})
    e8, de8, se8 = call(es, {"image": s8[None], "extent": np.array([eh, ew], np.int64), "image_id": np.array([i], np.int64), "boxes": ph["boxes"]})
    same_e = all(np.array_equal(e8[n], e32[n]) for n in e32); ok_e += same_e
    rt["e32"].append(s32); rt["e8"].append(se8)
    print(f"photo {i}: YOLOE uint8 identical {same} (uint8 flag {d8.get('uint8')}, {y8.nbytes / 1e6:.2f} MB vs 4.92 MB), "
          f"EdgeSAM uint8 identical {same_e} ({len(ph['boxes'])} boxes, extent {eh}x{ew}, {s8.nbytes / 1e6:.2f} MB vs 12.58 MB)", flush=True)
med = lambda v: float(np.median(v[1:]))   # first request per path warms up
print(f"YOLOE: {ok_y}/{len(files)} identical; round trip median fp32 {med(rt['y32']):.0f} ms -> uint8 {med(rt['y8']):.0f} ms")
print(f"EdgeSAM (image + all its boxes): {ok_e}/{len(files)} identical; round trip median fp32 {med(rt['e32']):.0f} ms -> uint8 {med(rt['e8']):.0f} ms")
