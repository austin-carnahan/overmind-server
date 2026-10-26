"""MobileNet health probe through MLServer (cerebrate-infer endpoint), since
2026-10-25 the standard Pixel health probe: the worker runs on demand, so
probing its raw port no longer works. Sends the project's deterministic
i%256 input as a 224x224 PNG (lossless, already the model's size, so the
adapter's resize is a copy) and expects class 795, as every probe before it.
usage: mobilenet_probe.py <grpc host:port> [count] [model]   (exit 0 = all 795)"""
import base64
import io
import sys
import time

import grpc
from mlserver.grpc import dataplane_pb2 as pb, dataplane_pb2_grpc as pbg
from PIL import Image


def probe_png() -> bytes:
    img = Image.frombytes("RGB", (224, 224), bytes(i % 256 for i in range(224 * 224 * 3)))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def classify(stub, png_b64: bytes, model="cerebrate-infer"):
    req = pb.ModelInferRequest(model_name=model)
    req.inputs.add(name="image", datatype="BYTES", shape=[1])
    req.raw_input_contents.append(len(png_b64).to_bytes(4, "little") + png_b64)
    t = time.perf_counter()
    r = stub.ModelInfer(req, timeout=60)
    ms = (time.perf_counter() - t) * 1000
    out = {o.name: b for o, b in zip(r.outputs, r.raw_output_contents)}
    return int.from_bytes(out["top_class"][:8], "little"), ms


if __name__ == "__main__":
    target = sys.argv[1]
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    model = sys.argv[3] if len(sys.argv) > 3 else "cerebrate-infer"
    stub = pbg.GRPCInferenceServiceStub(grpc.insecure_channel(target))
    png = base64.b64encode(probe_png())
    results = [classify(stub, png, model) for _ in range(count)]
    for cls, ms in results:
        print(f"top_class={cls} round_trip_ms={ms:.1f}")
    ok = all(cls == 795 for cls, _ in results)
    print("PASS" if ok else "FAIL", f"{sum(cls == 795 for cls, _ in results)}/{count} class 795")
    sys.exit(0 if ok else 1)
