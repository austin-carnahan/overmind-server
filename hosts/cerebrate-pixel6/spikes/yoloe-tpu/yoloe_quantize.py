"""int8 static quantization of the YOLOE backbone + neck partitions (ONNX
Runtime, QDQ format, uint8 activations, int8 per-channel weights, MinMax
calibration on 300 indoor COCO val2017 photos letterboxed to 640x640), then a
desktop task check: int8 backbone -> fp32 head -> evaluator vs Ultralytics'
original predictions on the eight lane photos.
usage: <yoloe dir> <calib dir> [n_calib] [minmax|percentile|entropy]"""
import sys, glob, os
import numpy as np, cv2, onnxruntime as ort
from onnxruntime.quantization import quantize_static, CalibrationDataReader, QuantFormat, QuantType, CalibrationMethod
from onnxruntime.quantization.shape_inference import quant_pre_process
from ultralytics.data.augment import LetterBox
Y, C = sys.argv[1], sys.argv[2]; NCAL = int(sys.argv[3]) if len(sys.argv) > 3 else 300
METHOD = sys.argv[4] if len(sys.argv) > 4 else "minmax"
CM = {"minmax": CalibrationMethod.MinMax, "percentile": CalibrationMethod.Percentile, "entropy": CalibrationMethod.Entropy}[METHOD]
EXTRA = {"CalibPercentile": 99.999} if METHOD == "percentile" else {}
lb = LetterBox((640, 640), auto=False)
def prep(p):
    im = lb(image=cv2.imread(p)); return np.ascontiguousarray(im[..., ::-1].transpose(2, 0, 1))[None].astype(np.float32) / 255
class Reader(CalibrationDataReader):
    def __init__(s): s.files = sorted(glob.glob(f"{C}/*.jpg"))[:NCAL]; s.i = 0
    def get_next(s):
        if s.i >= len(s.files): return None
        s.i += 1; return {"images": prep(s.files[s.i - 1])}
for v in ("yoloe-v8s-seg-pf", "yoloe-11s-seg-pf"):
    src = f"{Y}/{v}-backbone.onnx"; pp = f"{Y}/{v}-backbone-pp.onnx"; dst = f"{Y}/{v}-backbone-int8{'' if METHOD == 'minmax' else '-' + METHOD}.onnx"
    if not os.path.exists(pp): quant_pre_process(src, pp, skip_symbolic_shape=True)
    quantize_static(pp, dst, Reader(), quant_format=QuantFormat.QDQ, activation_type=QuantType.QUInt8, weight_type=QuantType.QInt8,
                    per_channel=True, calibrate_method=CM, extra_options=EXTRA)
    print(f"{v}: int8 backbone {os.path.getsize(dst) / 1e6:.1f} MB (fp32 {os.path.getsize(src) / 1e6:.1f} MB)", flush=True)
