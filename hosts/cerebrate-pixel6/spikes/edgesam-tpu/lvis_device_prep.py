"""Device inputs for EdgeSAM's fast pipeline on the LVIS selection set, in
batches of photos: per batch, the TPU stage's image list, the GPU neck's
list (the TPU outputs), and the decoder's list (the neck outputs + each
box's corner tokens from the original prompt encoder + the constant inputs
from edgesam_decoder.py). index.json maps decoder samples to objects.
usage: lvis_device_prep.py <dl-edgesam dir> <lvis dir (lvis_compare.py output)> <batch size>"""
import sys, os, json, glob
import numpy as np, torch
from edgesam_common import load_edgesam
D, L, BS = sys.argv[1], sys.argv[2], int(sys.argv[3])
DEV = "/data/local/tmp/edgesam/lvis"; DEC = "/data/local/tmp/edgesam/dec/inputs"
sam, pred = load_edgesam(D, "bicubic")
rows = json.load(open(f"{L}/lvis_rows.json"))
n_img = len(glob.glob(f"{L}/edgesam_in_*.npz"))
index = []
for b0 in range(0, n_img, BS):
    b = b0 // BS; bd = f"{L}/dev/b{b}"; os.makedirs(bd, exist_ok=True)
    t1, n1, dec = [], [], []
    for s, n in enumerate(range(b0, min(b0 + BS, n_img))):
        z = np.load(f"{L}/edgesam_in_{n}.npz")
        z["image_nhwc"].astype(np.float32).tofile(f"{bd}/in{n}.bin")
        t1.append(f"{DEV}/b{b}/in{n}.bin"); n1.append(f"{DEV}/b{b}/t1out/{s}_o0.bin")
        for k, box in enumerate(z["boxes"]):
            with torch.no_grad():
                bx = torch.as_tensor(pred.transform.apply_boxes(box, tuple(z["original_size"])), dtype=torch.float)[None]
                sparse, _ = sam.prompt_encoder(points=None, boxes=bx, masks=None)
            sparse.numpy().astype(np.float32).tofile(f"{bd}/sparse{n}_{k}.bin")
            dec.append(",".join([f"{DEV}/b{b}/n1out/{s}_o0.bin", f"{DEV}/b{b}/sparse{n}_{k}.bin", f"{DEC}/dense.bin", f"{DEC}/image_pe.bin", f"{DEC}/output_tokens.bin"]))
            index.append(dict(batch=b, sample=len(dec) - 1, image=n, box=k))
    for name, lines in (("t1_inputs.txt", t1), ("n1_inputs.txt", n1), ("dec_inputs.txt", dec)):
        open(f"{bd}/{name}", "w").write("\n".join(lines) + "\n")
json.dump(index, open(f"{L}/dev/index.json", "w"))
print(f"{n_img} photos in {(n_img + BS - 1) // BS} batches, {len(index)} boxes")
