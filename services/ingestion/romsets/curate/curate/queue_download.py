"""Stage: queue-download. For remote-scanned disc-based platforms, add the
shared per-system Redump torrent to Transmission and select only the
selected top-N's files (plus every disc of a multi-disc release) via
files-wanted -- never the whole multi-TB archive.

Every title in a Minerva/Myrient-style system catalog shares one torrent
(one info-hash, confirmed identical magnet across records during
remote-scan), so this only ever adds one torrent per platform. It's added
paused so file selection can be applied before any data moves; Transmission
doesn't know a torrent's file list until its metadata is fetched from the
swarm, which is why this polls torrent-get after adding rather than setting
files-wanted in the same call.
"""

import time

from .transmission_rpc import TransmissionClient


def _wait_for_status(
    client: TransmissionClient, torrent_id: int, stopped: bool, timeout_seconds: float = 30.0
) -> None:
    """Transmission's torrent-stop/torrent-start RPC calls return success as
    soon as the request is queued, not once the daemon has actually applied
    it -- confirmed against the real service: a torrent-set immediately
    after torrent-stop can still see the old (running) state, and the
    matching torrent-start after that then has nothing to do, leaving the
    torrent stuck stopped despite every call "succeeding". Poll until the
    status actually reflects the request before moving on.
    """
    waited = 0.0
    while waited < timeout_seconds:
        info = client.torrent_get([torrent_id], ["status"])[0]
        is_stopped = info["status"] == 0
        if is_stopped == stopped:
            return
        time.sleep(1.0)
        waited += 1.0
    raise TimeoutError(f"torrent {torrent_id} did not reach {'stopped' if stopped else 'running'} state in time")


def _wanted_so_ids(top: list[dict]) -> set[int]:
    wanted = set()
    for record in top:
        if record.get("so_id") is not None:
            wanted.add(record["so_id"])
        for disc in record.get("disc_files", []):
            if disc.get("so_id") is not None:
                wanted.add(disc["so_id"])
    return wanted


def queue_download(
    top: list[dict],
    client: TransmissionClient,
    download_dir: str,
    poll_interval_seconds: float = 3.0,
    max_wait_seconds: float = 300.0,
) -> dict:
    if not top:
        raise ValueError("nothing to queue -- empty selection")

    magnet = top[0].get("magnet")
    if not magnet:
        raise ValueError("selection has no magnet link -- was this platform built via remote-scan?")
    torrent_path = top[0].get("torrent_path")
    for record in top:
        if record.get("magnet") != magnet:
            raise ValueError(
                f"selection spans more than one torrent ({record.get('canonical_filename')!r} "
                f"has a different magnet) -- queue_download only handles one shared torrent"
            )

    wanted_so_ids = _wanted_so_ids(top)

    # Transmission does no network activity at all -- no DHT, no trackers,
    # no peers -- while a torrent is paused, so a magnet's file list can
    # only ever arrive while it's running. Add unpaused, then stop it the
    # instant metadata arrives, *before* touching file selection, so the
    # default "everything wanted" window between metadata completion and
    # our files-set call is as short as one RPC round trip rather than a
    # full poll interval.
    added = client.torrent_add(magnet, download_dir, paused=False)
    torrent_id = added["id"]

    waited = 0.0
    files = None
    while waited < max_wait_seconds:
        info = client.torrent_get([torrent_id], ["files", "metadataPercentComplete", "name"])[0]
        if info["metadataPercentComplete"] >= 1.0 and info["files"]:
            client.torrent_stop([torrent_id])
            _wait_for_status(client, torrent_id, stopped=True)
            files = info["files"]
            name = info["name"]
            break
        time.sleep(poll_interval_seconds)
        waited += poll_interval_seconds

    if files is None:
        raise TimeoutError(
            f"torrent metadata not fetched from the swarm after {max_wait_seconds}s "
            f"(torrent id {torrent_id}, left running -- check tracker/peer health, or just retry)"
        )

    all_indices = set(range(len(files)))
    files_wanted = sorted(wanted_so_ids & all_indices)
    missing_so_ids = wanted_so_ids - all_indices
    files_unwanted = sorted(all_indices - wanted_so_ids)

    client.torrent_set([torrent_id], files_wanted=files_wanted, files_unwanted=files_unwanted)
    client.torrent_start([torrent_id])
    _wait_for_status(client, torrent_id, stopped=False)

    selected_bytes = sum(files[i]["length"] for i in files_wanted)

    return {
        "torrent_id": torrent_id,
        "torrent_name": name,
        "torrent_path": torrent_path,
        "total_files_in_torrent": len(files),
        "files_selected": len(files_wanted),
        "missing_so_ids": sorted(missing_so_ids),
        "selected_bytes": selected_bytes,
    }
