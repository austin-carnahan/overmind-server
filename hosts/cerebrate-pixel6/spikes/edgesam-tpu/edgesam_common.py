"""Shared pieces for the EdgeSAM TPU spike: the original model (EdgeSAM-3x,
bicubic upsampling as trained), the lane's eight photos, YOLOE-v8s's 132
detections as box prompts, and the task-level score (embeddings decoded by
the original prompt encoder + mask decoder, masks compared with the
original model's)."""
import sys, types, glob
import numpy as np, cv2, torch

BP = "/Users/dev/Code/browser-perception/demos"
PHOTOS = sorted(glob.glob(f"{BP}/object-selection/samples/*.jpg"))[:5] + sorted(glob.glob(f"{BP}/segmentation/samples/*.jpg"))[:3]


def load_edgesam(dl_dir, upsample_mode="bicubic"):
    """edge_sam.modeling.sam imports mmdet/mmengine at module level for
    training-only detection heads the predictor never builds; stub them."""
    stubs = {"mmdet": {}, "mmdet.models": {}, "mmdet.models.dense_heads": {"RPNHead": object, "CenterNetUpdateHead": object},
             "mmdet.models.necks": {"FPN": object}, "projects": {}, "projects.EfficientDet": {"efficientdet": None},
             "mmengine": {"ConfigDict": dict}}
    for name, attrs in stubs.items():
        if name not in sys.modules:
            mod = types.ModuleType(name); mod.__dict__.update(attrs); sys.modules[name] = mod
    if f"{dl_dir}/src" not in sys.path:
        sys.path.insert(0, f"{dl_dir}/src")
    from edge_sam import sam_model_registry, SamPredictor
    # The repo's loader uses torch.load without map_location (the checkpoint
    # holds CUDA tensors) and strict=False; load here and require every
    # weight of the parts the predictor uses.
    sam = sam_model_registry["edge_sam"](checkpoint=None, upsample_mode=upsample_mode)
    sd = torch.load(f"{dl_dir}/edge_sam_3x.pth", map_location="cpu", weights_only=True)
    res = sam.load_state_dict(sd, strict=False)
    used = ("image_encoder.", "prompt_encoder.", "mask_decoder.")
    missing = [k for k in res.missing_keys if k.startswith(used)]
    assert not missing, f"checkpoint lacks {missing[:5]}"
    if res.unexpected_keys:
        print(f"(checkpoint keys not in the model, ignored: {len(res.unexpected_keys)})")
    return sam.eval(), SamPredictor(sam.eval())


def yoloe_boxes(yoloe_dir, i, shape):
    """YOLOE-v8s's detections for photo i (Ultralytics predictions on the
    640x640 letterbox), mapped back to original-photo xyxy."""
    h, w = shape
    r = min(640 / h, 640 / w)
    left = int(round((640 - round(w * r)) / 2 - 0.1)); top = int(round((640 - round(h * r)) / 2 - 0.1))
    b = np.load(f"{yoloe_dir}/yoloe-v8s-seg-pf-task{i}.npz")["xyxy"].astype(np.float64)
    b[:, [0, 2]] = (b[:, [0, 2]] - left) / r; b[:, [1, 3]] = (b[:, [1, 3]] - top) / r
    b[:, [0, 2]] = b[:, [0, 2]].clip(0, w); b[:, [1, 3]] = b[:, [1, 3]].clip(0, h)
    return b.astype(np.float32)


def encoder_input(predictor, rgb):
    """The exact encoder input the predictor builds (resize longest side to
    1024, normalize, pad): [1,3,1024,1024]."""
    t = torch.as_tensor(predictor.transform.apply_image(rgb)).permute(2, 0, 1).contiguous()[None]
    return predictor.model.preprocess(t), tuple(t.shape[-2:])


@torch.no_grad()
def decode(predictor, emb, boxes, original_size, input_size):
    """Box-prompted masks (as the official demo: one mask per box, no
    stability score) from given embeddings [1,256,64,64]."""
    predictor.original_size, predictor.input_size, predictor.is_image_set = original_size, input_size, True
    feats = torch.as_tensor(np.ascontiguousarray(emb), dtype=torch.float32)
    out = [predictor.predict(features=feats, box=b, num_multimask_outputs=1) for b in boxes]
    return np.stack([m[0] for m, _, _ in out]), np.array([s[0] for _, s, _ in out])


def mask_stats(masks, ref):
    """Per-box mask IoU and flipped pixels vs the reference masks."""
    inter = (masks & ref).sum((1, 2)); union = (masks | ref).sum((1, 2))
    iou = np.where(union > 0, inter / np.maximum(union, 1), 1.0)
    return iou, (masks ^ ref).sum((1, 2))


def summarize(name, ious, flips, areas):
    ious, flips, areas = map(np.concatenate, (ious, flips, areas))
    rel = flips / np.maximum(areas, 1)
    print(f"{name}: {len(ious)} masks | IoU worst {ious.min():.4f}, mean {ious.mean():.5f}, "
          f"<0.95: {(ious < 0.95).sum()}, <0.90: {(ious < 0.9).sum()} | flipped px total {int(flips.sum())}, "
          f"worst {rel.max() * 100:.2f}% of mask area", flush=True)
    return ious
