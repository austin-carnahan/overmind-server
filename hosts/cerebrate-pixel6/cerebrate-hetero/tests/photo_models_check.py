"""Photo path of the graph-mode models: the adapter hook's preprocessing
(uint8 to the worker, normalized there) must reproduce the validated device
inputs, so the worker's outputs for the eight lane photos equal the
validated raw-path outputs bit for bit; then the hook's final result is
decoded and sanity-checked against the raw outputs.
usage: photo_models_check.py <host> <port> <depth|dinov2|yoloe11s> <photos dir> <validated outputs dir>"""
import sys, socket, json, base64
import numpy as np
sys.path.insert(0, "/home/droid/cg-test/stage/code/cerebrate-graph")
import cerebrate_graph_protocol as protocol
import cerebrate_graph_photo as cgp
import cv2


class FakeInput:   # what MLServer hands a hook: a BYTES request input
    def __init__(self, data): self.datatype, self.data = "BYTES", [data]


HOST, PORT, KIND, PHOTOS, REF = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4], sys.argv[5]
hooks = {"depth": cgp.HOOKS["depth"], "dinov2": cgp.HOOKS["dinov2"], "yoloe11s": cgp.HOOKS["yoloe"]}[KIND]()
s = socket.create_connection((HOST, PORT)); s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
same = 0
for i in range(8):
    data = open(f"{PHOTOS}/photo{i}.jpg", "rb").read()
    inputs, ctx = hooks.prepare({"photo": FakeInput(data)}, None)
    out, done = protocol.call(s, inputs)
    ok = all(np.array_equal(np.fromfile(f"{REF}/{i}_o{k}.bin", v.dtype), v.ravel()) for k, v in enumerate(out.values()))
    same += ok
    doc = json.loads(hooks.finish(out, ctx)["result"])
    if KIND == "depth":
        d = doc["depth"]; png = cv2.imdecode(np.frombuffer(base64.b64decode(d["data"]), np.uint8), cv2.IMREAD_UNCHANGED)
        rec = d["min"] + png.astype(np.float64) / 65535 * (d["max"] - d["min"])
        err = np.abs(rec - out["depth"].reshape(png.shape)).max() / (d["max"] - d["min"])
        note = f"png16 {png.shape} {png.dtype}, max reconstruction error {err:.1e} of the range"
    elif KIND == "dinov2":
        e = np.frombuffer(base64.b64decode(doc["embedding"]["data"]), "<f4")
        note = f"embedding dim {e.size}, equals mean of patch tokens: {np.array_equal(e, out['patch_tokens'].reshape(-1, 384).mean(0, dtype=np.float32))}"
    else:
        note = f"{len(doc['detections'])} detections, first {doc['detections'][0]['label'] if doc['detections'] else '-'}"
    print(f"photo {i}: worker outputs {'bit-identical' if ok else 'DIFFERENT'} to the validated run; uint8={done['uint8']}; {note}")
print(f"{KIND}: {same}/8 photos bit-identical through the photo path")
