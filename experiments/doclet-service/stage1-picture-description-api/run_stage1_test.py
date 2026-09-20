"""Stage 1 proof: submit a real conversion job to a running Docling Serve,
with do_picture_description routed at the dummy endpoint, and confirm the
dummy's fixed marker text actually lands in the output document.
"""
import base64
import json
import sys
import time
import urllib.request

DOCLING_SERVE = "http://127.0.0.1:5001"
PDF_PATH = sys.argv[1] if len(sys.argv) > 1 else "/mnt/doclet/scratch/sampling-variance-CFR.pdf"


def post(path, payload):
    req = urllib.request.Request(
        DOCLING_SERVE + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def get(path):
    with urllib.request.urlopen(DOCLING_SERVE + path, timeout=30) as resp:
        return json.loads(resp.read())


with open(PDF_PATH, "rb") as f:
    b64 = base64.b64encode(f.read()).decode()

payload = {
    "options": {
        "to_formats": ["md", "json"],
        "do_picture_description": True,
        "picture_description_api": {
            "url": "http://127.0.0.1:9100/v1/chat/completions",
            "params": {"model": "dummy", "max_completion_tokens": 200},
            "timeout": 30,
            "prompt": "Describe this image.",
        },
        "generate_picture_images": True,
    },
    "sources": [
        {"kind": "file", "base64_string": b64, "filename": "sampling-variance-CFR.pdf"}
    ],
}

print("submitting job...")
resp = post("/v1/convert/source/async", payload)
print("submit response:", json.dumps(resp)[:500])
task_id = resp["task_id"]

for i in range(60):
    status = get(f"/v1/status/poll/{task_id}")
    task_status = status.get("task_status")
    print(f"poll {i}: status={task_status}")
    if task_status in ("success", "failure"):
        break
    time.sleep(5)

result = get(f"/v1/result/{task_id}")
md = result.get("document", {}).get("md_content", "")
print("=== markdown length:", len(md))
marker = "DUMMY_ENRICHMENT_MARKER"
if marker in md:
    print(f"PROOF: marker '{marker}' found in output markdown.")
else:
    print(f"NOT FOUND: marker '{marker}' missing from output markdown.")
    print(md[:2000])

with open("/mnt/doclet/scratch/stage1_result.json", "w") as f:
    json.dump(result, f)
print("full result saved to /mnt/doclet/scratch/stage1_result.json")
