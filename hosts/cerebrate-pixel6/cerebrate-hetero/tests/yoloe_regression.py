"""YOLOE-v8s fast profile on a (new) cerebrate-hetero build: the eight
photos' outputs must equal the validated hand-launched run (out-fast) bit for
bit. usage: yoloe_regression.py <host> <port> <hetero test dir (in*.npz, out-fast/)>"""
import sys, socket
import numpy as np
sys.path.insert(0, "/home/droid/cg-test/mlserver/models/cerebrate-graph")
import cerebrate_graph_protocol as protocol
HOST, PORT, D = sys.argv[1], int(sys.argv[2]), sys.argv[3]
s = socket.create_connection((HOST, PORT)); same = 0; codes = set(); inf = []
for i in range(8):
    out, done = protocol.call(s, dict(np.load(f"{D}/in{i}.npz"))); ref = np.load(f"{D}/out-fast/out{i}.npz")
    codes.add(done["backend"]); inf.append(done["inference_us"] / 1000)
    same += all(np.array_equal(out[n], ref[n]) for n in ref.files)
d, _ = protocol.call(s, {})
print(f"YOLOE fast: {same}/8 photos bit-identical to the validated outputs, backend codes {sorted(codes)}, "
      f"inference median {np.median(inf):.1f} ms; DESCRIBE input {d['inputs'][0]['shape']}, model {d['model']}, health {d['health']}")
