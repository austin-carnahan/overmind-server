"""photo_preprocess against the references: (1) on the lane photos,
uint8 + the worker's normalization reproduces the fp32 inputs the models were
validated with (YOLOE in*.npz, EdgeSAM in*_nhwc.npz) bit for bit, and
sam_resize equals SAM's own ResizeLongestSide.apply_image (when torchvision
is importable); (2) for any images, prints hashes of the decoded image and
both models' uint8 inputs, to compare machines (Mac reference vs guest).
usage: photo_preprocess_check.py <yoloe ref dir|-> <edgesam ref dir|-> <image ...>"""
import sys, hashlib
import numpy as np
import os
# photo_preprocess lives with the shared MLServer adapter
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../mlserver/models/cerebrate-graph"))
import photo_preprocess as pp
YR, ER, files = sys.argv[1], sys.argv[2], sys.argv[3:]
h = lambda a: hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()[:16]
try:
    from torchvision.transforms.functional import resize, to_pil_image
    def sam_ref(rgb):
        nh, nw = pp.sam_shape(*rgb.shape[:2]); return np.array(resize(to_pil_image(rgb), (nh, nw)))
except ImportError:
    sam_ref = None
for i, f in enumerate(files):
    bgr = pp.decode(open(f, "rb").read())
    y8, lb = pp.yoloe_letterbox(bgr); s8, ext = pp.sam_resize(bgr)
    line = f"{f.split('/')[-1][:34]:34s} {bgr.shape[1]}x{bgr.shape[0]} decode {h(bgr)} yoloe {h(y8)} sam {h(s8)}"
    if YR != "-" and i < 8:
        line += f" | fp32 yoloe exact {np.array_equal(pp.normalize_yoloe(y8), np.load(f'{YR}/in{i}.npz')['images'].transpose(0, 2, 3, 1))}"
    if ER != "-" and i < 8:
        line += f", fp32 edgesam exact {np.array_equal(pp.normalize_sam(s8, ext), np.load(f'{ER}/in{i}_nhwc.npz')['image'])}"
    if sam_ref is not None:
        line += f", = SAM resize {np.array_equal(s8[:ext[0], :ext[1]], sam_ref(np.ascontiguousarray(bgr[..., ::-1])))}"
    print(line, flush=True)
