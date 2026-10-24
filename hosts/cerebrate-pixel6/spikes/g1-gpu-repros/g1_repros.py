"""Minimal reproductions of the two silent Mali-G78 miscomputations found in
EfficientSAM3's grounding graph (LiteRT 2.3.0 GPU, OpenCL). Each model is
converted with litert-torch 0.10.0 and paired with random inputs and a numpy
reference, for comparison of GPU and CPU outputs on the device.

A -- a constant operand of BATCH_MATMUL: runtime attention weights
     [8,201,201] times a constant [8,201,32]. In the model the constant was
     layer 0's attention values, which the converter folded from the
     learned 200x256 query embeddings (a weight used as an activation).
     Control: the same tensor supplied as an input (the fix). Also as a whole
     attention block (q = k = constant + runtime position, v = constant).
B -- a batch-broadcast BATCH_MATMUL: lhs [6,1,200,256] (batch 6) x rhs
     [256,1]. The converter fuses reshape -> 2-D matmul -> reshape back into
     this op, so a 2-D rewrite alone does not avoid it. Earlier variants
     kept for the record: reshape into [6, 1, 200, 1], scaled. Variants: from an input, from a matmul (as in
     the model), with the last batch slice taken (what the model output),
     and batch 1 ([1, 1, 1200, 1]) as the control.
usage: <out dir>"""
import sys
import numpy as np, torch
import litert_torch
OUT = sys.argv[1]; torch.manual_seed(0); rng = np.random.default_rng(0)
cases = {}

class AConst(torch.nn.Module):       # runtime [8,201,201] @ constant [8,201,32] (as in the model)
    def __init__(s): super().__init__(); s.v = torch.nn.Parameter(torch.randn(8, 201, 32), requires_grad=False)
    def forward(s, p): return torch.bmm(p, s.v)
class AInput(torch.nn.Module):       # the same with the constant supplied as an input (the fix)
    def forward(s, p, v): return torch.bmm(p, v)
ac = AConst().eval(); pw = torch.softmax(torch.randn(8, 201, 201), dim=-1)
cases["A_bmm_const"] = (ac, (pw,)); cases["A_bmm_input"] = (AInput().eval(), (pw, ac.v.detach().clone()))
class ASoftmax(torch.nn.Module):     # softmax(runtime logits) @ constant -- the attention core alone
    def __init__(s): super().__init__(); s.v = torch.nn.Parameter(torch.randn(8, 201, 32), requires_grad=False)
    def forward(s, l): return torch.bmm(torch.softmax(l, -1), s.v)
cases["A_softmax_const"] = (ASoftmax().eval(), (torch.randn(8, 201, 201),))

class AMha(torch.nn.Module):         # attention block: q = k = const + pos, v = const (layer 0's self-attention)
    def __init__(s, const=True):
        super().__init__(); s.const = const
        s.t = torch.nn.Parameter(torch.randn(201, 1, 256), requires_grad=False); s.mha = torch.nn.MultiheadAttention(256, 8)
    def forward(s, pos, t=None):
        t = s.t if s.const else t
        q = t + pos; L, nh, hd = 201, 8, 32
        wq, wk, wv = s.mha.in_proj_weight.chunk(3); bq, bk, bv = s.mha.in_proj_bias.chunk(3)
        qh = torch.nn.functional.linear(q, wq, bq).reshape(L, nh, hd).transpose(0, 1)
        kh = torch.nn.functional.linear(q, wk, bk).reshape(L, nh, hd).transpose(0, 1)
        vh = torch.nn.functional.linear(t, wv, bv).reshape(L, nh, hd).transpose(0, 1)
        o = torch.bmm(torch.softmax(torch.bmm(qh, kh.transpose(1, 2)) / hd ** 0.5, -1), vh)
        return torch.nn.functional.linear(o.transpose(0, 1).reshape(L, 1, 256), s.mha.out_proj.weight, s.mha.out_proj.bias)
am = AMha(True).eval(); ami = AMha(False).eval(); ami.load_state_dict(am.state_dict())
pos = torch.randn(201, 1, 256)
cases["A_mha_const"] = (am, (pos,)); cases["A_mha_input"] = (ami, (pos, am.t.detach().clone()))

class BSlice(torch.nn.Module):       # [1200,256] @ [256,1] -> [6,1,200,1] * s -> last batch slice (what the model output)
    def forward(s, a, w): return (torch.matmul(a, w).reshape(6, 1, 200, 1) * 0.0625)[-1]
class BLayers(torch.nn.Module):      # as in the model: Linear over [6,1,200,256] -> 2-D matmul -> [6,1,200,1] * s -> last slice
    def __init__(s): super().__init__(); s.lin = torch.nn.Linear(256, 256)
    def forward(s, hs, p):
        h = s.lin(hs)
        return (torch.matmul(h.reshape(-1, 256), p.reshape(-1, 1)).reshape(6, 1, 200, 1) * 0.0625)[-1]
cases["B_layers"] = (BLayers().eval(), (torch.randn(6, 1, 200, 256), torch.randn(1, 256)))

class BFcOnly(torch.nn.Module):      # Linear over [6,1,200,256] alone
    def __init__(s): super().__init__(); s.lin = torch.nn.Linear(256, 256)
    def forward(s, hs): return s.lin(hs)
class BFcReshape(torch.nn.Module):   # Linear over [6,1,200,256], reshaped to [1200,256]
    def __init__(s): super().__init__(); s.lin = torch.nn.Linear(256, 256)
    def forward(s, hs): return s.lin(hs).reshape(-1, 256)
hs6 = torch.randn(6, 1, 200, 256)
cases["B_fc_only"] = (BFcOnly().eval(), (hs6,)); cases["B_fc_reshape"] = (BFcReshape().eval(), (hs6,))

class BBmm4d(torch.nn.Module):       # single op: BATCH_MATMUL [6,1,200,256] x [256,1] (batch-broadcast rhs)
    def forward(s, h, p): return torch.matmul(h, p)
class BBmm4dB1(torch.nn.Module):     # control: batch 1, [1,1,1200,256] x [256,1]
    def forward(s, h, p): return torch.matmul(h.reshape(1, 1, 1200, 256), p)
cases["B_bmm4d"] = (BBmm4d().eval(), (hs6, torch.randn(256, 1)))
cases["B_bmm4d_b1"] = (BBmm4dB1().eval(), (hs6, torch.randn(256, 1)))

class BInput(torch.nn.Module):       # input [1200,1] -> [6,1,200,1] * 0.0625
    def forward(s, a): return a.reshape(6, 1, 200, 1) * 0.0625
class BMatmul(torch.nn.Module):      # [1200,256] @ [256,1] -> [6,1,200,1] * 0.0625 (the model's path)
    def forward(s, a, w): return torch.matmul(a, w).reshape(6, 1, 200, 1) * 0.0625
class BBatch1(torch.nn.Module):      # control: same values, batch 1
    def forward(s, a, w): return torch.matmul(a, w).reshape(1, 1, 1200, 1) * 0.0625
cases["B_input"] = (BInput().eval(), (torch.randn(1200, 1),))
cases["B_matmul"] = (BMatmul().eval(), (torch.randn(1200, 256), torch.randn(256, 1)))
cases["B_batch1"] = (BBatch1().eval(), cases["B_matmul"][1])
cases["B_slice"] = (BSlice().eval(), cases["B_matmul"][1])

lines = []
with torch.no_grad():
    for name, (m, args) in cases.items():
        litert_torch.convert(m, args).export(f"{OUT}/{name}.tflite")
        files = []
        for k, a in enumerate(args):
            a.numpy().astype(np.float32).tofile(f"{OUT}/{name}_in{k}.bin"); files.append(f"/data/local/tmp/repro/{name}_in{k}.bin")
        open(f"{OUT}/{name}.txt", "w").write(",".join(files) + "\n")
        ref = m(*args).numpy(); np.save(f"{OUT}/{name}_ref.npy", ref)
        print(f"{name}: inputs {[tuple(a.shape) for a in args]} -> output {ref.shape}", flush=True)
