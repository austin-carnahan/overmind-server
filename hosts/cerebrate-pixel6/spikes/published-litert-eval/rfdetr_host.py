"""Host step between published RF-DETR-Seg-Nano graphs A and B, verbatim from
litert-community/RF-DETR-Seg-Nano-LiteRT's model card (revision 8fee237c),
plus the task-level comparison used to judge outputs against the original."""
import numpy as np
R, NP_, NQ, NC, H, M, G = 312, 676, 100, 91, 256, 78, 26

def host_step(enc_cls, delta, mem2, rp):
    """enc_cls [676,91], delta [676,4], mem2 = graph A's memory*2 [676,256], rp refpoint_embed [100,4]
    -> (memory [1,676,256], refpoint [1,100,4]) for graph B."""
    mem = mem2 * 0.5
    gy, gx = np.mgrid[0:G, 0:G]
    prop = np.stack([(gx + .5) / G, (gy + .5) / G], -1).reshape(NP_, 2)
    cxcy = delta[:, :2] * 0.05 + prop
    wh = np.exp(delta[:, 2:]) * 0.05
    top = np.argsort(-enc_cls.max(-1))[:NQ]
    ts = np.concatenate([cxcy, wh], -1)[top]
    ref = np.concatenate([rp[:, :2] * ts[:, 2:] + ts[:, :2], np.exp(rp[:, 2:]) * ts[:, 2:]], -1)
    return mem.reshape(1, NP_, H).astype(np.float32), ref.reshape(1, NQ, 4).astype(np.float32)

def detections(logits, boxes, masks, thr=0.5):
    score = 1 / (1 + np.exp(-logits.max(-1))); cls = logits.argmax(-1)
    keep = np.where((score > thr) & (cls > 0))[0]
    return [(int(cls[q]), float(score[q]), boxes[q], masks[q] > 0) for q in keep]

def xyxy(b):
    cx, cy, w, h = b; return np.array([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2])

def box_iou(a, b):
    a, b = xyxy(a), xyxy(b)
    iw = max(0, min(a[2], b[2]) - max(a[0], b[0])); ih = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = iw * ih; u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / u if u > 0 else 0.0

def compare(ref_dets, got_dets):
    """Greedy one-to-one matching by box IoU (>= 0.5). Returns counts and agreement stats."""
    used, matched, same_cls, biou, miou, sdiff = set(), 0, 0, [], [], []
    for rc, rs, rb, rm in sorted(ref_dets, key=lambda d: -d[1]):
        best, bj = 0.5, None
        for j, (gc, gs, gb, gm) in enumerate(got_dets):
            if j in used: continue
            iou = box_iou(rb, gb)
            if iou >= best: best, bj = iou, j
        if bj is None: continue
        used.add(bj); matched += 1
        gc, gs, gb, gm = got_dets[bj]
        same_cls += int(gc == rc); biou.append(best); sdiff.append(abs(gs - rs))
        u = (rm | gm).sum(); miou.append((rm & gm).sum() / u if u else 1.0)
    return dict(ref=len(ref_dets), got=len(got_dets), matched=matched, same_cls=same_cls,
                box_iou_min=min(biou) if biou else None, mask_iou_min=min(miou) if miou else None,
                mask_iou_mean=float(np.mean(miou)) if miou else None, score_maxdiff=max(sdiff) if sdiff else None)
