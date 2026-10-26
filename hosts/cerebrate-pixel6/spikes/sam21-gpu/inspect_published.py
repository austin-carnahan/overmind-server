"""Inputs for evaluating litert-community's published SAM 2.1 fp16 models
against the unmodified PyTorch model: I/O inspection, host-side box prompt
encoding with the original fp32 prompt encoder, and a desktop LiteRT CPU
sanity run of the published decoder on the original embeddings."""
import sys
import numpy as np
import torch
from ai_edge_litert.interpreter import Interpreter
from transformers import Sam2Model

P, SAMDEC, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
for name in ("enc_sam2_tiny_image_encoder_v2_fp16.tflite", "dec_sam2_tiny_mask_decoder_v2_fp16.tflite"):
    it = Interpreter(model_path=f"{P}/{name}")
    print(name)
    for d in it.get_input_details(): print("   in ", d["index"], d["name"], d["shape"], d["dtype"].__name__)
    for d in it.get_output_details(): print("   out", d["index"], d["name"], d["shape"], d["dtype"].__name__)
    sig = it.get_signature_list(); print("   signatures", sig)

m = Sam2Model.from_pretrained("facebook/sam2.1-hiera-tiny", revision="de431c4043854a71d8101e17995dfe596bf101a5").eval()
boxes = [[0.25, 0.35, 0.75, 0.95], [0.05, 0.05, 0.55, 0.60]]
ref_masks = np.load(f"{SAMDEC}/ref_masks.npy")
dec = Interpreter(model_path=f"{P}/dec_sam2_tiny_mask_decoder_v2_fp16.tflite"); dec.allocate_tensors()
lines, ious = [], []
for i in range(4):
    emb = [np.fromfile(f"{SAMDEC}/inputs/img{i}_emb{k}.bin", np.float32).reshape(s) for k, s in
           enumerate(((1, 32, 256, 256), (1, 64, 128, 128), (1, 256, 64, 64)))]
    for j, b in enumerate(boxes):
        box = torch.from_numpy((np.array(b, np.float32) * 1024).reshape(1, 1, 4))
        with torch.no_grad():
            sparse, dense = m.prompt_encoder(input_points=None, input_labels=None, input_boxes=box, input_masks=None)
        if i == 0 and j == 0: print("box -> sparse prompt shape", tuple(sparse.shape), "dense", tuple(dense.shape))
        sp = sparse.numpy().reshape(1, -1, 256).astype(np.float32)
        sp.tofile(f"{OUT}/inputs/img{i}_box{j}_sparse.bin")
        feed = {(1, 256, 64, 64): emb[2], (1, 64, 128, 128): emb[1], (1, 32, 256, 256): emb[0], tuple(sp.shape): sp}
        for d in dec.get_input_details(): dec.set_tensor(d["index"], feed[tuple(d["shape"])])
        dec.invoke()
        o = {len(d["shape"]): dec.get_tensor(d["index"]) for d in dec.get_output_details()}
        got, ref = o[4][0], ref_masks[i * 2 + j]
        ious.append(min(((got[k] > 0) & (ref[k] > 0)).sum() / max(1, ((got[k] > 0) | (ref[k] > 0)).sum()) for k in range(3)))
        order = sorted(dec.get_input_details(), key=lambda d: d["index"])
        lines.append(",".join(f"/data/local/tmp/pubsam/img{i}_" + {(1, 256, 64, 64): "emb2", (1, 64, 128, 128): "emb1", (1, 32, 256, 256): "emb0"}.get(tuple(d["shape"]), f"box{j}_sparse") + ".bin" for d in order))
print("published decoder on desktop LiteRT CPU, original embeddings: worst-mask IoU per sample", np.round(ious, 4))
open(f"{OUT}/dec_inputs.txt", "w").write("\n".join(lines) + "\n")
print(lines[0])
