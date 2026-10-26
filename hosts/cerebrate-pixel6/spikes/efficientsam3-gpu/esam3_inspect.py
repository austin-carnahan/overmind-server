"""Operator inspection of LiteRT graphs against the Mali-G78 risk patterns
recorded in the lane plan (Section 4.5): op counts; tensors above 4-D (the
classic delegate's limit; LiteRT GPU varies); non-float model I/O; ops that
commonly fall back (GATHER/GATHER_ND/BROADCAST_TO/ARG_MAX/CAST/int math);
large constants consumed by non-weight ops (rule 3); per-channel broadcast
multiplies (rule 4)."""
import sys, collections
import numpy as np
from ai_edge_litert.interpreter import Interpreter
WEIGHT_OPS = {"CONV_2D", "DEPTHWISE_CONV_2D", "FULLY_CONNECTED", "TRANSPOSE_CONV", "EMBEDDING_LOOKUP"}
WATCH = {"GATHER", "GATHER_ND", "BROADCAST_TO", "ARG_MAX", "ARG_MIN", "CAST", "SELECT", "SELECT_V2", "SIGN", "LOG", "TOPK_V2",
         "SCATTER_ND", "WHERE", "CUMSUM", "RANGE", "FLOOR_DIV", "EQUAL", "NOT_EQUAL", "LESS", "GREATER", "LOGICAL_AND", "LOGICAL_OR", "LOGICAL_NOT"}
for path in sys.argv[1:]:
    it = Interpreter(model_path=path); ops = it._get_ops_details(); td = {t["index"]: t for t in it.get_tensor_details()}
    produced = {o for op in ops for o in op["outputs"]}
    ins = {d["index"] for d in it.get_input_details()}
    const = lambda i: i >= 0 and i not in produced and i not in ins
    cnt = collections.Counter(op["op_name"] for op in ops)
    print(f"\n== {path.split('/')[-1]}: {len(ops)} ops")
    print("   ", ", ".join(f"{k} {v}" for k, v in cnt.most_common()))
    for d in it.get_input_details() + it.get_output_details():
        if d["dtype"] != np.float32: print(f"    non-float I/O: {d['name']} {d['dtype'].__name__} {list(d['shape'])}")
    hi = collections.Counter(); watch = collections.Counter(); bigc = collections.Counter(); pcm = 0
    for op in ops:
        n = op["op_name"]
        if any(len(td[i]["shape"]) > 4 for i in list(op["inputs"]) + list(op["outputs"]) if i >= 0): hi[n] += 1
        if n in WATCH or any(td[i]["dtype"] not in (np.float32,) for i in op["outputs"]): watch[f"{n}->{td[op['outputs'][0]]['dtype'].__name__}"] += 1
        if n not in WEIGHT_OPS:
            for i in op["inputs"]:
                if const(i) and np.prod(td[i]["shape"]) >= 100_000: bigc[f"{n} {list(td[i]['shape'])}"] += 1
        if n == "MUL":
            a = [i for i in op["inputs"] if i >= 0]
            for c, x in ((a[0], a[1]), (a[1], a[0])):
                cs, xs = td[c]["shape"], td[x]["shape"]
                if const(c) and len(xs) >= 2 and np.prod(cs) > 1 and np.prod(cs) == xs[-1] and np.prod(cs) == cs[-1]: pcm += 1
    print("    ops touching >4-D tensors:", dict(hi) or "none")
    print("    watch-list / non-float ops:", dict(watch) or "none")
    print("    large constants into non-weight ops:", dict(bigc) or "none")
    print("    per-channel broadcast MULs ([..,C] x const[C]):", pcm)
