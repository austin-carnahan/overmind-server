#!/usr/bin/env python3
"""Compares the ONNX vision_encoder.onnx from onnx-community/granite-docling-258M-ONNX
against the HF transformers reference (ibm-granite/granite-docling-258M,
Idefics3ForConditionalGeneration.model.get_image_features(...).pooler_output),
on the exact same image and exact same processor/resize/splitting settings.

Correctness is judged on the intermediate image-feature tensor, not on
generated DocTags text -- the same discipline used for every other
correctness check in this project (don't trust successful execution;
compare actual output values).
"""
import sys

import numpy as np
import onnxruntime as ort
import torch
from PIL import Image
from transformers import AutoModelForImageTextToText, AutoProcessor


def main() -> int:
    if len(sys.argv) != 4:
        print(f"usage: {sys.argv[0]} <image.png> <hf_checkpoint_dir> <onnx_vision_encoder_path>", file=sys.stderr)
        return 1
    image_path, hf_dir, onnx_path = sys.argv[1], sys.argv[2], sys.argv[3]

    image = Image.open(image_path).convert("RGB")

    print("loading HF processor + model...")
    processor = AutoProcessor.from_pretrained(hf_dir)
    model = AutoModelForImageTextToText.from_pretrained(hf_dir, torch_dtype=torch.float32)
    model.eval()

    # Build a minimal conversation so the processor applies the same
    # image splitting/resizing it would for a real request.
    messages = [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": "Convert this page to docling."}]}]
    prompt = processor.apply_chat_template(messages, add_generation_prompt=True)
    inputs = processor(text=prompt, images=[image], return_tensors="pt")

    print("pixel_values shape:", tuple(inputs["pixel_values"].shape))
    if "pixel_attention_mask" in inputs:
        print("pixel_attention_mask shape:", tuple(inputs["pixel_attention_mask"].shape))

    with torch.no_grad():
        hf_out = model.model.get_image_features(
            pixel_values=inputs["pixel_values"],
            pixel_attention_mask=inputs.get("pixel_attention_mask"),
        )
    hf_features = hf_out.pooler_output if hasattr(hf_out, "pooler_output") else hf_out
    hf_features = hf_features.numpy()
    print("HF image_hidden_states shape:", hf_features.shape)

    print("loading ONNX vision encoder (CPU EP)...")
    session = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
    for inp in session.get_inputs():
        print("  onnx input:", inp.name, inp.shape, inp.type)
    for out in session.get_outputs():
        print("  onnx output:", out.name, out.shape, out.type)

    onnx_inputs = {"pixel_values": inputs["pixel_values"].numpy().astype(np.float32)}
    if "pixel_attention_mask" in inputs:
        onnx_inputs["pixel_attention_mask"] = inputs["pixel_attention_mask"].numpy().astype(np.bool_)

    onnx_features = session.run(None, onnx_inputs)[0]
    print("ONNX image_features shape:", onnx_features.shape)

    if hf_features.shape != onnx_features.shape:
        print(f"SHAPE MISMATCH: HF={hf_features.shape} ONNX={onnx_features.shape}")
        # Try to reshape for comparison anyway if element counts match.
        if hf_features.size != onnx_features.size:
            print("FAIL: element counts differ too, cannot compare")
            return 1
        onnx_features = onnx_features.reshape(hf_features.shape)

    a = hf_features.astype(np.float64).flatten()
    b = onnx_features.astype(np.float64).flatten()
    diff = np.abs(a - b)
    max_abs_err = float(diff.max())
    mean_abs_err = float(diff.mean())
    denom = np.maximum(np.abs(a), 1e-8)
    rel_err = float((diff / denom).mean())
    cos_sim = float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))

    print()
    print(f"max_abs_error:  {max_abs_err:.6e}")
    print(f"mean_abs_error: {mean_abs_err:.6e}")
    print(f"mean_rel_error: {rel_err:.6e}")
    print(f"cosine_sim:     {cos_sim:.8f}")
    verdict = "PASS" if max_abs_err < 0.05 and cos_sim > 0.999 else "FAIL"
    print(f"verdict: {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
