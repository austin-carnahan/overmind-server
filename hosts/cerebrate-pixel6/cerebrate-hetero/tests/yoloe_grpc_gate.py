"""Deployment gate for YOLOE through MLServer's gRPC endpoint (runbook step
7): full-size images (4.9 MB in, ~4.6 MB out) with a client receive limit of
32 MiB, outputs vs the validated out-fast bit for bit, the hetero1 slot
before and after (the first request starts it on demand).
usage: yoloe_grpc_gate.py <grpc host:port> <supervisor host> <control port> <hetero dir>"""
import sys, socket, time
import numpy as np, grpc
from mlserver.grpc import dataplane_pb2 as pb, dataplane_pb2_grpc as pbg
GRPC, HOST, CP, D = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]

def slot():
    s = socket.create_connection((HOST, CP)); s.sendall(b"LIST\n\n"); s.shutdown(socket.SHUT_WR); b = b""
    while (c := s.recv(4096)): b += c
    return " | ".join(l[:40] for l in b.decode().splitlines() if l.startswith("hetero"))

stub = pbg.GRPCInferenceServiceStub(grpc.insecure_channel(GRPC, options=[("grpc.max_send_message_length", 33554432), ("grpc.max_receive_message_length", 33554432)]))
print("before:", slot())
same = 0
for i in range(8):
    x = np.load(f"{D}/in{i}.npz")["images"]; ref = np.load(f"{D}/out-fast/out{i}.npz")
    req = pb.ModelInferRequest(model_name="yoloe-v8s-pf"); req.inputs.add(name="images", datatype="FP32", shape=list(x.shape)); req.raw_input_contents.append(x.tobytes())
    t = time.perf_counter(); r = stub.ModelInfer(req, timeout=300); ms = (time.perf_counter() - t) * 1000
    out = {o.name: np.frombuffer(raw, np.float32).reshape(list(o.shape)) for o, raw in zip(r.outputs, r.raw_output_contents)}
    p = {k: v.int64_param for k, v in r.parameters.items()}
    ok = all(np.array_equal(out[n], ref[n]) for n in ref.files); same += ok
    print(f"photo {i}: {x.nbytes / 1e6:.1f} MB in, {sum(len(b) for b in r.raw_output_contents) / 1e6:.1f} MB out, identical {ok}, "
          f"backend {p.get('backend')}, worker {p.get('inference_us', 0) / 1000:.0f} ms, round trip {ms:.0f} ms")
print("after:", slot())
print(f"GATE {'PASS' if same == 8 else 'FAIL'}: {same}/8 identical")
