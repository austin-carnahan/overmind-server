"""Sample outputs from the Pixel's vision and text models for one photo, for
people to look at (Granite-Docling, a document converter, is left out):
each model's request through MLServer (gRPC), its JSON result, a rendered
overlay, timings (the first request to a model includes its on-demand start),
summary.md and an index.html contact sheet. Prompts are deliberately basic.
Run in the guest with the MLServer venv:
  sample_outputs.py <grpc host:port> <photo.jpg> <out dir> [<other photos for DINOv2 similarity>...]"""
import base64
import html
import json
import os
import sys
import time

import cv2
import grpc
import numpy as np
from mlserver.grpc import dataplane_pb2 as pb, dataplane_pb2_grpc as pbg

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "mlserver", "models", "cerebrate-graph"))
from photo_postprocess import decode_mask  # noqa: E402

GRPC, PHOTO, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
OTHERS = sys.argv[4:]
stub = pbg.GRPCInferenceServiceStub(grpc.insecure_channel(GRPC, options=[("grpc.max_send_message_length", 33554432), ("grpc.max_receive_message_length", 33554432)]))
os.makedirs(OUT, exist_ok=True)
photo_bytes = open(PHOTO, "rb").read()
img = cv2.imread(PHOTO)                      # BGR, for drawing
H, W = img.shape[:2]
sections, summary = [], []
OBJECT_PROMPTS = ["bed", "pillow", "lamp", "suitcase", "backpack"]
OWL_QUERIES = ["a bed", "a pillow", "a lamp", "a suitcase", "a backpack", "a window", "a chair", "a curtain"]
BAG_WORDS = ("bag", "suitcase", "luggage", "backpack", "baggage")


def infer(model, tensors=None, **byte_inputs):
    req = pb.ModelInferRequest(model_name=model)
    for name, values in byte_inputs.items():
        req.inputs.add(name=name, datatype="BYTES", shape=[len(values)])
        req.raw_input_contents.append(b"".join(len(v).to_bytes(4, "little") + v for v in values))
    for name, a in (tensors or {}).items():
        req.inputs.add(name=name, datatype={np.dtype("float32"): "FP32", np.dtype("int64"): "INT64"}[a.dtype], shape=list(a.shape))
        req.raw_input_contents.append(np.ascontiguousarray(a).tobytes())
    t = time.perf_counter()
    r = stub.ModelInfer(req, timeout=900)
    return r, time.perf_counter() - t


def result_json(r):
    return json.loads(r.raw_output_contents[[o.name for o in r.outputs].index("result")][4:])


def bytes_output(r, name):
    return r.raw_output_contents[[o.name for o in r.outputs].index(name)][4:].decode("utf-8", "replace")


def color(i):
    palette = [(66, 135, 245), (245, 66, 66), (66, 245, 135), (245, 200, 66), (200, 66, 245), (66, 230, 245),
               (245, 120, 200), (150, 245, 66), (245, 150, 66), (120, 120, 245)]
    return palette[i % len(palette)]


def area(box):
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1]) / (W * H)


def header(canvas, title):
    bar = np.full((30, canvas.shape[1], 3), 32, np.uint8)
    cv2.putText(bar, title, (8, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
    return np.concatenate([bar, canvas], axis=0)


def draw(items, title, masks=True):
    """items: dicts with box, label, score, optional mask -> annotated BGR image
    (masks of room-sized detections are left out so the photo stays readable)."""
    canvas = img.copy()
    overlay = img.copy()
    for i, it in enumerate(items):
        c = color(i)
        if masks and it.get("mask") and area(it["box"]) < 0.6:
            m = decode_mask(it["mask"], (H, W))
            overlay[m] = (0.45 * np.array(c) + 0.55 * overlay[m]).astype(np.uint8)
    canvas = overlay
    for i, it in enumerate(items):
        c = color(i)
        x0, y0, x1, y1 = [int(round(v)) for v in it["box"]]
        cv2.rectangle(canvas, (x0, y0), (x1, y1), c, 2)
        text = f"{it.get('label', '')} {it['score']:.2f}".strip()
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.rectangle(canvas, (x0, max(0, y0 - th - 6)), (x0 + tw + 4, max(th + 6, y0)), c, -1)
        cv2.putText(canvas, text, (x0 + 2, max(th + 2, y0 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    return header(canvas, title)


def save(folder, name, data):
    d = os.path.join(OUT, folder)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, name)
    if isinstance(data, np.ndarray):
        cv2.imwrite(path, data)
    elif isinstance(data, (dict, list)):
        with open(path, "w") as f:
            json.dump(data, f, indent=1)
    else:
        with open(path, "w") as f:
            f.write(data)
    return f"{folder}/{name}"


def section(folder, title, model, request, seconds, images, text):
    sections.append({"folder": folder, "title": title, "model": model, "request": request,
                     "seconds": seconds, "images": images, "text": text})
    summary.append(f"## {title}\n\nEndpoint `{model}`; request: {request}; {seconds:.1f} s\n\n{text}\n")
    print(f"{title}: {seconds:.1f} s", flush=True)


def run(step):
    try:
        step()
    except Exception as exc:   # one failing model shouldn't hide the others
        print(f"  {step.__name__} failed: {exc}", flush=True)
        summary.append(f"## {step.__name__}\n\nFAILED: {exc}\n")


cv2.imwrite(os.path.join(OUT, "00_photo.jpg"), img)
state = {}


def yoloe_v8s():
    r, s = infer("yoloe-v8s-pf", photo=[photo_bytes])
    res = result_json(r)
    dets = sorted(res["detections"], key=lambda d: -d["score"])
    state["yoloe"] = dets
    shown = dets[:20]
    imgs = [save("01_yoloe-v8s", "overlay.png", draw(shown, "YOLOE-v8s prompt-free (4,585 classes), top 20"))]
    save("01_yoloe-v8s", "result.json", res)
    text = f"{len(dets)} detections. Top: " + ", ".join(f"{d['label']} {d['score']:.2f}" for d in dets[:12])
    section("01_yoloe-v8s", "YOLOE-v8s: prompt-free detection + masks", "yoloe-v8s-pf", "the photo", s, imgs, text)


def yoloe_11s():
    r, s = infer("yoloe-11s-pf", photo=[photo_bytes])
    res = result_json(r)
    dets = sorted(res["detections"], key=lambda d: -d["score"])
    imgs = [save("02_yoloe-11s", "overlay.png", draw(dets[:20], "YOLOE-11s prompt-free, top 20"))]
    save("02_yoloe-11s", "result.json", res)
    text = f"{len(dets)} detections. Top: " + ", ".join(f"{d['label']} {d['score']:.2f}" for d in dets[:12])
    section("02_yoloe-11s", "YOLOE-11s: prompt-free detection + masks", "yoloe-11s-pf", "the photo", s, imgs, text)


def rfdetr():
    r, s = infer("rf-detr-seg-nano", photo=[photo_bytes])
    res = result_json(r)
    dets = sorted(res["detections"], key=lambda d: -d["score"])
    imgs = [save("03_rf-detr", "overlay.png", draw(dets, "RF-DETR-Seg-Nano (COCO 80 classes)"))]
    save("03_rf-detr", "result.json", res)
    text = f"{len(dets)} detections: " + ", ".join(f"{d['label']} {d['score']:.2f}" for d in dets)
    section("03_rf-detr", "RF-DETR-Seg-Nano: fixed-class detection + masks", "rf-detr-seg-nano", "the photo", s, imgs, text)


def owlv2():
    r, s = infer("owlv2-b16", photo=[photo_bytes], queries=[q.encode() for q in OWL_QUERIES])
    res = result_json(r)
    items = [{"box": d["box"], "score": d["score"], "label": q["text"]} for q in res["queries"] for d in q["detections"]]
    imgs = [save("04_owlv2", "overlay.png", draw(items, "OWLv2: open-vocabulary detection", masks=False))]
    save("04_owlv2", "result.json", res)
    text = "Queries: " + "; ".join(f"{q['text']}: {len(q['detections'])}" + (f" (best {max(d['score'] for d in q['detections']):.2f})" if q["detections"] else "")
                                   for q in res["queries"])
    section("04_owlv2", "OWLv2: open-vocabulary detection", "owlv2-b16", f"the photo + {len(OWL_QUERIES)} text queries", s, imgs, text)


def esam3():
    imgs, lines, total = [], [], 0.0
    for i, p in enumerate(OBJECT_PROMPTS):
        kw = {"photo": [photo_bytes]} if i == 0 else {}
        r, s = infer("efficientsam3-rvm", {"image_id": np.array([4242], np.int64)}, prompts=[p.encode()], **kw)
        total += s
        res = result_json(r)
        pr = res["prompts"][0]
        items = [{"box": d["box"], "score": d["score"], "label": p, "mask": d["mask"]} for d in pr["detections"]]
        imgs.append(save("05_efficientsam3", f"prompt-{p}.png", draw(items, f"EfficientSAM3: '{p}' (presence {pr['presence']:.2f})")))
        save("05_efficientsam3", f"result-{p}.json", res)
        lines.append(f"'{p}': {len(items)} instance(s), presence {pr['presence']:.2f}, {s:.1f} s")
    section("05_efficientsam3", "EfficientSAM3: text-prompted segmentation", "efficientsam3-rvm",
            f"the photo once (cached), then one phrase per request: {', '.join(OBJECT_PROMPTS)}", total, imgs, "\n".join(f"- {l}" for l in lines))


def box_prompts():
    """Box prompts for the refinement models: YOLOE's best object-sized
    detections (2-40 % of the photo), at most one per label."""
    seen, boxes = set(), []
    for d in state.get("yoloe", []):
        if d["label"] not in seen and 0.02 <= area(d["box"]) <= 0.4:
            seen.add(d["label"])
            boxes.append((d["label"], d["box"]))
        if len(boxes) == 4:
            break
    return boxes


def refine(model, folder, title):
    boxes = box_prompts()
    arr = np.array([b for _, b in boxes], np.float32)
    r, s = infer(model, {"image_id": np.array([4243 if "sam2" in model else 4244], np.int64), "boxes": arr}, photo=[photo_bytes])
    res = result_json(r)
    items = [{"box": m["box"], "score": m["score"], "label": lab, "mask": m["mask"]} for (lab, _), m in zip(boxes, res["masks"])]
    imgs = [save(folder, "overlay.png", draw(items, title))]
    save(folder, "result.json", res)
    text = "Box prompts from YOLOE's detections: " + ", ".join(f"{lab} (mask score {m['score']:.2f})" for (lab, _), m in zip(boxes, res["masks"]))
    section(folder, title, model, f"the photo + {len(boxes)} boxes", s, imgs, text)


def edgesam():
    refine("edgesam3x-box", "06_edgesam", "EdgeSAM: box -> mask refinement")


def sam2():
    refine("sam2.1-hiera-tiny", "07_sam2", "SAM 2.1 (FP32, quality): box -> mask refinement")


def depth():
    r, s = infer("depth-anything-v2-small", photo=[photo_bytes])
    res = result_json(r)
    d = cv2.imdecode(np.frombuffer(base64.b64decode(res["depth"]["data"]), np.uint8), cv2.IMREAD_UNCHANGED)
    vis = cv2.applyColorMap((d / 256).astype(np.uint8), cv2.COLORMAP_INFERNO)
    vis = cv2.resize(vis, (W, H), interpolation=cv2.INTER_LINEAR)
    side = header(np.concatenate([img, vis], axis=1), "Depth Anything V2: photo -> relative depth (brighter = nearer)")
    imgs = [save("08_depth", "depth.png", vis), save("08_depth", "side-by-side.png", side)]
    res["depth"]["data"] = f"<{len(res['depth']['data'])} base64 chars: depth.png>"
    save("08_depth", "result.json", res)
    section("08_depth", "Depth Anything V2: relative depth", "depth-anything-v2-small", "the photo", s, imgs,
            "Brighter = nearer (relative inverse depth, colour-mapped).")


def migan():
    dets = state.get("yoloe", [])
    bags = [d for d in dets if any(w in d["label"].lower() for w in BAG_WORDS)] or dets[:1]
    small = [d for d in bags if area(d["box"]) < 0.12] or bags[:1]
    imgs, lines, total = [], [], 0.0
    for tag, chosen, note in (("one-bag", small[:1], "one object"), ("all-bags", bags[:6], "every bag: a stress test, much larger than MI-GAN's comfort zone")):
        mask = np.zeros((H, W), np.uint8)
        for d in chosen:
            mask[decode_mask(d["mask"], (H, W))] = 255
        mask = cv2.dilate(mask, np.ones((15, 15), np.uint8))
        ok, mask_png = cv2.imencode(".png", mask)
        r, s = infer("mi-gan-512", photo=[photo_bytes], mask=[mask_png.tobytes()])
        total += s
        out = cv2.imdecode(np.frombuffer(base64.b64decode(result_json(r)["result"]), np.uint8), cv2.IMREAD_COLOR)
        shown = img.copy()
        shown[mask > 0] = (0.5 * shown[mask > 0] + 0.5 * np.array([0, 0, 255])).astype(np.uint8)
        save("09_migan", f"{tag}-mask.png", mask)
        save("09_migan", f"{tag}-inpainted.png", out)
        imgs.append(save("09_migan", f"{tag}-side-by-side.png",
                         header(np.concatenate([shown, out], axis=1), f"MI-GAN, {note}: mask (red) -> result")))
        lines.append(f"- {note}: {', '.join(sorted({d['label'] for d in chosen}))}; {100 * (mask > 0).mean():.0f} % of the photo masked; {s:.1f} s")
    section("09_migan", "MI-GAN: inpainting", "mi-gan-512", "the photo + a mask built from YOLOE's bag masks (dilated 7 px)",
            total, imgs, "\n".join(lines))


def dinov2():
    def embed(path):
        r, s = infer("dinov2-s14", photo=[open(path, "rb").read()])
        e = np.frombuffer(base64.b64decode(result_json(r)["embedding"]["data"]), "<f4")
        return e / np.linalg.norm(e), s
    ref, s = embed(PHOTO)
    rows = [f"| {os.path.basename(p)} | {float(np.dot(ref, embed(p)[0])):.3f} |" for p in OTHERS]
    thumbs = []
    for p in OTHERS:
        t = cv2.imread(p)
        thumbs.append(save("10_dinov2", f"compare-{os.path.basename(p)}", cv2.resize(t, (240, int(240 * t.shape[0] / t.shape[1])))))
    text = ("Cosine similarity of the photo's 384-d embedding to other photos:\n\n| Photo | Similarity |\n| --- | --- |\n"
            + "\n".join(rows))
    section("10_dinov2", "DINOv2-S/14: image embedding", "dinov2-s14", "the photo, then each comparison photo", s, thumbs, text)


def mobilenet():
    r, s = infer("cerebrate-infer", image=[base64.b64encode(photo_bytes)])
    label = bytes_output(r, "label")
    conf = np.frombuffer(r.raw_output_contents[[o.name for o in r.outputs].index("confidence")], "<f4")[0]
    section("11_mobilenet", "MobileNet v1: ImageNet classification", "cerebrate-infer", "the photo", s, [],
            f"Top class: **{label}** ({conf:.2f}). (1,000 ImageNet classes, 224x224 input.)")


def smollm2():
    prompt = "List three things a traveler usually finds in a hotel room."
    r, s = infer("cerebrate-generate", prompt=[prompt.encode()])
    text = bytes_output(r, "text").strip()
    save("12_smollm2", "response.txt", text)
    section("12_smollm2", "SmolLM2-135M: text generation", "cerebrate-generate", f"prompt: \"{prompt}\" (text only)", s, [], f"> {text}")


for step in (yoloe_v8s, yoloe_11s, rfdetr, owlv2, esam3, edgesam, sam2, depth, migan, dinov2, mobilenet, smollm2):
    run(step)

with open(os.path.join(OUT, "summary.md"), "w") as f:
    f.write(f"# Sample outputs: {os.path.basename(PHOTO)} ({W}x{H})\n\nGenerated {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())} "
            "through production MLServer. Times include a worker's on-demand start on its first request.\n\n" + "\n".join(summary))
cards = []
for sec in sections:
    pics = "".join(f'<a href="{html.escape(p)}"><img src="{html.escape(p)}"></a>' for p in sec["images"])
    cards.append(f'<section><h2>{html.escape(sec["title"])}</h2><p class="meta"><code>{html.escape(sec["model"])}</code> · '
                 f'{html.escape(sec["request"])} · {sec["seconds"]:.1f} s</p><div class="pics">{pics}</div>'
                 f'<pre>{html.escape(sec["text"])}</pre></section>')
with open(os.path.join(OUT, "index.html"), "w") as f:
    f.write(f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pixel model samples</title><style>
:root {{ --bg:#fafafa; --fg:#1d1d1f; --card:#fff; --muted:#666; --line:#e2e2e2; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#141416; --fg:#ececec; --card:#1d1d20; --muted:#9a9a9a; --line:#333; }} }}
body {{ background:var(--bg); color:var(--fg); font:15px/1.5 -apple-system,system-ui,sans-serif; margin:0 auto; max-width:1200px; padding:16px; }}
section {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:12px 16px; margin:14px 0; }}
h2 {{ margin:4px 0; font-size:18px; }} .meta {{ color:var(--muted); margin:2px 0 10px; }}
.pics {{ display:flex; flex-wrap:wrap; gap:8px; }} .pics img {{ max-width:100%; width:360px; border-radius:6px; border:1px solid var(--line); }}
pre {{ white-space:pre-wrap; font-size:13px; }} </style></head><body>
<h1>Pixel model samples: {html.escape(os.path.basename(PHOTO))}</h1>
<p class="meta">{W}×{H}, through production MLServer, {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}. Times include each worker's on-demand start.</p>
<section><h2>Input</h2><div class="pics"><img src="00_photo.jpg"></div></section>
{''.join(cards)}</body></html>""")
print(f"wrote {OUT}/index.html and summary.md ({len(sections)} models)")
