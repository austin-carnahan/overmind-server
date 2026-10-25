"""Peak memory of an MLServer process serving EdgeSAM requests through the
graph adapter, by boxes per request: MLServer's NumpyCodec turns each output
into a Python list (~262 KB of float32 logits per box -> tens of MB of
Python floats). Reads the server's VmHWM after each request size, in
increasing order, and stops before <limit MB>.
usage: mlserver_memory_per_box.py <grpc host:port> <mlserver pid> <edgesam dir> <limit MB> <box counts...>"""
import sys
import numpy as np, grpc
from mlserver.grpc import dataplane_pb2 as pb, dataplane_pb2_grpc as pbg
GRPC, PID, ED, LIMIT = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4])
stub = pbg.GRPCInferenceServiceStub(grpc.insecure_channel(GRPC, options=[("grpc.max_send_message_length", 33554432), ("grpc.max_receive_message_length", 33554432)]))
def mem():
    st = dict(l.split(":", 1) for l in open(f"/proc/{PID}/status"))
    return int(st["VmRSS"].split()[0]) / 1024, int(st["VmHWM"].split()[0]) / 1024
p = dict(np.load(f"{ED}/photo1.npz"))
rss0, hwm0 = mem(); print(f"before: RSS {rss0:.0f} MB, peak {hwm0:.0f} MB")
for n in map(int, sys.argv[5:]):
    req = pb.ModelInferRequest(model_name="edgesam3x-box")
    for name, a in (("image", p["image"]), ("image_id", np.array([1], np.int64)), ("boxes", np.resize(p["boxes"], (n, 1, 4)).astype(np.float32))):
        req.inputs.add(name=name, datatype="FP32" if a.dtype == np.float32 else "INT64", shape=list(a.shape)); req.raw_input_contents.append(a.tobytes())
    stub.ModelInfer(req, timeout=300)
    rss, hwm = mem()
    print(f"{n:3d} boxes ({n * 262144 / 1e6:4.1f} MB of logits): peak {hwm:.0f} MB (+{hwm - hwm0:.0f} over the idle baseline), RSS after {rss:.0f} MB", flush=True)
    if hwm > LIMIT: print(f"stopping: peak above {LIMIT:.0f} MB"); break
