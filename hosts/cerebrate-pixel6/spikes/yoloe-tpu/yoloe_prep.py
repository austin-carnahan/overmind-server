"""Step 2B, step 1: YOLOE prompt-free (v8s, 11s) model preparation, inputs and
references.
- Reduced outputs: output0 [1, 4+4585+32, 8400] (~155 MB fp32) is a Concat of
  boxes, sigmoid class scores and mask coefficients; graph surgery takes those
  three tensors directly (no 155 MB concat) and appends the best score and
  class per anchor: boxes [1,4,8400] (cx,cy,w,h px), score [1,8400], cls
  [1,8400] (int64), coef [1,32,8400]; protos kept.
- DFL box decoding as a 2-D softmax (dfl_2d): the Edge TPU converter rejected
  the box head's 4-D softmax ("RET_CHECK axis == -1 || axis == input_rank -
  1"); exact.
- Split -> Slice: every Split (all equal channel halves) becomes Slices --
  ORT 1.30's NNAPI provider fails to build Split here ("AddNnapiSplit count
  [0] does not evenly divide dimension"); exact.
- Inputs: the eight lane photos letterboxed to 640x640 (Ultralytics
  LetterBox, auto=False -- the fixed-shape models' input; Ultralytics'
  PyTorch predict otherwise uses a minimal rectangle and is not comparable).
- References: the reduced ONNX on the desktop CPU (raw, for graph-client
  --reference), and Ultralytics' predictions from the original .pt on the
  same inputs (task level). The reduced outputs are checked against the
  unmodified ONNX.
- Evaluator check: Ultralytics' own NMS + mask functions applied to the
  reduced outputs (best class only, as its single-label path uses) must
  reproduce the .pt predictions (up to fp32 ONNX-vs-PyTorch rounding).
usage: <dl-yoloe dir> <out dir>"""
import sys, glob
import numpy as np, cv2, torch, onnx
from onnx import helper, TensorProto, numpy_helper
import onnxruntime as ort
from ultralytics import YOLOE
from ultralytics.data.augment import LetterBox
from ultralytics.utils import nms as unms
from ultralytics.utils import ops
NC = 4585
BP = "/Users/dev/Code/browser-perception/demos"
imgs = sorted(glob.glob(f"{BP}/object-selection/samples/*.jpg"))[:5] + sorted(glob.glob(f"{BP}/segmentation/samples/*.jpg"))[:3]
lb = LetterBox((640, 640), auto=False)
sq = [lb(image=cv2.imread(p)) for p in imgs]
X = [np.ascontiguousarray(im[..., ::-1].transpose(2, 0, 1))[None].astype(np.float32) / 255 for im in sq]


def reduce_onnx(src, dst):
    m = onnx.load(src); g = m.graph
    out0 = g.output[0].name
    cat = next(n for n in g.node if out0 in n.output)
    assert cat.op_type == "Concat" and len(cat.input) == 3
    b_in, s_in, k_in = cat.input
    g.node.remove(cat)
    g.initializer.append(helper.make_tensor("r_ax", TensorProto.INT64, [1], [1]))
    g.node.extend([helper.make_node("Identity", [b_in], ["boxes"]), helper.make_node("Identity", [k_in], ["coef"]),
                   helper.make_node("ReduceMax", [s_in, "r_ax"], ["score"], keepdims=0),
                   helper.make_node("ArgMax", [s_in], ["cls"], axis=1, keepdims=0)])
    protos = g.output[1]
    del g.output[:]
    g.output.extend([helper.make_tensor_value_info("boxes", TensorProto.FLOAT, [1, 4, 8400]),
                     helper.make_tensor_value_info("score", TensorProto.FLOAT, [1, 8400]),
                     helper.make_tensor_value_info("cls", TensorProto.INT64, [1, 8400]),
                     helper.make_tensor_value_info("coef", TensorProto.FLOAT, [1, 32, 8400]), protos])
    dfl_2d(g)
    split_to_slice(g)
    onnx.checker.check_model(m); onnx.save(m, dst)


def dfl_2d(g):
    """DFL: x [1,4,16,8400] -> Transpose(0,2,1,3) -> Softmax(axis 1) -> Conv 1x1
    (weights 0..15) -> Reshape [1,4,8400] becomes Transpose(0,1,3,2) -> Reshape
    [33600,16] -> Softmax(-1) -> MatMul [16,1] (the same weights) -> Reshape
    [1,4,8400]."""
    by_out = {o: n for n in g.node for o in n.output}
    sm = next(n for n in g.node if n.op_type == "Softmax" and "dfl" in n.name)
    tr = by_out[sm.input[0]]
    conv = next(n for n in g.node if sm.output[0] in n.input)
    rs1 = next(n for n in g.node if conv.output[0] in n.input)
    assert tr.op_type == "Transpose" and conv.op_type == "Conv" and rs1.op_type == "Reshape"
    w = numpy_helper.to_array(next(i for i in g.initializer if i.name == conv.input[1])).reshape(16, 1).astype(np.float32)
    g.initializer.extend([numpy_helper.from_array(w, "dfl_w"),
                          helper.make_tensor("dfl_s1", TensorProto.INT64, [2], [33600, 16]),
                          helper.make_tensor("dfl_s2", TensorProto.INT64, [3], [1, 4, 8400])])
    new = [helper.make_node("Transpose", [tr.input[0]], ["dfl_t"], perm=[0, 1, 3, 2], name="dfl2d_t"),
           helper.make_node("Reshape", ["dfl_t", "dfl_s1"], ["dfl_r"], name="dfl2d_r"),
           helper.make_node("Softmax", ["dfl_r"], ["dfl_sm"], axis=-1, name="dfl2d_softmax"),
           helper.make_node("MatMul", ["dfl_sm", "dfl_w"], ["dfl_mm"], name="dfl2d_matmul"),
           helper.make_node("Reshape", ["dfl_mm", "dfl_s2"], [rs1.output[0]], name="dfl2d_r2")]
    idx = list(g.node).index(tr)
    for n in (tr, sm, conv, rs1):
        g.node.remove(n)
    for k, n in enumerate(new):
        g.node.insert(idx + k, n)


def split_to_slice(g):
    init = {i.name: numpy_helper.to_array(i) for i in g.initializer}
    new = []
    for n in g.node:
        if n.op_type != "Split":
            new.append(n); continue
        axis = next((a.i for a in n.attribute if a.name == "axis"), 0)
        sizes = init[n.input[1]].tolist(); start = 0
        for k, (out, sz) in enumerate(zip(n.output, sizes)):
            nm = f"{n.name}_slice{k}"
            g.initializer.extend([helper.make_tensor(nm + "_s", TensorProto.INT64, [1], [start]),
                                  helper.make_tensor(nm + "_e", TensorProto.INT64, [1], [start + sz]),
                                  helper.make_tensor(nm + "_a", TensorProto.INT64, [1], [axis])])
            new.append(helper.make_node("Slice", [n.input[0], nm + "_s", nm + "_e", nm + "_a"], [out], name=nm)); start += sz
    del g.node[:]; g.node.extend(new)


def detections(boxes, score, cls, coef, protos, conf=0.25, iou=0.7):
    """Ultralytics' NMS + masks on the reduced outputs (best class only), with
    the YOLOE predictor's settings: conf 0.25, IoU 0.7, class-agnostic NMS."""
    pred = torch.zeros(1, 4 + NC + 32, 8400)
    pred[0, :4] = torch.from_numpy(boxes[0]); pred[0, 4 + NC:] = torch.from_numpy(coef[0])
    pred[0, 4 + torch.from_numpy(cls[0]).long(), torch.arange(8400)] = torch.from_numpy(score[0])
    det = unms.non_max_suppression(pred, conf, iou, agnostic=True, nc=NC, max_det=300)[0]
    det[:, :4] = ops.clip_boxes(det[:, :4], (640, 640))          # as Ultralytics' results do
    masks = ops.process_mask(torch.from_numpy(protos[0]), det[:, 6:], det[:, :4], (640, 640), upsample=True) if len(det) else torch.zeros(0, 640, 640)
    return det[:, :6].numpy(), masks.numpy() > 0.5


if __name__ == "__main__":
    D, OUT = sys.argv[1], sys.argv[2]
    for i, x in enumerate(X):
        np.savez(f"{OUT}/in{i}.npz", images=x)
    for v in ("yoloe-v8s-seg-pf", "yoloe-11s-seg-pf"):
        red = f"{OUT}/{v}-reduced.onnx"; reduce_onnx(f"{D}/{v}.onnx", red)
        sess = ort.InferenceSession(red); orig = ort.InferenceSession(f"{D}/{v}.onnx"); pt = YOLOE(f"{D}/{v}.pt")
        same = 0
        for i, (x, im) in enumerate(zip(X, sq)):
            o = dict(zip([s.name for s in sess.get_outputs()], sess.run(None, {"images": x})))
            np.savez(f"{OUT}/{v}-ref{i}.npz", **o)
            if i == 0:
                f0, f1 = orig.run(None, {"images": x}); cl = f0[0, 4:4 + NC]
                print(f"  {v}: reduced vs unmodified ONNX (photo 0): boxes {np.abs(o['boxes'][0] - f0[0, :4]).max():.1e}, "
                      f"score {np.abs(o['score'][0] - cl.max(0)).max():.1e}, cls same {np.array_equal(o['cls'][0], cl.argmax(0))}, "
                      f"coef {np.abs(o['coef'][0] - f0[0, 4 + NC:]).max():.1e}, protos {np.abs(o['output1'] - f1).max():.1e}", flush=True)
            r = pt.predict(im, imgsz=640, verbose=False)[0]
            tm = r.masks.data.numpy() > 0.5 if r.masks is not None else np.zeros((0, 640, 640), bool)
            np.savez(f"{OUT}/{v}-task{i}.npz", xyxy=r.boxes.xyxy.numpy(), conf=r.boxes.conf.numpy(), cls=r.boxes.cls.numpy(),
                     masks=np.packbits(tm, axis=-1))
            det, m = detections(o["boxes"], o["score"], o["cls"], o["coef"], o["output1"])
            ok = (len(det) == len(r.boxes) and np.array_equal(det[:, 5], r.boxes.cls.numpy())
                  and np.abs(det[:, :4] - r.boxes.xyxy.numpy()).max(initial=0) < 0.01 and np.abs(det[:, 4] - r.boxes.conf.numpy()).max(initial=0) < 1e-4
                  and (m == tm).mean() > 0.99999)
            same += ok
            if not ok:
                print(f"  {v} photo {i}: evaluator {len(det)} dets vs Ultralytics {len(r.boxes)}", flush=True)
        print(f"{v}: evaluator reproduces Ultralytics' .pt predictions on {same}/8 photos "
              f"(same detections and classes, boxes < 0.01 px, scores < 1e-4, masks > 99.999% equal)", flush=True)
