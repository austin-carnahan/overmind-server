"""Same-input conversion check: photos letterboxed to 640x640 once
(Ultralytics LetterBox, auto=False), then predicted by the original .pt and
the fp32 ONNX export. Also the raw class-score range on real photos."""
import sys, glob
import numpy as np, cv2
from ultralytics import YOLOE
from ultralytics.data.augment import LetterBox
import onnxruntime as ort
D = sys.argv[1]
BP = "/Users/dev/Code/browser-perception/demos"
imgs = sorted(glob.glob(f"{BP}/object-selection/samples/*.jpg"))[:5] + sorted(glob.glob(f"{BP}/segmentation/samples/*.jpg"))[:3]
lb = LetterBox((640, 640), auto=False)
sq = [lb(image=cv2.imread(p)) for p in imgs]
for v in ("yoloe-v8s-seg-pf", "yoloe-11s-seg-pf"):
    pt = YOLOE(f"{D}/{v}.pt"); ox = YOLOE(f"{D}/{v}.onnx"); names = pt.names
    s = ort.InferenceSession(f"{D}/{v}.onnx"); mx = []
    for i, im in enumerate(sq):
        a = pt.predict(im, imgsz=640, verbose=False)[0]; b = ox.predict(im, imgsz=640, verbose=False)[0]
        la = sorted([(names[int(c)], round(float(s_), 2)) for c, s_ in zip(a.boxes.cls, a.boxes.conf)], key=lambda t: -t[1])
        lbb = sorted([(names[int(c)], round(float(s_), 2)) for c, s_ in zip(b.boxes.cls, b.boxes.conf)], key=lambda t: -t[1])
        x = np.ascontiguousarray(im[..., ::-1].transpose(2, 0, 1))[None].astype(np.float32) / 255
        o0 = s.run(None, {s.get_inputs()[0].name: x})[0][0]; mx.append(float(o0[4:4589].max()))
        if i < 3: print(f"{v} photo {i}: pt {len(la)} {la[:6]}\n{'':>26}onnx {len(lbb)} {lbb[:6]}", flush=True)
    print(f"  {v}: max class score per photo {[round(m, 3) for m in mx]}")
