"""The capacity rule end to end, on a test supervisor (generated profiles file
with reserve_mb) and a test MLServer built with make_test_repository.py:
  co-residency  EfficientSAM3 resident; YOLOE (510 MB) fits beside it: admitted,
                 nothing stopped
  idle eviction  EfficientSAM3 resident and idle; an OWLv2 request needs room it
                 can't share (2,365 + 1,924 MB) -> EfficientSAM3 is stopped, OWLv2
                 serves (result unchanged)
  busy wait      EfficientSAM3 busy (many phrases); an OWLv2 request waits for it,
                 then serves -- or, with a short CEREBRATE_CAPACITY_WAIT_S on the
                 test MLServer, fails with the supervisor's capacity message
  reserve        the phone's MemAvailable (CAPACITY, every 0.5 s) never below
                 reserve_mb - 150 MB (allocations after a start, other processes)
usage: capacity_scenarios.py <grpc> <http> <gateway> <supervisor port> <data dir> wait|fail
  (wait: the test MLServer runs with the policy's 30 s; fail: with CEREBRATE_CAPACITY_WAIT_S=5)"""
import os
import socket
import sys
import threading
import time
import urllib.request

import grpc
import numpy as np
from mlserver.grpc import dataplane_pb2 as pb, dataplane_pb2_grpc as pbg

GRPC, HTTP, GW, SUP, D, MODE = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5], sys.argv[6]
stub = pbg.GRPCInferenceServiceStub(grpc.insecure_channel(GRPC, options=[("grpc.max_send_message_length", 33554432), ("grpc.max_receive_message_length", 33554432)]))
results = []


def check(name, ok, note=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'} {name}{': ' + note if note else ''}", flush=True)


def supervisor(cmd, **fields):
    with socket.create_connection((GW, SUP), timeout=200) as s:
        s.sendall(("\n".join([cmd] + [f"{k}: {v}" for k, v in fields.items()]) + "\n\n").encode())
        s.shutdown(socket.SHUT_WR)
        return b"".join(iter(lambda: s.recv(4096), b"")).decode()


def state(slot):
    return supervisor("STATUS", worker=slot).split()[1]


def infer(model, tensors=None, **byte_inputs):
    req = pb.ModelInferRequest(model_name=model)
    for name, values in byte_inputs.items():
        req.inputs.add(name=name, datatype="BYTES", shape=[len(values)])
        req.raw_input_contents.append(b"".join(len(v).to_bytes(4, "little") + v for v in values))
    for name, a in (tensors or {}).items():
        req.inputs.add(name=name, datatype="INT64", shape=list(a.shape))
        req.raw_input_contents.append(np.ascontiguousarray(a).tobytes())
    t = time.perf_counter()
    r = stub.ModelInfer(req, timeout=300)
    return r, (time.perf_counter() - t) * 1000


photo = lambda i: open(f"{D}/stage-photos/photo{i}.jpg", "rb").read()
reserve = int(dict(kv.split("=") for kv in supervisor("CAPACITY").split()[1:4])["reserve_mb"])
check("test supervisor has a reserve", reserve > 0, f"reserve_mb={reserve}")

# free memory sampled throughout
mins, stop = [], threading.Event()


def sample():
    while not stop.is_set():
        line = supervisor("CAPACITY").splitlines()[0]
        mins.append(int(dict(kv.split("=") for kv in line.split()[1:])["available_mb"]))
        time.sleep(0.5)


threading.Thread(target=sample, daemon=True).start()
for line in supervisor("LIST").splitlines():
    if " RUNNING " in line:
        supervisor("STOP", worker=line.split()[0])
time.sleep(3)

QUERIES = [b"a bed", b"a lamp", b"a pillow", b"a chair"]
ref, _ = infer("owlv2-b16", photo=[photo(1)], queries=QUERIES)        # OWLv2's solo result, then stop it again
supervisor("STOP", worker="gpu-owlv2")
ref = ref.raw_output_contents[0]

# 1. co-residency within the reserve, then idle eviction
r, ms = infer("efficientsam3-rvm", {"image_id": np.array([1], np.int64)}, photo=[photo(1)], prompts=[b"bed"])
check("EfficientSAM3 serves and stays resident", state("gpu-esam3") == "RUNNING", f"{ms:.0f} ms")
r, ms = infer("yoloe-v8s-pf", photo=[photo(1)])
check("co-residency: YOLOE fits beside EfficientSAM3, nothing stopped",
      state("gpu-esam3") == "RUNNING" and state("hetero1") == "RUNNING", f"YOLOE {ms:.0f} ms incl. start")
supervisor("STOP", worker="hetero1")   # (the adapter restarts it on its next request: the lost-worker path)
r, ms = infer("owlv2-b16", photo=[photo(1)], queries=QUERIES)
check("idle eviction: OWLv2 serves, idle EfficientSAM3 was stopped to make room",
      r.raw_output_contents[0] == ref and state("gpu-esam3") == "STOPPED" and state("gpu-owlv2") == "RUNNING", f"OWLv2 {ms:.0f} ms incl. start")

# 2. busy: EfficientSAM3 serving many phrases while OWLv2 needs its memory
supervisor("STOP", worker="gpu-owlv2")
infer("efficientsam3-rvm", {"image_id": np.array([2], np.int64)}, photo=[photo(2)], prompts=[b"bed"])
phrases = [b"bed", b"lamp", b"pillow", b"chair", b"table", b"window", b"curtain", b"bag", b"towel", b"door"]
busy = {}


def long_request():
    t = time.time()
    infer("efficientsam3-rvm", {"image_id": np.array([2], np.int64)}, prompts=phrases)
    busy["done"] = time.time()
    busy["took"] = time.time() - t


th = threading.Thread(target=long_request)
th.start()
time.sleep(1.0)
t0 = time.time()
try:
    r, ms = infer("owlv2-b16", photo=[photo(1)], queries=QUERIES)
    outcome, msg = "served", ""
except grpc.RpcError as exc:
    outcome, msg = "refused", exc.details()
waited = time.time() - t0
th.join()
if MODE == "wait":
    check("busy wait: OWLv2 waited for EfficientSAM3 to finish, then served",
          outcome == "served" and r.raw_output_contents[0] == ref and busy["done"] <= t0 + waited,
          f"EfficientSAM3 busy {busy['took']:.1f} s; OWLv2 answered after {waited:.1f} s")
else:
    check("busy fail: OWLv2 refused with the capacity reason after the wait, EfficientSAM3 unharmed",
          outcome == "refused" and "capacity" in msg and 4 <= waited <= 12 and "took" in busy,
          f"after {waited:.1f} s: {msg[:200]}")
stop.set()
time.sleep(0.6)
check("reserve held: free memory never far below the reserve", min(mins) >= reserve - 150,
      f"minimum {min(mins)} MB free (reserve {reserve} MB, {len(mins)} samples)")
print(f"{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
