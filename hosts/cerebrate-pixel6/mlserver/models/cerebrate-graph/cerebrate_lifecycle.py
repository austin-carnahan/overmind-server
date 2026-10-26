"""Shared worker lifecycle for every Cerebrate MLServer adapter (cerebrate-graph
and cerebrate-hetero models, cerebrate-infer, cerebrate-generate,
cerebrate-gguf). The adapters keep only their request handling (wire
protocol, pre- and postprocessing); starting, stopping and making room live
here, the same for every Pixel model (decision 2026-10-25).

Policy (system-wide, never per model): serving_policy.json beside this file,
generated from models/catalog.yaml serving_policy by `scripts/cerebrate-models
generate`. A test MLServer may override it through the environment
(CEREBRATE_IDLE_STOP_S, CEREBRATE_CAPACITY_WAIT_S, CEREBRATE_SUPERVISOR_PORT).

Every worker runs on demand: a model reports ready without a worker; its first
request STARTs it through cerebrate-supervisor, and it is STOPped after
idle_stop_s without requests. Memory is the supervisor's decision: a START
that would take the phone below its reserve is refused with
"ERROR: capacity: ...". Then this module makes room -- it stops the least
recently used *idle* worker of this MLServer process (never one serving a
request) and asks again; if every other worker is busy, it waits up to
capacity_wait_s for one to finish, then fails the request with the
supervisor's capacity message. A stopped worker's model stays ready and
starts again on its next request.

One MLServer process (MLSERVER_PARALLEL_WORKERS=0) and one event loop, so the
pool below is every worker MLServer can start, and asyncio locks serialize
admission. This module is imported once and kept: MLServer reloads only each
model's own runtime module (mlserver/settings.py _reload_module), so the
pool survives model loads and unloads.

Refcounts stay file-backed and PID-tagged per slot (cerebrate_infer_runtime's
original reasoning): MLServer's rolling reload runs the new instance's load
before the old one's unload, both holding the same worker.
"""
import asyncio
import contextlib
import fcntl
import json
import os
import socket
import subprocess
import time

_HERE = os.path.dirname(os.path.realpath(__file__))

DEFAULT_HOST = "10.70.217.78"
SUPERVISOR_CONNECT_TIMEOUT_S = 5.0
# Covers cerebrate-supervisor's up-to-120 s readiness wait (large models and
# NNAPI compilation load slowly).
SUPERVISOR_COMMAND_TIMEOUT_S = 150.0
# Keyed by supervisor port too: a test MLServer on the same guest uses the same slot names.
REFCOUNT_PATH_TEMPLATE = "/tmp/cerebrate-worker-{port}-{slot}.refcount"


def _load_policy():
    with open(os.path.join(_HERE, "serving_policy.json")) as f:
        policy = json.load(f)
    return (float(os.environ.get("CEREBRATE_IDLE_STOP_S", policy["idle_stop_s"])),
            float(os.environ.get("CEREBRATE_CAPACITY_WAIT_S", policy["capacity_wait_s"])),
            int(os.environ.get("CEREBRATE_SUPERVISOR_PORT", 8767)))


IDLE_STOP_S, CAPACITY_WAIT_S, SUPERVISOR_PORT = _load_policy()


class WorkerUnavailable(Exception):
    """The worker could not be started (supervisor refusal, no capacity,
    failed verification). The message is the reason, for the client."""


def discover_gateway() -> str:
    """The AVF gateway (the Android host) is assigned per VM boot: read it
    from the guest's default route."""
    try:
        out = subprocess.check_output(["ip", "route", "show", "default"], text=True, timeout=2)
        for line in out.splitlines():
            parts = line.split()
            if "via" in parts:
                return parts[parts.index("via") + 1]
    except (subprocess.SubprocessError, OSError, ValueError):
        pass
    return DEFAULT_HOST


def supervisor_request(host: str, port: int, command: str, fields: dict) -> str:
    """One cerebrate-supervisor command. Blocking; callers use
    asyncio.to_thread so a slow START doesn't stall the event loop."""
    message = ("\n".join([command] + [f"{k}: {v}" for k, v in fields.items()]) + "\n\n").encode("utf-8")
    with socket.create_connection((host, port), timeout=SUPERVISOR_CONNECT_TIMEOUT_S) as sock:
        sock.settimeout(SUPERVISOR_COMMAND_TIMEOUT_S)
        sock.sendall(message)
        sock.shutdown(socket.SHUT_WR)
        chunks = []
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
    return b"".join(chunks).decode("utf-8", "replace")


def _adjust_refcount(path: str, delta: int) -> int:
    my_pid = os.getpid()
    with open(path, "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        owner_pid, _, count_str = f.read().strip().partition(":")
        count = int(count_str) if owner_pid == str(my_pid) and count_str else 0
        count = max(0, count + delta)
        f.seek(0)
        f.truncate()
        f.write(f"{my_pid}:{count}")
        fcntl.flock(f, fcntl.LOCK_UN)
    return count


_pool = []               # every active Worker in this process
_admission_lock = None   # one START decision at a time (created on first use, in the loop)


def _admission():
    global _admission_lock
    if _admission_lock is None:
        _admission_lock = asyncio.Lock()
    return _admission_lock


class Worker:
    """One MLServer model's hold on one supervisor slot.

    start_fields: the START fields (worker, model, and backend or mmproj).
    verify: optional async callable run after START (e.g. DESCRIBE); raises
      to refuse a worker that isn't serving what this model expects.
    drop: optional async callable closing the adapter's connection, run
      whenever the worker is released."""

    def __init__(self, name, start_fields, host=None, supervisor_port=None, verify=None, drop=None):
        self.name = name
        self.slot = start_fields["worker"]
        self.start_fields = dict(start_fields)
        self.host = host or discover_gateway()
        self.supervisor_port = supervisor_port or SUPERVISOR_PORT
        self.verify, self.drop = verify, drop
        self.refcount_path = REFCOUNT_PATH_TEMPLATE.format(port=self.supervisor_port, slot=self.slot)
        self.counted = False        # this instance holds the slot (a worker runs for it)
        self.busy = 0               # requests in progress
        self.last_used = time.monotonic()
        self._start_lock = asyncio.Lock()
        self._idle_task = None

    # ---- MLServer load / unload -------------------------------------------
    def activate(self):
        _pool.append(self)
        self._idle_task = asyncio.create_task(self._idle_stopper())
        print(f"cerebrate ({self.name}): on demand on {self.slot}, idle stop after {IDLE_STOP_S:.0f}s")

    async def deactivate(self) -> bool:
        if self._idle_task is not None:
            self._idle_task.cancel()
            self._idle_task = None
        if self in _pool:
            _pool.remove(self)
        async with self._start_lock:
            return await self._release()

    # ---- requests -----------------------------------------------------------
    @contextlib.asynccontextmanager
    async def use(self):
        """Hold the worker for one request (started on demand); it can't be
        stopped for idleness or room while held."""
        self.busy += 1
        try:
            await self._ensure_started()
            yield
        finally:
            self.busy -= 1
            self.last_used = time.monotonic()

    async def run(self, call):
        """Run one request (async callable) on the worker. A lost worker
        (ConnectionError: killed, or cleared after a supervisor restart)
        releases the slot and the request runs once more on a fresh worker --
        inference is stateless, so a retry can't double-apply anything."""
        for attempt in (1, 2):
            async with self.use():
                try:
                    return await call()
                except ConnectionError:
                    async with self._start_lock:
                        await self._release()
                    if attempt == 2:
                        raise
                    print(f"cerebrate ({self.name}): worker on {self.slot} lost; restarting it for this request")

    # ---- starting and stopping ---------------------------------------------
    async def _ensure_started(self):
        self.last_used = time.monotonic()
        if self.counted:
            return
        async with self._start_lock:
            if not self.counted:
                await self._admit()

    async def _admit(self):
        deadline = time.monotonic() + CAPACITY_WAIT_S
        async with _admission():
            while True:
                try:
                    response = await asyncio.to_thread(
                        supervisor_request, self.host, self.supervisor_port, "START", self.start_fields)
                except OSError as exc:
                    raise WorkerUnavailable(f"cerebrate-supervisor unreachable: {exc}") from exc
                if response.startswith("OK"):
                    await asyncio.to_thread(_adjust_refcount, self.refcount_path, 1)
                    self.counted = True
                    if self.verify is not None:
                        try:
                            await self.verify()
                        except Exception as exc:
                            await self._release()
                            raise WorkerUnavailable(f"worker on {self.slot} failed verification: {exc}") from exc
                    return
                if "capacity:" not in response:
                    raise WorkerUnavailable(f"supervisor refused START: {response.strip()}")
                victim = self._idle_victim()
                if victim is not None:
                    if await victim._evict():
                        print(f"cerebrate ({self.name}): stopped idle {victim.name} ({victim.slot}) to make room")
                    continue
                busy = [w.name for w in _pool if w is not self and w.counted and w.busy]
                if not busy or time.monotonic() >= deadline:
                    detail = (f"waited {CAPACITY_WAIT_S:.0f}s for {', '.join(busy)} to finish" if busy
                              else "no other worker to stop")
                    raise WorkerUnavailable(f"no capacity for {self.slot}: {response.strip()} ({detail})")
                await asyncio.sleep(0.5)

    def _idle_victim(self):
        """The least recently used running worker that serves no request."""
        idle = [w for w in _pool if w is not self and w.counted and not w.busy and not w._start_lock.locked()]
        return min(idle, key=lambda w: w.last_used) if idle else None

    async def _evict(self) -> bool:
        async with self._start_lock:
            if not self.counted or self.busy:
                return False
            return await self._release()

    async def _release(self) -> bool:
        """Drop this instance's hold; STOP the worker if no other instance
        holds the slot. Call with _start_lock held."""
        if self.drop is not None:
            await self.drop()
        if not self.counted:
            return True
        self.counted = False   # before any await: a new request now waits for _start_lock
        remaining = await asyncio.to_thread(_adjust_refcount, self.refcount_path, -1)
        if remaining > 0:
            return True
        try:
            response = await asyncio.to_thread(
                supervisor_request, self.host, self.supervisor_port, "STOP", {"worker": self.slot})
        except OSError as exc:
            print(f"cerebrate ({self.name}): failed to STOP {self.slot}: {exc}")
            return False
        if not response.startswith("OK"):
            print(f"cerebrate ({self.name}): supervisor STOP did not confirm: {response.strip()}")
            return False
        return True

    async def _idle_stopper(self):
        while True:
            await asyncio.sleep(min(30.0, IDLE_STOP_S / 2))
            if not self.counted or self.busy or time.monotonic() - self.last_used < IDLE_STOP_S:
                continue
            async with self._start_lock:
                if not self.counted or self.busy or time.monotonic() - self.last_used < IDLE_STOP_S:
                    continue
                if await self._release():
                    print(f"cerebrate ({self.name}): stopped {self.slot} after {IDLE_STOP_S:.0f}s idle")
