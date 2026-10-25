"""EfficientSAM3 photo path on the device: the adapter hook (torchvision-exact
resize, stdlib CLIP tokenizer, one worker call per phrase) around a graph-mode
worker must reproduce the validated phone-native chain's raw outputs bit for
bit on the 11 validation samples (sha256 of logits, boxes, presence, masks),
then return final detections. usage:
  esam3_photo_check.py <host> <port> <photos dir> <expect.json> <fast|default>"""
import sys, json, socket, hashlib, asyncio, time
import numpy as np
sys.path.insert(0, "/home/droid/cg-test/stage/code/cerebrate-graph")
import cerebrate_graph_protocol as protocol
import cerebrate_graph_photo as cgp

HOST, PORT, PHOTOS, EXP, KEY = sys.argv[1], int(sys.argv[2]), sys.argv[3], json.load(open(sys.argv[4])), sys.argv[5]


class In:
    def __init__(self, data, datatype="BYTES"): self.datatype, self.data = datatype, data


class Params:
    def __init__(self, **kw): self.__dict__.update(kw)


s = socket.create_connection((HOST, PORT)); s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
async def call(inputs):
    return protocol.call(s, inputs)

h = cgp.HOOKS["esam3"]()
same, t_prompt, n_det = 0, [], 0
for n, smp in enumerate(EXP["samples"]):
    photo = open(f"{PHOTOS}/photo{smp['photo']}.jpg", "rb").read()
    iid = In(np.array([smp["photo"]], np.int64).tolist(), "INT64")
    from mlserver.codecs import NumpyCodec
    from mlserver.types import RequestInput
    image_id = RequestInput(name="image_id", datatype="INT64", shape=[1], data=[smp["photo"]])
    t = time.perf_counter()
    raw, done = asyncio.run(h.run({"photo": In([photo]), "image_id": image_id, "prompts": In([smp["prompt"].encode()])}, Params(output="raw"), call))
    t_prompt.append(done["prompt_us"] / 1000)
    got = [hashlib.sha256(np.ascontiguousarray(raw[k]).tobytes()).hexdigest() for k in ("logits", "boxes", "presence", "masks")]
    ok = got == EXP[KEY][str(n)]
    same += ok
    res, _ = asyncio.run(h.run({"image_id": image_id, "prompts": In([smp["prompt"].encode()])}, None, call))
    doc = json.loads(res["result"]); dets = doc["prompts"][0]["detections"]; n_det += len(dets)
    print(f"sample {n} photo {smp['photo']} '{smp['prompt']}': raw {'bit-identical' if ok else 'DIFFERENT'}; {len(dets)} detections {[round(d['score'], 3) for d in dets]}; vision {done['vision_us']/1000:.0f} ms, prompt {done['prompt_us']/1000:.0f} ms")
print(f"{KEY}: {same}/11 samples bit-identical to the validated chain; {n_det} detections; prompt median {np.median(t_prompt):.0f} ms")
