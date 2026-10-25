"""MI-GAN photo path on the device: the adapter hook (the author's pipeline:
photo + mask in, composited PNG out) around a graph-mode worker, judged
against the author's full migan.onnx pipeline run on the desktop with the fp32
generator: PSNR inside the removed region (8-bit), identity outside it.
usage: migan_photo_check.py <host> <port> <photos dir> <dir with mask<i>.png, ref<i>.npy>"""
import sys, socket, json, base64
import numpy as np, cv2
sys.path.insert(0, "/home/droid/cg-test/stage/code/cerebrate-graph")
import cerebrate_graph_protocol as protocol
import cerebrate_graph_photo as cgp


class FakeInput:
    def __init__(self, data): self.datatype, self.data = "BYTES", [data]


HOST, PORT, PHOTOS, REFD = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
h = cgp.HOOKS["migan"]()
s = socket.create_connection((HOST, PORT)); s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
desc, _ = protocol.call(s, {})
ps, inf = [], []
for i in range(8):
    photo = open(f"{PHOTOS}/photo{i}.jpg", "rb").read(); mask = open(f"{REFD}/mask{i}.png", "rb").read()
    inputs, ctx = h.prepare({"photo": FakeInput(photo), "mask": FakeInput(mask)})
    out, done = protocol.call(s, inputs); inf.append(done["inference_us"] / 1000)
    doc = json.loads(h.finish(out, ctx)["result"])
    got = cv2.imdecode(np.frombuffer(base64.b64decode(doc["result"]), np.uint8), cv2.IMREAD_COLOR)[..., ::-1].astype(np.float64)
    ref = np.load(f"{REFD}/ref{i}.npy").astype(np.float64)
    region = cv2.imdecode(np.frombuffer(mask, np.uint8), cv2.IMREAD_GRAYSCALE) >= 128
    mse = ((got - ref) ** 2)[region].mean(); p = 10 * np.log10(255 ** 2 / max(mse, 1e-12)); ps.append(p)
    print(f"photo {i}: removed-region PSNR vs the author's pipeline {p:.1f} dB; outside identical {bool((got[~region] == ref[~region]).all())}; worker {inf[-1]:.0f} ms")
print(f"{desc['config'][:70]}: worst {min(ps):.1f} dB, mean {np.mean(ps):.1f} dB; worker median {np.median(inf):.0f} ms")
