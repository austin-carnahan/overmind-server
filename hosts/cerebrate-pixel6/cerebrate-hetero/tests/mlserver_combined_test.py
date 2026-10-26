"""YOLOE-v8s and EdgeSAM through one MLServer instance (graph adapter,
on-demand residency) and a supervisor, over MLServer's gRPC endpoint with
raw tensor bytes (a 12.6 MB image as JSON would be ~40 MB of text). Outputs
must equal the validated direct runs bit for bit: YOLOE's out-fast, and
EdgeSAM's supervisor-chain outputs (edgesam_supervisor_chain.py, out-sup).
Phases:
  start       both models READY, neither worker running
  infer       2 photos each (the first requests start the workers), EdgeSAM
              {image, image_id, boxes} then {image_id, boxes} from the cache
  idle        after the idle window both workers are STOPPED; a request each
              restarts them (identical outputs)
  after-kill  (EdgeSAM worker killed beforehand) one failed request, model
              stays READY, the next request restarts it
  unload      repository unload of every model: all slots STOPPED
usage: mlserver_combined_test.py <phase> <grpc host:port> <supervisor host> <control port> <hetero dir> <edgesam dir> [models to unload ...]"""
import sys, socket, time, json
import numpy as np, grpc
from mlserver.grpc import dataplane_pb2 as pb, dataplane_pb2_grpc as pbg
PHASE, GRPC, HOST, CP, HD, ED = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5], sys.argv[6]
stub = pbg.GRPCInferenceServiceStub(grpc.insecure_channel(GRPC, options=[("grpc.max_send_message_length", -1), ("grpc.max_receive_message_length", -1)]))
DT = {np.dtype("float32"): "FP32", np.dtype("int64"): "INT64"}; ND = {"FP32": np.float32, "INT64": np.int64}

def sup(cmd, **f):
    msg = ("\n".join([cmd] + [f"{k}: {v}" for k, v in f.items()]) + "\n\n").encode()
    with socket.create_connection((HOST, CP), timeout=5) as s:
        s.settimeout(30); s.sendall(msg); s.shutdown(socket.SHUT_WR); b = b""
        while (c := s.recv(4096)): b += c
    return b.decode().strip()
def slots(): return " | ".join(l[:30] for l in sup("LIST").splitlines() if l.startswith("hetero"))

def infer(model, tensors):
    req = pb.ModelInferRequest(model_name=model)
    for name, a in tensors.items():
        req.inputs.add(name=name, datatype=DT[a.dtype], shape=list(a.shape)); req.raw_input_contents.append(np.ascontiguousarray(a).tobytes())
    t = time.perf_counter(); r = stub.ModelInfer(req, timeout=300); ms = (time.perf_counter() - t) * 1000
    out = {o.name: np.frombuffer(raw, ND[o.datatype]).reshape(list(o.shape)) for o, raw in zip(r.outputs, r.raw_output_contents)}
    return out, {k: v.int64_param for k, v in r.parameters.items()}, ms

yin = [dict(np.load(f"{HD}/in{i}.npz")) for i in range(2)]; yref = [np.load(f"{HD}/out-fast/out{i}.npz") for i in range(2)]
eph = [dict(np.load(f"{ED}/photo{i}.npz")) for i in range(2)]
offset = [0, len(eph[0]["boxes"])]
eref = [np.stack([np.fromfile(f"{ED}/out-sup/edgesam3x-fast/{offset[i] + j}_o0.bin", np.float32).reshape(1, 256, 256) for j in range(len(eph[i]["boxes"]))]) for i in range(2)]

def yoloe(i):
    out, p, ms = infer("yoloe-v8s-pf", yin[i])
    return all(np.array_equal(out[n], yref[i][n]) for n in yref[i].files), p, ms
def edgesam(i, cached=False):
    t = {"image_id": np.array([i], np.int64), "boxes": eph[i]["boxes"]}
    if not cached: t["image"] = eph[i]["image"]
    out, p, ms = infer("edgesam3x-box", t)
    return np.array_equal(out["mask_logits"], eref[i]), p, ms

if PHASE == "start":
    idx = stub.RepositoryIndex(pb.RepositoryIndexRequest())
    print("index:", [(m.name, m.state) for m in idx.models]); print("slots:", slots())
elif PHASE in ("infer", "idle"):
    if PHASE == "idle": print("after idle window:", slots())
    for i in range(2 if PHASE == "infer" else 1):
        ok, p, ms = yoloe(i); print(f"  yoloe photo {i}: identical {ok}, backend {p.get('backend')}, worker {p.get('inference_us', 0)/1000:.0f} ms, gRPC round trip {ms:.0f} ms")
        ok, p, ms = edgesam(i); print(f"  edgesam photo {i} ({len(eph[i]['boxes'])} boxes): identical {ok}, backend {p.get('backend')}, cache {p.get('cache')}, worker {p.get('inference_us', 0)/1000:.0f} ms, gRPC round trip {ms:.0f} ms")
    if PHASE == "infer":
        ok, p, ms = edgesam(0, cached=True); print(f"  edgesam photo 0 from the cache: identical {ok}, cache {p.get('cache')}, worker {p.get('inference_us', 0)/1000:.0f} ms, round trip {ms:.0f} ms")
    print("slots:", slots())
elif PHASE == "after-kill":
    print("after kill:", slots())
    try: edgesam(1); print("  first request after the kill: succeeded (unexpected)")
    except grpc.RpcError as e: print(f"  first request after the kill: {e.code().name}")
    idx = stub.RepositoryIndex(pb.RepositoryIndexRequest()); print("  index:", [(m.name, m.state) for m in idx.models])
    ok, p, ms = edgesam(1); print(f"  next request: identical {ok}, backend {p.get('backend')}, round trip {ms:.0f} ms"); print("slots:", slots())
elif PHASE == "unload":
    for m in sys.argv[7:]:
        stub.RepositoryModelUnload(pb.RepositoryModelUnloadRequest(model_name=m))
    print("after unload:", sup("LIST").replace("\n", " | "))
