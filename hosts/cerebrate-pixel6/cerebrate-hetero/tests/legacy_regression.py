"""Legacy-path regression for a new cerebrate-hetero build: the same requests
to the deployed build and the new one (run one after the other on the same
port) must give bit-identical outputs. Requests per configuration: every
photo as float32 and as uint8 (the worker normalizes); for EdgeSAM also all
boxes per photo with image_id, then the cached photos' boxes again.
usage: legacy_regression.py save|compare <host> <port> <yoloe|edgesam> <inputs dir> <out dir>
  yoloe inputs: in<i>.npz (images [1,640,640,3] float32 = u8 / 255)
  edgesam inputs: photo<i>.npz (image [1,1024,1024,3] normalized, boxes)"""
import sys, os, socket
import numpy as np
sys.path.insert(0, "/home/droid/cg-test/mlserver/models/cerebrate-graph")
import cerebrate_graph_protocol as protocol
MODE, HOST, PORT, KIND, IND, OUT = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4], sys.argv[5], sys.argv[6]
os.makedirs(OUT, exist_ok=True)
s = socket.create_connection((HOST, PORT)); s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
desc, _ = protocol.call(s, {})
reqs = []
if KIND == "yoloe":
    for i in range(8):
        x = np.load(f"{IND}/in{i}.npz")["images"]
        reqs.append((f"f{i}", {"images": x}))
        reqs.append((f"u{i}", {"images": np.round(x * 255).astype(np.uint8)}))
else:
    MEAN = np.array([123.675, 116.28, 103.53], np.float32); STD = np.array([58.395, 57.12, 57.375], np.float32)
    for i in range(8):
        p = np.load(f"{IND}/photo{i}.npz")
        reqs.append((f"f{i}", {"image": p["image"], "image_id": np.array([i], np.int64), "boxes": p["boxes"]}))
    for i in range(4, 8):   # still cached (4 entries): boxes only
        p = np.load(f"{IND}/photo{i}.npz")
        reqs.append((f"c{i}", {"image_id": np.array([i], np.int64), "boxes": p["boxes"]}))
    for i in range(2):      # uint8 path: recover u8 from the normalized image inside its extent
        p = np.load(f"{IND}/photo{i}.npz"); x = p["image"][0]
        nz = np.argwhere(np.abs(x).sum(-1) > 0); h, w = nz.max(0) + 1
        u8 = np.zeros(x.shape, np.uint8); u8[:h, :w] = np.clip(np.round(x[:h, :w] * STD + MEAN), 0, 255)
        reqs.append((f"u{i}", {"image": u8[None], "image_id": np.array([100 + i], np.int64), "extent": np.array([h, w], np.int64), "boxes": p["boxes"]}))
same = 0; backends = set()
for tag, r in reqs:
    out, done = protocol.call(s, r); backends.add(done.get("backend"))
    if MODE == "save":
        np.savez(f"{OUT}/{tag}.npz", **out)
    else:
        ref = np.load(f"{OUT}/{tag}.npz")
        ok = set(ref.files) == set(out) and all(np.array_equal(ref[k], out[k]) for k in ref.files)
        same += ok
        if not ok:
            print(f"  DIFFERENT: {tag}", {k: float(np.abs(ref[k].astype(np.float64) - out[k].astype(np.float64)).max()) for k in ref.files if k in out})
print(f"{MODE} {KIND} via {desc.get('backend')} ({desc.get('mode')}): {len(reqs)} requests, backends {sorted(backends)}" + (f", {same}/{len(reqs)} bit-identical" if MODE == "compare" else ""))
