# g1-gpu-repros

Minimal reproductions of two **silent miscomputations** on the Pixel 6
(Tensor G1) GPU with LiteRT 2.3.0: the graph delegates fully, runs, and
returns wrong values, with no error or warning. Both were found in
EfficientSAM3's grounding graph
([efficientsam3-gpu](../efficientsam3-gpu/README.md)) and are the kind of
issue an operator-support matrix doesn't capture. Kept for possible upstream
reports (LiteRT GPU / ML Drift, and the
[edge-compat](https://github.com/john-rocky/edge-compat) record, which has no
Mali-G78 coverage).

## Environment

| | |
| --- | --- |
| Device | Pixel 6 (`oriole`), Tensor G1, Mali-G78, driver `v1.r54p3-01eac0` |
| OS | Android 17, `google/oriole/oriole:17/CP3A.260905.009/16091614:user/release-keys` |
| Runtime | LiteRT 2.3.0 `CompiledModel` (`litert` + `litert-gpu` AARs, `libLiteRtClGlAccelerator.so`, OpenCL), GPU accelerator at fp32 precision |
| Converter | `litert-torch` 0.10.0, torch 2.14.1 (macOS arm64) |
| Harness | `litert-e2e` from [litert-gpu-transformers](../litert-gpu-transformers/README.md): requirement-based buffers, synchronized output lock |

## Results (2026-10-24)

[`g1_repros.py`](g1_repros.py) `<out dir>` builds each model with random
inputs and a numpy-equivalent PyTorch reference. Relative L2 error against
that reference, same inputs, run on the device:

| Case | Graph | CPU (XNNPACK) | GPU | |
| --- | --- | --- | --- | --- |
| **B_bmm4d** | `BATCH_MATMUL` lhs `[6,1,200,256]` × rhs `[256,1]` (one op) | 3.1e-7 | **1.2** | **wrong** |
| B_bmm4d_b1 | same values at batch 1: `[1,1,1200,256]` × `[256,1]` | 2.9e-7 | 2.9e-7 | correct |
| B_layers | Linear over `[6,1,200,256]` → matmul with `[256,1]` → `[6,1,200,1]` × s → last slice (EfficientSAM3's scoring; the converter fuses it into `BATCH_MATMUL` `[6,1,200,256]`×`[256,1]`) | 2.9e-7 | **1.2** | **wrong** |
| B_matmul / B_slice / B_batch1 | `[1200,256]`×`[256,1]` (2-D) then reshape into `[6,1,200,1]` (± slice), or batch 1 | ~3e-7 | ~3e-7 | correct |
| B_fc_only / B_fc_reshape / B_input | Linear over the batch-6 tensor alone; reshape alone | ≤ 3e-7 | ≤ 2e-7 | correct |
| **A_mha_const** | attention block, 15 ops: q = k = T + pos, v = T, with T a constant `[201,1,256]` (pos a runtime input); the converter folds v's projection into a constant `[8,201,32]` consumed by `BATCH_MATMUL` | 5.0e-7 | **0.87** | **wrong** |
| A_mha_input | the same block with T supplied as an input | 3.3e-7 | 3.6e-7 | correct |
| A_bmm_const / A_softmax_const | `BATCH_MATMUL` with a constant `[8,201,32]` operand, alone or after `SOFTMAX` | ≤ 1.4e-7 | ≤ 2.1e-7 | correct |

**B — batch-broadcast `BATCH_MATMUL`.** A 4-D left operand with batch 6 times
a 2-D right operand (broadcast over the batch) is wrong as a single op; the
same arithmetic at batch 1 is right. Note that a 2-D rewrite
(`reshape → matmul → reshape`) doesn't avoid it: the converter fuses it back
into the 4-D form. Workaround used: keep batch 1 (EfficientSAM3 needed only
the last of six decoder layers' scores).

**A — constant operand inside an attention block.** Not reproducible with
the `BATCH_MATMUL`-with-constant op alone, nor with softmax → matmul; it needs
the surrounding chain (projections, reshapes, transposes). In EfficientSAM3
the constant came from a model weight used as an activation (decoder layer
0's learned query embeddings), which the converter folded into the attention
values. Workaround used: supply such tensors as model inputs, so no op
computes on constants alone.

Both workarounds are exact and are recorded as preparation rules (lane plan,
Section 4.5, rules 3 and 5).
