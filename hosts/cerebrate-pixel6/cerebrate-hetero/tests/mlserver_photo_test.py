"""Photo input through MLServer (graph adapter with cerebrate_graph_photo
hooks), over gRPC with the encoded photo as BYTES: outputs must equal the
validated runs bit for bit -- YOLOE vs out-fast; EdgeSAM (YOLOE's boxes in
photo pixels) vs the supervisor-chain outputs, then the same boxes against
the cached image -- and MLServer's peak memory per request (VmHWM of the
server process) is reported after each kind of request.
usage: mlserver_photo_test.py <grpc host:port> <mlserver pid> <photos dir> <hetero dir> <edgesam dir> <photo boxes npz> <photo files in index order...>"""
import sys, time
import numpy as np, grpc
from mlserver.grpc import dataplane_pb2 as pb, dataplane_pb2_grpc as pbg
GRPC, PID, PD, HD, ED, BOXES = sys.argv[1:7]
files = sys.argv[7:]
stub = pbg.GRPCInferenceServiceStub(grpc.insecure_channel(GRPC, options=[("grpc.max_send_message_length", 33554432), ("grpc.max_receive_message_length", 33554432)]))
pboxes = np.load(BOXES)
def peak():
    st = dict(l.split(":", 1) for l in open(f"/proc/{PID}/status")); return int(st["VmHWM"].split()[0]) // 1024, int(st["VmRSS"].split()[0]) // 1024
def infer(model, photo=None, **tensors):
    # Everything raw: MLServer answers raw only when the request is raw (else
    # its outputs come back as repeated floats -- its slow, list-heavy path).
    # BYTES raw = each element prefixed with its 4-byte little-endian length.
    req = pb.ModelInferRequest(model_name=model)
    if photo is not None:
        req.inputs.add(name="photo", datatype="BYTES", shape=[1]); req.raw_input_contents.append(len(photo).to_bytes(4, "little") + photo)
    for name, a in tensors.items():
        req.inputs.add(name=name, datatype={np.dtype("float32"): "FP32", np.dtype("int64"): "INT64"}[a.dtype], shape=list(a.shape))
        req.raw_input_contents.append(np.ascontiguousarray(a).tobytes())
    a = time.perf_counter(); r = stub.ModelInfer(req, timeout=300); ms = (time.perf_counter() - a) * 1000
    nd = {"FP32": np.float32, "INT64": np.int64}
    out = {o.name: np.frombuffer(raw, nd[o.datatype]).reshape(list(o.shape)) for o, raw in zip(r.outputs, r.raw_output_contents)}
    return out, {k: v.int64_param for k, v in r.parameters.items()}, ms, len(r.SerializeToString())
h0 = peak(); print(f"idle: peak {h0[0]} MB, RSS {h0[1]} MB")
ok = 0; times = []
for i, f in enumerate(files):
    photo = open(f"{PD}/{f}", "rb").read(); ref = np.load(f"{HD}/out-fast/out{i}.npz")
    out, p, ms, nbytes = infer("yoloe-v8s-pf", photo)
    same = all(np.array_equal(out[n], ref[n]) for n in ref.files); ok += same; times.append(ms)
    if i == 0: print(f"  YOLOE extra outputs: letterbox {out['letterbox']}, original_size {out['original_size']}; photo {len(photo) / 1e3:.0f} KB in, {nbytes / 1e6:.1f} MB out")
print(f"YOLOE photo: {ok}/{len(files)} identical to the validated outputs, round trip median {np.median(times[1:]):.0f} ms (first {times[0]:.0f}); peak now {peak()[0]} MB (+{peak()[0] - h0[0]})")
k = 0; ok = okc = 0; t1 = []; tc = []
for i, f in enumerate(files):
    photo = open(f"{PD}/{f}", "rb").read(); b = pboxes[f"b{i}"]
    ref = np.stack([np.fromfile(f"{ED}/out-sup/edgesam3x-fast/{k + j}_o0.bin", np.float32).reshape(1, 256, 256) for j in range(len(b))]); k += len(b)
    out, p, ms, _ = infer("edgesam3x-box", photo, image_id=np.array([i], np.int64), boxes=b)
    ok += np.array_equal(out["mask_logits"], ref); t1.append(ms)
    outc, pc, msc, _ = infer("edgesam3x-box", image_id=np.array([i], np.int64), boxes=b)
    okc += np.array_equal(outc["mask_logits"], ref); tc.append(msc)
    if i == 0: print(f"  EdgeSAM extra outputs: input_size {out['input_size']}, original_size {out['original_size']}, cache {p.get('cache')}/{pc.get('cache')}")
print(f"EdgeSAM photo + boxes: {ok}/{len(files)} identical; cached + boxes: {okc}/{len(files)} identical; peak now {peak()[0]} MB (+{peak()[0] - h0[0]})")
b = pboxes["b0"]; photo = open(f"{PD}/{files[0]}", "rb").read()
lat = {}
for label, kw in (("photo + 1 box", dict(photo=photo, image_id=np.array([0], np.int64), boxes=b[:1])), ("cached + 1 box", dict(image_id=np.array([0], np.int64), boxes=b[:1])),
                  ("photo + 24 boxes", dict(photo=photo, image_id=np.array([0], np.int64), boxes=np.resize(b, (24, 4)).astype(np.float32)))):
    v = [infer("edgesam3x-box", **kw) for _ in range(6)][1:]
    print(f"EdgeSAM {label}: round trip median {np.median([x[2] for x in v]):.0f} ms, worker {np.median([x[1]['inference_us'] for x in v]) / 1000:.0f} ms; peak now {peak()[0]} MB (+{peak()[0] - h0[0]})")
