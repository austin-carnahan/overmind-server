"""Graph-mode serving fidelity: the validated device inputs (raw float32
tensors from the spikes) sent to a cerebrate-hetero graph-mode worker must
give the validated device outputs bit for bit (same graph, precision and
LiteRT build). usage:
  graph_fidelity.py <host> <port> <input name> <shape,comma> <inputs: dir/{i}.bin pattern> <validated outputs: dir with <i>_o<k>.bin> [n]
e.g. graph_fidelity.py $GW 8792 pixel_values 1,3,518,686 depth/inputs/{i}.bin depth/out-fp32-gpu-fp32 8"""
import sys, socket, time
import numpy as np
sys.path.insert(0, "/home/droid/cg-test/stage/code/cerebrate-graph")
import cerebrate_graph_protocol as protocol
HOST, PORT, NAME, SHAPE, PAT, REF = sys.argv[1], int(sys.argv[2]), sys.argv[3], tuple(int(v) for v in sys.argv[4].split(",")), sys.argv[5], sys.argv[6]
N = int(sys.argv[7]) if len(sys.argv) > 7 else 8
s = socket.create_connection((HOST, PORT)); s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
desc, _ = protocol.call(s, {})
same, inf = 0, []
for i in range(N):
    x = np.fromfile(PAT.format(i=i), np.float32).reshape(SHAPE)
    out, done = protocol.call(s, {NAME: x}); inf.append(done["inference_us"] / 1000)
    ok = True
    for k, (name, v) in enumerate(out.items()):
        ref = np.fromfile(f"{REF}/{i}_o{k}.bin", v.dtype)
        if ref.size != v.size or not np.array_equal(ref, v.ravel()):
            ok = False
            print(f"  photo {i} output {name}: max |diff| {np.abs(ref.astype(np.float64) - v.ravel().astype(np.float64)).max() if ref.size == v.size else 'size mismatch'}")
    same += ok
print(f"{desc['backend']} [{desc['config'][:90]}]: {same}/{N} bit-identical to {REF}; worker inference median {np.median(inf):.1f} ms (first {inf[0]:.0f} ms)")
