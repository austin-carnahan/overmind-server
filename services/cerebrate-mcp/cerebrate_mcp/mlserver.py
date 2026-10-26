"""MLServer's V2 REST API, the transport every Overmind-side client uses
(services/doclet/vlm-adapter: JSON over HTTP, BYTES inputs as base64 text).
Standard library only."""
import json
import urllib.error
import urllib.request


class MLServerError(Exception):
    """MLServer refused or failed a request; the message is its reason."""


class MLServer:
    def __init__(self, url: str, timeout_s: float = 300.0):
        self.url = url.rstrip("/")
        self.timeout_s = timeout_s

    def _post(self, path: str, payload: dict, timeout_s: float) -> dict:
        request = urllib.request.Request(
            f"{self.url}{path}", data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout_s) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            try:
                reason = json.loads(body).get("error", body)
            except ValueError:
                reason = body
            raise MLServerError(f"{path}: HTTP {exc.code}: {reason}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise MLServerError(f"MLServer at {self.url} unreachable: {exc}") from exc

    def readiness(self) -> dict:
        """{model name: state} from the repository index (READY = loaded; an
        on-demand Cerebrate model is READY without a running worker)."""
        index = self._post("/v2/repository/index", {}, timeout_s=10)
        return {m["name"]: m.get("state") for m in index}

    def infer(self, endpoint: str, inputs: list, parameters: dict | None = None) -> dict:
        """One inference; returns the photo hooks' JSON document (the
        "result" output)."""
        payload = {"inputs": inputs}
        if parameters:
            payload["parameters"] = parameters
        response = self._post(f"/v2/models/{endpoint}/infer", payload, self.timeout_s)
        for output in response.get("outputs", []):
            if output.get("name") == "result":
                value = output["data"][0]
                return json.loads(value) if isinstance(value, str) else value
        raise MLServerError(f"{endpoint}: response has no 'result' output")


def bytes_input(name: str, b64: str) -> dict:
    return {"name": name, "shape": [1], "datatype": "BYTES", "data": [b64]}


def tensor_input(name: str, datatype: str, shape: list, values: list) -> dict:
    return {"name": name, "shape": shape, "datatype": datatype, "data": values}
