"""Stage 1 dummy endpoint: proves Docling Serve's picture_description_api
config actually reaches a remote OpenAI-compatible endpoint with an image
payload, before any real Cerebrate backend exists.

Not production code -- logs and returns a fixed string for any request.
"""
import json
import logging
from fastapi import FastAPI, Request
import uvicorn

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("dummy-vlm")

app = FastAPI()


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    messages = body.get("messages", [])
    image_count = 0
    prompt_text = None
    for m in messages:
        content = m.get("content")
        if isinstance(content, list):
            for part in content:
                if part.get("type") == "image_url":
                    image_count += 1
                    url = part.get("image_url", {}).get("url", "")
                    log.info("image_url part: prefix=%s len=%d", url[:40], len(url))
                elif part.get("type") == "text":
                    prompt_text = part.get("text")

    log.info(
        "request received: model=%s messages=%d images=%d prompt=%r",
        body.get("model"), len(messages), image_count, prompt_text,
    )
    log.info("full request body keys: %s", list(body.keys()))

    return {
        "id": "dummy-1",
        "object": "chat.completion",
        "model": body.get("model", "dummy"),
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "DUMMY_ENRICHMENT_MARKER: this text proves the picture_description_api round trip works.",
                },
                "finish_reason": "stop",
            }
        ],
    }


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=9100)
