import sys, traceback
import ultralytics
from ultralytics import YOLOE
print("ultralytics", ultralytics.__version__, flush=True)
for name in sys.argv[1:]:
    try:
        model = YOLOE(name)
        path = model.export(format="onnx", imgsz=640, simplify=True)
        print("EXPORTED", name, path, flush=True)
    except Exception:
        print("FAILED", name, flush=True)
        traceback.print_exc()
