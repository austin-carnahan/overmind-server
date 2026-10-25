"""cerebrate-hetero serving EdgeSAM (TPU trunk -> GPU neck, GPU box decoder as
the prompt model, embeddings cached per image_id), from the guest.
  A  per photo, one request {image, image_id, boxes}: all its boxes; outputs
     saved per box (<k>_o0.bin logits, <k>_o1.bin score) in edgesam-tpu's
     index order, for edgesam_decoder_accuracy.py
  B  cache: {image_id, boxes} for the cached photos (cache_entries = 4) must
     equal A bit for bit; an evicted photo must be refused
  C  {image, image_id} alone: acknowledged with image_id
  D  latency, worker-side (inference_us) and round trip: image + 1 box,
     image + 10 boxes, cached image + 1 box, cached image + 10 boxes
usage: edgesam_worker_test.py <host> <port> <inputs dir (photo<i>.npz)> <out dir>"""
import sys, os, socket, time, json
import numpy as np
sys.path.insert(0, "/home/droid/cg-test/mlserver/models/cerebrate-graph")
import cerebrate_graph_protocol as protocol
HOST, PORT, IND, OUT = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
os.makedirs(OUT, exist_ok=True)
s = socket.create_connection((HOST, PORT)); s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
desc, _ = protocol.call(s, {})
print("DESCRIBE:", json.dumps({k: desc[k] for k in ("mode", "tpu", "fallback", "nnapi_cache", "tpu_lock", "load_us", "tpu_load_us", "inputs", "prompt_outputs", "cache_entries")})[:900])
photos = [dict(np.load(f"{IND}/photo{i}.npz")) for i in range(8)]
iid = lambda i: np.array([i], np.int64)
k = 0; first = {}
for i, p in enumerate(photos):
    t = time.perf_counter(); out, done = protocol.call(s, {"image": p["image"], "image_id": iid(i), "boxes": p["boxes"]}); rt = (time.perf_counter() - t) * 1000
    first[i] = out
    for j in range(len(p["boxes"])):
        out["mask_logits"][j].astype(np.float32).tofile(f"{OUT}/{k}_o0.bin"); out["iou"][j].astype(np.float32).tofile(f"{OUT}/{k}_o1.bin"); k += 1
    print(f"A photo {i}: {len(p['boxes'])} boxes, backend {done['backend']}, cache {done['cache']}, tpu {done['tpu_us']/1000:.0f} ms, gpu {done['gpu_us']/1000:.0f} ms, "
          f"prompts {done['prompt_us']/1000:.0f} ms ({done['prompt_us']/1000/len(p['boxes']):.1f}/box), inference {done['inference_us']/1000:.0f} ms, round trip {rt:.0f} ms")
for i in range(8):
    try:
        out, done = protocol.call(s, {"image_id": iid(i), "boxes": photos[i]["boxes"]})
        same = all(np.array_equal(out[n], first[i][n]) for n in out)
        print(f"B photo {i}: cache {done['cache']}, identical to A: {same}")
    except protocol.WorkerError as e:
        print(f"B photo {i}: refused: {e}")
out, done = protocol.call(s, {"image": photos[0]["image"], "image_id": iid(100)})
print(f"C image only: outputs {list(out)} = {out['image_id']}, cache {done['cache']}")
def lat(req, n=6):
    w, r = [], []
    for _ in range(n):
        t = time.perf_counter(); _, done = protocol.call(s, req); r.append((time.perf_counter() - t) * 1000); w.append(done["inference_us"] / 1000)
    return np.median(w), np.median(r)
b = photos[0]["boxes"]
for name, req in (("image + 1 box", {"image": photos[0]["image"], "image_id": iid(0), "boxes": b[:1]}),
                  ("image + 10 boxes", {"image": photos[0]["image"], "image_id": iid(0), "boxes": b[:10]}),
                  ("cached + 1 box", {"image_id": iid(0), "boxes": b[:1]}),
                  ("cached + 10 boxes", {"image_id": iid(0), "boxes": b[:10]})):
    w, r = lat(req)
    print(f"D {name}: worker {w:.0f} ms, round trip {r:.0f} ms")
desc, _ = protocol.call(s, {})
print("health:", desc["health"])
