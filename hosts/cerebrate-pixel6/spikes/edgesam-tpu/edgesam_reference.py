"""EdgeSAM-3x reference (step 1): the original model (bicubic upsampling, as
trained) on the eight lane photos with YOLOE-v8s's 132 detections as box
prompts. Writes encoder inputs (NCHW for ONNX, NHWC for TFLite), reference
embeddings and masks. Also checks the authors' ONNX encoder, which they
export with *bilinear* upsampling (scripts/export_onnx_model.py): against
the PyTorch model built the same way (export fidelity), and against the
original at task level (what the bilinear swap costs).
usage: edgesam_reference.py <dl-edgesam dir> <yoloe dir> <out dir>"""
import sys
import numpy as np, cv2, torch, onnxruntime as ort
from edgesam_common import PHOTOS, load_edgesam, yoloe_boxes, encoder_input, decode, mask_stats, summarize
D, Y, OUT = sys.argv[1:4]
sam, pred = load_edgesam(D, "bicubic")
sam_bl, _ = load_edgesam(D, "bilinear")
onnx_enc = ort.InferenceSession(f"{D}/edge_sam_3x_encoder.onnx")
acc = {k: ([], [], []) for k in ("bilinear (authors' export setting)",)}
n = 0
for i, p in enumerate(PHOTOS):
    rgb = cv2.cvtColor(cv2.imread(p), cv2.COLOR_BGR2RGB)
    x, input_size = encoder_input(pred, rgb)
    boxes = yoloe_boxes(Y, i, rgb.shape[:2]); n += len(boxes)
    with torch.no_grad():
        emb = sam.image_encoder(x).numpy(); emb_bl = sam_bl.image_encoder(x).numpy()
    emb_onnx = onnx_enc.run(None, {"image": x.numpy()})[0]
    masks, scores = decode(pred, emb, boxes, rgb.shape[:2], input_size)
    np.savez(f"{OUT}/in{i}.npz", image=x.numpy())
    np.savez(f"{OUT}/in{i}_nhwc.npz", image=np.ascontiguousarray(x.numpy().transpose(0, 2, 3, 1)))
    np.savez(f"{OUT}/ref{i}.npz", emb=emb, boxes=boxes, scores=scores, masks=np.packbits(masks, axis=-1),
             mask_shape=np.array(masks.shape), original_size=np.array(rgb.shape[:2]), input_size=np.array(input_size))
    m_bl, _ = decode(pred, emb_bl, boxes, rgb.shape[:2], input_size)
    iou, fl = mask_stats(m_bl, masks)
    for lst, v in zip(acc["bilinear (authors' export setting)"], (iou, fl, masks.sum((1, 2)))): lst.append(v)
    cos = lambda a, b: float((a * b).sum() / np.linalg.norm(a) / np.linalg.norm(b))
    print(f"photo {i}: {len(boxes)} boxes, input {input_size} | ONNX vs PyTorch-bilinear max |diff| {np.abs(emb_onnx - emb_bl).max():.1e} | "
          f"bilinear vs bicubic emb cosine {cos(emb_bl, emb):.6f}, max |diff| {np.abs(emb_bl - emb).max():.3f}", flush=True)
print(f"{n} box prompts")
for k, v in acc.items(): summarize(k, *v)
