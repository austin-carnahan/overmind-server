"""Measures capacity costs (variants.yaml resources.load_mb) through a test
supervisor and test MLServer: per endpoint, every test worker stopped, the
phone's MemAvailable read through the supervisor's CAPACITY command (baseline,
then every 0.5 s while the endpoint serves representative requests), cost =
baseline - minimum. The worker's peak RSS (with children) comes from the same
replies. Run on the guest beside production; the test supervisor needs no
reserve_mb while costs are measured.
usage: measure_costs.py <grpc host:port> <http host:port> <gateway> <supervisor port> <data dir> <endpoint>[=<slot>]...
endpoints: yoloe-v8s-pf, edgesam3x-box (and copies serving their default
profiles), cerebrate-infer, cerebrate-generate, cerebrate-gguf, or any photo
endpoint of the registry (8 photos)."""
import base64
import json
import os
import socket
import sys
import threading
import time
import urllib.request

import grpc
import numpy as np
from mlserver.grpc import dataplane_pb2 as pb, dataplane_pb2_grpc as pbg

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mobilenet_probe  # noqa: E402

GRPC, HTTP, GW, SUP, D = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5]
stub = pbg.GRPCInferenceServiceStub(grpc.insecure_channel(GRPC, options=[("grpc.max_send_message_length", 33554432), ("grpc.max_receive_message_length", 33554432)]))


def supervisor(cmd, **fields):
    with socket.create_connection((GW, SUP), timeout=200) as s:
        s.sendall(("\n".join([cmd] + [f"{k}: {v}" for k, v in fields.items()]) + "\n\n").encode())
        s.shutdown(socket.SHUT_WR)
        return b"".join(iter(lambda: s.recv(4096), b"")).decode()


def capacity():
    lines = supervisor("CAPACITY").splitlines()
    avail = int(dict(kv.split("=") for kv in lines[0].split()[1:])["available_mb"])
    rss = {l.split()[0]: int(l.split("rss_mb=")[1]) for l in lines[1:] if "rss_mb=" in l}
    return avail, rss


def bytes_input(req, name, values):
    req.inputs.add(name=name, datatype="BYTES", shape=[len(values)])
    req.raw_input_contents.append(b"".join(len(v).to_bytes(4, "little") + v for v in values))


def infer(model, tensors=None, **byte_inputs):
    req = pb.ModelInferRequest(model_name=model)
    for name, values in byte_inputs.items():
        bytes_input(req, name, values)
    for name, a in (tensors or {}).items():
        req.inputs.add(name=name, datatype={np.dtype("float32"): "FP32", np.dtype("int64"): "INT64"}[a.dtype], shape=list(a.shape))
        req.raw_input_contents.append(np.ascontiguousarray(a).tobytes())
    return stub.ModelInfer(req, timeout=900)


photo = lambda i: open(f"{D}/stage-photos/photo{i}.jpg", "rb").read()


def drive(endpoint):
    if endpoint.startswith("cerebrate-infer"):
        png = base64.b64encode(mobilenet_probe.probe_png())
        assert all(mobilenet_probe.classify(stub, png, endpoint)[0] == 795 for _ in range(20))
    elif endpoint.startswith("cerebrate-generate"):
        infer(endpoint, prompt=[b"Write one sentence about the sea."])
    elif endpoint.startswith("cerebrate-gguf"):
        infer(endpoint, image=[base64.b64encode(open(f"{D}/gguf-probe.png", "rb").read())], prompt=[b"Convert this page to docling."])
    elif endpoint.startswith("edgesam3x"):
        from PIL import Image
        for i in range(8):
            w, h = Image.open(f"{D}/stage-photos/photo{i}.jpg").size
            boxes = np.array([[0.25 * w, 0.35 * h, 0.75 * w, 0.95 * h], [0.05 * w, 0.05 * h, 0.55 * w, 0.60 * h]], np.float32)
            infer(endpoint, {"image_id": np.array([i], np.int64), "boxes": boxes}, photo=[photo(i)])
    else:
        for i in range(8):
            infer(endpoint, photo=[photo(i)])


def http_post(path):
    urllib.request.urlopen(urllib.request.Request(f"http://{HTTP}{path}", data=b"{}", method="POST"), timeout=120)


results = []
for arg in sys.argv[6:]:
    endpoint, _, slot = arg.partition("=")
    for line in supervisor("LIST").splitlines():
        if " RUNNING " in line:
            supervisor("STOP", worker=line.split()[0])
    time.sleep(5)
    base = sorted(capacity()[0] for _ in range(3))[1]
    samples, peak_rss, stop = [], {}, threading.Event()

    def sample():
        while not stop.is_set():
            a, rss = capacity()
            samples.append(a)
            for k, v in rss.items():
                peak_rss[k] = max(peak_rss.get(k, 0), v)
            time.sleep(0.5)
    t = threading.Thread(target=sample)
    t.start()
    t0 = time.time()
    try:
        drive(endpoint)
        ok = True
    except Exception as exc:
        ok = False
        print(f"  {endpoint}: request failed: {exc}", flush=True)
    stop.set()
    t.join()
    drop = base - min(samples + [base])
    results.append((endpoint, drop, peak_rss, ok, time.time() - t0))
    print(f"{endpoint}: baseline {base} MB, min {min(samples + [base])} MB -> load_mb {drop}; peak rss {peak_rss}; "
          f"{'ok' if ok else 'FAILED'} in {time.time() - t0:.0f} s", flush=True)
    http_post(f"/v2/repository/models/{endpoint}/unload")
    http_post(f"/v2/repository/models/{endpoint}/load")
print("RESULTS", json.dumps([(e, d, ok) for e, d, _, ok, _ in results]))
