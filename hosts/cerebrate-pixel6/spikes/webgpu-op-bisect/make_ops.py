"""Single-op fp32 test graphs (+ inputs and ORT CPU references) for bisecting the
Pixel WebGPU hang. Shapes are sized like DINOv2-small / SAM tensors."""
import sys
import numpy as np, onnx, onnxruntime as ort
from onnx import TensorProto as T, helper as h, numpy_helper as nh
OUT = sys.argv[1]; rng = np.random.default_rng(0)
def f32(*s): return rng.standard_normal(s).astype(np.float32)
def build(name, nodes, inputs, inits=()):
    outs = [h.make_tensor_value_info("y", T.FLOAT, None)]
    ins = [h.make_tensor_value_info(k, T.FLOAT, list(v.shape)) for k, v in inputs.items()]
    g = h.make_graph(nodes, name, ins, outs, initializer=[nh.from_array(v, k) for k, v in inits])
    m = h.make_model(g, opset_imports=[h.make_opsetid("", 17)]); m.ir_version = 8
    onnx.save(m, f"{OUT}/op-{name}.onnx")
    ref = ort.InferenceSession(f"{OUT}/op-{name}.onnx", providers=["CPUExecutionProvider"]).run(None, inputs)[0]
    np.savez(f"{OUT}/op-{name}_in.npz", **inputs); np.savez(f"{OUT}/op-{name}_ref.npz", y=ref)
    print(name, {k: v.shape for k, v in inputs.items()}, "->", ref.shape)
build("mul-small", [h.make_node("Mul", ["x", "w"], ["y"])], {"x": f32(1, 384)}, [("w", f32(384))])
build("mul-large", [h.make_node("Mul", ["x", "w"], ["y"])], {"x": f32(1, 32, 256, 256)}, [("w", f32(256))])
build("add-bcast", [h.make_node("Add", ["x", "w"], ["y"])], {"x": f32(1, 257, 384)}, [("w", f32(384))])
build("matmul", [h.make_node("MatMul", ["x", "w"], ["y"])], {"x": f32(1, 257, 384)}, [("w", f32(384, 384))])
build("matmul-large", [h.make_node("MatMul", ["x", "w"], ["y"])], {"x": f32(1, 4096, 256)}, [("w", f32(256, 256))])
build("matmul-batched", [h.make_node("MatMul", ["x", "z"], ["y"])], {"x": f32(1, 6, 257, 64), "z": f32(1, 6, 64, 257)})
build("softmax", [h.make_node("Softmax", ["x"], ["y"], axis=-1)], {"x": f32(1, 6, 257, 257)})
build("layernorm", [h.make_node("LayerNormalization", ["x", "g", "b"], ["y"], axis=-1)], {"x": f32(1, 257, 384)}, [("g", f32(384)), ("b", f32(384))])
build("erf", [h.make_node("Erf", ["x"], ["y"])], {"x": f32(1, 257, 1536)})
build("reducemean", [h.make_node("ReduceMean", ["x"], ["y"], axes=[-1])], {"x": f32(1, 257, 384)})
build("transpose", [h.make_node("Transpose", ["x"], ["y"], perm=[0, 2, 1, 3])], {"x": f32(1, 6, 257, 64)})
build("conv3x3", [h.make_node("Conv", ["x", "w"], ["y"], pads=[1, 1, 1, 1])], {"x": f32(1, 64, 64, 64)}, [("w", f32(64, 64, 3, 3))])
build("conv-patch", [h.make_node("Conv", ["x", "w"], ["y"], strides=[14, 14])], {"x": f32(1, 3, 224, 224)}, [("w", f32(384, 3, 14, 14))])
