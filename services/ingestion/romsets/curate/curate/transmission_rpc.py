"""Minimal Transmission RPC client -- just enough for queue_download.py's
add-one-torrent, select-some-files, start workflow. Not a general client.

Transmission's RPC protocol requires an X-Transmission-Session-Id header,
handed back on a 409 response to the first request and then reused for
every call after; it rotates occasionally, so any call can 409 again and
needs one retry with the fresh id.
"""

import requests


class TransmissionClient:
    def __init__(self, host: str, port: int, username: str, password: str):
        self.url = f"http://{host}:{port}/transmission/rpc"
        self.auth = (username, password)
        self.session = requests.Session()
        self._session_id = None

    def _call(self, method: str, arguments: dict) -> dict:
        headers = {"X-Transmission-Session-Id": self._session_id} if self._session_id else {}
        resp = self.session.post(
            self.url,
            json={"method": method, "arguments": arguments},
            headers=headers,
            auth=self.auth,
            timeout=30,
        )
        if resp.status_code == 409:
            self._session_id = resp.headers["X-Transmission-Session-Id"]
            resp = self.session.post(
                self.url,
                json={"method": method, "arguments": arguments},
                headers={"X-Transmission-Session-Id": self._session_id},
                auth=self.auth,
                timeout=30,
            )
        resp.raise_for_status()
        data = resp.json()
        if data.get("result") != "success":
            raise RuntimeError(f"Transmission RPC {method} failed: {data.get('result')}")
        return data.get("arguments", {})

    def torrent_add(self, magnet: str, download_dir: str, paused: bool = True) -> dict:
        result = self._call(
            "torrent-add",
            {"filename": magnet, "download-dir": download_dir, "paused": paused},
        )
        return result.get("torrent-added") or result.get("torrent-duplicate")

    def torrent_get(self, ids: list[int], fields: list[str]) -> list[dict]:
        result = self._call("torrent-get", {"ids": ids, "fields": fields})
        return result["torrents"]

    def torrent_set(self, ids: list[int], files_wanted: list[int], files_unwanted: list[int]) -> None:
        self._call(
            "torrent-set",
            {"ids": ids, "files-wanted": files_wanted, "files-unwanted": files_unwanted},
        )

    def torrent_start(self, ids: list[int]) -> None:
        self._call("torrent-start", {"ids": ids})

    def torrent_stop(self, ids: list[int]) -> None:
        self._call("torrent-stop", {"ids": ids})

    def torrent_remove(self, ids: list[int], delete_local_data: bool = False) -> None:
        self._call("torrent-remove", {"ids": ids, "delete-local-data": delete_local_data})
