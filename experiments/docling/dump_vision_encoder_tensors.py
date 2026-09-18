#!/usr/bin/env python3
"""Dumps the exact pixel_values/pixel_attention_mask inputs (from the real
HF processor, same settings as compare_vision_encoder.py) and the ONNX
CPU reference output as raw binary files, so an on-device C canary can
feed identical, deterministic tensors without reimplementing Idefics3's
image processor (resize/tiling/splitting) in C.
"""
import sys

import numpy as np
import onnxruntime as ort
import torch
from PIL import Image
from transformers import AutoProcessor


def main() -> int:
    if len(sys.argv) != 5:
        print(f"usage: {sys.argv[0]} <image.png> <hf_checkpoint_dir> <onnx_vision_encoder_path> <out_dir>", file=sys.stderr)
        return 1
    image_path, hf_dir, onnx_path, out_dir = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]

    import os
    os.makedirs(out_dir, exist_ok=True)

    image = Image.open(image_path).convert("RGB")
    processor = AutoProcessor.from_pretrained(hf_dir)
    messages = [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": "Convert this page to docling."}]}]
    prompt = processor.apply_chat_template(messages, add_generation_prompt=True)
    inputs = processor(text=prompt, images=[image], return_tensors="pt")

    pixel_values = inputs["pixel_values"].numpy().astype(np.float32)
    pixel_attention_mask = inputs["pixel_attention_mask"].numpy().astype(np.bool_)

    print("pixel_values shape:", pixel_values.shape, pixel_values.dtype)
    print("pixel_attention_mask shape:", pixel_attention_mask.shape, pixel_attention_mask.dtype)

    pixel_values.tofile(f"{out_dir}/pixel_values.f32.bin")
    pixel_attention_mask.tofile(f"{out_dir}/pixel_attention_mask.bool.bin")
    with open(f"{out_dir}/shapes.txt", "w") as f:
        f.write(f"pixel_values {' '.join(map(str, pixel_values.shape))}\n")
        f.write(f"pixel_attention_mask {' '.join(map(str, pixel_attention_mask.shape))}\n")

    session = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
    onnx_features = session.run(None, {
        "pixel_values": pixel_values,
        "pixel_attention_mask": pixel_attention_mask,
    })[0]
    print("reference (CPU) output shape:", onnx_features.shape, onnx_features.dtype)
    onnx_features.astype(np.float32).tofile(f"{out_dir}/reference_output_cpu.f32.bin")
    with open(f"{out_dir}/shapes.txt", "a") as f:
        f.write(f"reference_output_cpu {' '.join(map(str, onnx_features.shape))}\n")

    print(f"wrote tensors to {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
