"""Final results through MLServer (photo hooks, step 2), gRPC with raw
inputs. On the lane photos: result-mode JSON (masks decoded) must equal
photo_postprocess applied to the validated raw outputs (itself checked equal
to PyTorch/Ultralytics by photo_postprocess_check.py), and raw mode must
still be bit-identical. On extra photos (e.g. 1600 x 1200): saves raw and
result outputs to <out dir> for a PyTorch check on the desktop. Then latency
and MLServer peak memory (VmHWM) by boxes per request.
usage: mlserver_result_test.py <grpc host:port> <mlserver pid> <photos dir> <hetero dir> <edgesam dir> <photo boxes npz> <out dir> <lane files x8> -- <extra photos...>"""
import sys, os, json, time
import numpy as np, grpc
from mlserver.grpc import dataplane_pb2 as pb, dataplane_pb2_grpc as pbg
# photo_postprocess from the adapter under test (default: the production checkout's)
sys.path.insert(0, os.environ.get("CG_ADAPTER_DIR", "/home/droid/code/overmind-server/hosts/cerebrate-pixel6/mlserver/models/cerebrate-graph"))
import photo_postprocess as post
GRPC, PID, PD, HD, ED, BOXES, OUT = sys.argv[1:8]
rest = sys.argv[8:]; lane = rest[:rest.index("--")]; extra = rest[rest.index("--") + 1:]
os.makedirs(OUT, exist_ok=True)
stub = pbg.GRPCInferenceServiceStub(grpc.insecure_channel(GRPC, options=[("grpc.max_send_message_length", 33554432), ("grpc.max_receive_message_length", 33554432)]))
pboxes = np.load(BOXES)
def peak():
    st = dict(l.split(":", 1) for l in open(f"/proc/{PID}/status")); return int(st["VmHWM"].split()[0]) // 1024
def infer(model, photo=None, raw=False, **tensors):
    req = pb.ModelInferRequest(model_name=model)
    if raw: req.parameters["output"].string_param = "raw"
    if photo is not None:
        req.inputs.add(name="photo", datatype="BYTES", shape=[1]); req.raw_input_contents.append(len(photo).to_bytes(4, "little") + photo)
    for name, a in tensors.items():
        req.inputs.add(name=name, datatype={np.dtype("float32"): "FP32", np.dtype("int64"): "INT64"}[a.dtype], shape=list(a.shape)); req.raw_input_contents.append(np.ascontiguousarray(a).tobytes())
    a = time.perf_counter(); r = stub.ModelInfer(req, timeout=300); ms = (time.perf_counter() - a) * 1000
    out = {}
    for o, b in zip(r.outputs, r.raw_output_contents):
        out[o.name] = json.loads(b[4:]) if o.datatype == "BYTES" else np.frombuffer(b, {"FP32": np.float32, "INT64": np.int64}[o.datatype]).reshape(list(o.shape))
    return out, {k: v.int64_param for k, v in r.parameters.items()}, ms, len(r.SerializeToString())
def yoloe_expected(raw, shape):
    b, s, c, m = post.yoloe_results(raw["boxes"], raw["score"], raw["cls"], raw["coef"], raw["protos"], shape); return b, s, c, m
h0 = peak(); print(f"idle peak {h0} MB")
ok_r = ok_raw = 0; sizes = []
for i, f in enumerate(lane):
    photo = open(f"{PD}/{f}", "rb").read(); ref = np.load(f"{HD}/out-fast/out{i}.npz")
    res, _, ms, nb = infer("yoloe-v8s-pf", photo); doc = res["result"]; sizes.append(nb)
    shape = (doc["image"]["height"], doc["image"]["width"])
    b, s, c, m = yoloe_expected({k: ref[k] for k in ref.files}, shape)
    dets = doc["detections"]
    same = (len(dets) == len(b) and all(d["class_id"] == int(cc) and np.float32(d["score"]) == ss and np.allclose(d["box"], bb, atol=0, rtol=0)
                                        and np.array_equal(post.decode_mask(d["mask"], shape), mm) for d, bb, ss, cc, mm in zip(dets, b, s, c, m)))
    ok_r += same
    raw, _, _, _ = infer("yoloe-v8s-pf", photo, raw=True); ok_raw += all(np.array_equal(raw[n], ref[n]) for n in ref.files)
    if i == 0: print(f"  YOLOE result: {len(dets)} detections, e.g. {dets[0]['label']!r} {dets[0]['score']:.3f} box {[round(v, 1) for v in dets[0]['box']]}; response {nb / 1e3:.1f} KB")
print(f"YOLOE result mode: {ok_r}/{len(lane)} equal to the validated postprocessing; raw mode {ok_raw}/{len(lane)} bit-identical; responses median {np.median(sizes) / 1e3:.1f} KB; peak +{peak() - h0} MB")
k = 0; ok_e = ok_c = 0
for i, f in enumerate(lane):
    photo = open(f"{PD}/{f}", "rb").read(); bx = pboxes[f"b{i}"]
    logits = np.stack([np.fromfile(f"{ED}/out-sup/edgesam3x-fast/{k + j}_o0.bin", np.float32).reshape(256, 256) for j in range(len(bx))]); k += len(bx)
    res, _, _, nb = infer("edgesam3x-box", photo, image_id=np.array([i], np.int64), boxes=bx); doc = res["result"]
    shape = (doc["image"]["height"], doc["image"]["width"])
    raw, _, _, _ = infer("edgesam3x-box", raw=True, image_id=np.array([i], np.int64), boxes=bx)
    exp = post.sam_masks(logits, tuple(int(v) for v in raw["input_size"].reshape(-1)), shape)
    ok_e += len(doc["masks"]) == len(bx) and all(np.array_equal(post.decode_mask(d["mask"], shape), e) for d, e in zip(doc["masks"], exp))
    resc, _, _, _ = infer("edgesam3x-box", image_id=np.array([i], np.int64), boxes=bx)
    ok_c += resc["result"]["masks"] == doc["masks"]
    if i == 0: print(f"  EdgeSAM result: {len(doc['masks'])} masks, response {nb / 1e3:.1f} KB (raw logits would be {len(bx) * 262144 / 1e6:.1f} MB)")
print(f"EdgeSAM result mode: {ok_e}/{len(lane)} photos equal to postprocess of the validated logits; cached requests identical {ok_c}/{len(lane)}; peak +{peak() - h0} MB")
for j, f in enumerate(extra):
    photo = open(f"{PD}/{f}", "rb").read(); bx = pboxes["b0"] * 2.5   # the lane boxes, scaled to the 2.5x test images
    r1, _, ms1, _ = infer("yoloe-v8s-pf", photo); r2, _, _, _ = infer("yoloe-v8s-pf", photo, raw=True)
    e1, _, ms2, _ = infer("edgesam3x-box", photo, image_id=np.array([100 + j], np.int64), boxes=bx.astype(np.float32))
    e2, _, _, _ = infer("edgesam3x-box", raw=True, image_id=np.array([100 + j], np.int64), boxes=bx.astype(np.float32))
    np.savez(f"{OUT}/extra{j}.npz", **{f"y_{k}": v for k, v in r2.items()}, **{f"e_{k}": v for k, v in e2.items()}, boxes=bx.astype(np.float32))
    json.dump({"yoloe": r1["result"], "edgesam": e1["result"]}, open(f"{OUT}/extra{j}.json", "w"))
    print(f"  extra {f}: {r1['result']['image']}: YOLOE {len(r1['result']['detections'])} detections {ms1:.0f} ms; EdgeSAM {len(bx)} masks {ms2:.0f} ms")
photo = open(f"{PD}/{lane[0]}", "rb").read(); bx = pboxes["b0"]
for label, kw in (("YOLOE photo", dict(model="yoloe-v8s-pf", photo=photo)), ("EdgeSAM photo + 1 box", dict(model="edgesam3x-box", photo=photo, image_id=np.array([0], np.int64), boxes=bx[:1])),
                  ("EdgeSAM cached + 1 box", dict(model="edgesam3x-box", image_id=np.array([0], np.int64), boxes=bx[:1]))):
    v = [infer(**kw) for _ in range(6)][1:]
    print(f"{label}: round trip median {np.median([x[2] for x in v]):.0f} ms, worker {np.median([x[1]['inference_us'] for x in v]) / 1000:.0f} ms")
for n in (24, 96):
    _, p, ms, nb = infer("edgesam3x-box", photo, image_id=np.array([0], np.int64), boxes=np.resize(bx, (n, 4)).astype(np.float32))
    print(f"EdgeSAM photo + {n} boxes: round trip {ms:.0f} ms (worker {p['inference_us'] / 1000:.0f} ms), response {nb / 1e3:.0f} KB; MLServer peak +{peak() - h0} MB")
