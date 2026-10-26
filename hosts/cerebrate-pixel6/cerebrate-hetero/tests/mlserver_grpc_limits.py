"""MLServer gRPC message limits with full-size payloads (the deployment sets
MLSERVER_GRPC_MAX_MESSAGE_LENGTH=33554432, which bounds requests and
responses): YOLOE (4.9 MB image in, ~5 MB out) with a client whose receive
limit is raised and with gRPC's client defaults (4 MiB receive); EdgeSAM with
a full image and 28 boxes; EdgeSAM responses near the 32 MiB cap (~262 KB per
box: 120 boxes fit, 130 don't); then an ordinary request (still healthy).
usage: mlserver_grpc_limits.py <grpc host:port> <hetero dir> <edgesam dir>"""
import sys, time
import numpy as np, grpc
from mlserver.grpc import dataplane_pb2 as pb, dataplane_pb2_grpc as pbg
GRPC, HD, ED = sys.argv[1:4]
raised = pbg.GRPCInferenceServiceStub(grpc.insecure_channel(GRPC, options=[("grpc.max_send_message_length", 33554432), ("grpc.max_receive_message_length", 33554432)]))
default = pbg.GRPCInferenceServiceStub(grpc.insecure_channel(GRPC))
DT = {np.dtype("float32"): "FP32", np.dtype("int64"): "INT64"}; ND = {"FP32": np.float32, "INT64": np.int64}

def infer(stub, model, tensors):
    req = pb.ModelInferRequest(model_name=model)
    for name, a in tensors.items():
        req.inputs.add(name=name, datatype=DT[a.dtype], shape=list(a.shape)); req.raw_input_contents.append(np.ascontiguousarray(a).tobytes())
    t = time.perf_counter(); r = stub.ModelInfer(req, timeout=300)
    out = {o.name: np.frombuffer(raw, ND[o.datatype]).reshape(list(o.shape)) for o, raw in zip(r.outputs, r.raw_output_contents)}
    return out, (time.perf_counter() - t) * 1000, sum(len(x) for x in r.raw_output_contents)

def attempt(label, fn):
    try:
        msg = fn(); print(f"OK    {label}: {msg}")
    except grpc.RpcError as e:
        print(f"ERROR {label}: {e.code().name}: {e.details()[:110]}")

y = dict(np.load(f"{HD}/in0.npz")); yref = np.load(f"{HD}/out-fast/out0.npz")
p1 = dict(np.load(f"{ED}/photo1.npz")); e1ref = np.stack([np.fromfile(f"{ED}/out-sup/edgesam3x-fast/{21 + j}_o0.bin", np.float32).reshape(1, 256, 256) for j in range(28)])
def yoloe(stub):
    out, ms, nb = infer(stub, "yoloe-v8s-pf", y)
    return f"{y['images'].nbytes / 1e6:.1f} MB in, {nb / 1e6:.1f} MB out, identical {all(np.array_equal(out[n], yref[n]) for n in yref.files)}, {ms:.0f} ms"
def edgesam(n, ref=None):
    boxes = np.resize(p1["boxes"], (n, 1, 4)).astype(np.float32)
    out, ms, nb = infer(raised, "edgesam3x-box", {"image": p1["image"], "image_id": np.array([1], np.int64), "boxes": boxes})
    same = "" if ref is None else f", identical {np.array_equal(out['mask_logits'], ref)}"
    return f"{p1['image'].nbytes / 1e6:.1f} MB in, {n} boxes, {nb / 1e6:.1f} MB out{same}, {ms:.0f} ms"
attempt("YOLOE, client receive limit 32 MiB", lambda: yoloe(raised))
attempt("YOLOE, gRPC client defaults", lambda: yoloe(default))
attempt("EdgeSAM full image + 28 boxes", lambda: edgesam(28, e1ref))
attempt("EdgeSAM + 120 boxes (response under 32 MiB)", lambda: edgesam(120))
attempt("EdgeSAM + 130 boxes (response over 32 MiB)", lambda: edgesam(130))
attempt("EdgeSAM + 28 boxes afterwards", lambda: edgesam(28, e1ref))
attempt("YOLOE afterwards", lambda: yoloe(raised))
