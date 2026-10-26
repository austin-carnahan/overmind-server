"""cerebrate_lifecycle against a fake cerebrate-supervisor with the real
capacity rule (free - cost >= reserve): on-demand start, making room by
stopping the least recently used idle worker, never stopping a busy one,
waiting for a busy one up to capacity_wait_s, failing with the supervisor's
reason, the lost-worker retry, and the idle stop. Standard library only:
  python3 -m unittest discover -s hosts/cerebrate-pixel6/mlserver/tests -v"""
import asyncio
import os
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "models" / "cerebrate-graph"))
os.environ["CEREBRATE_CAPACITY_WAIT_S"] = "2"
os.environ["CEREBRATE_IDLE_STOP_S"] = "1"
import cerebrate_lifecycle as lifecycle  # noqa: E402


class FakeSupervisor:
    """Total memory, a reserve, a cost per slot; START refuses below the reserve."""

    def __init__(self, total_mb, reserve_mb, costs):
        self.total, self.reserve, self.costs = total_mb, reserve_mb, costs
        self.running, self.log = set(), []

    def __call__(self, host, port, command, fields):
        slot = fields["worker"]
        self.log.append((command, slot))
        if command == "STOP":
            self.running.discard(slot)
            return "OK: stopped\n"
        if slot in self.running:
            return "OK: already running (idempotent)\n"
        free = self.total - sum(self.costs[s] for s in self.running)
        if free - self.costs[slot] < self.reserve:
            return f"ERROR: capacity: {slot} needs {self.costs[slot]} MB; {free} MB free, reserve {self.reserve} MB\n"
        self.running.add(slot)
        return "OK: started\n"


class Lifecycle(unittest.TestCase):
    def setUp(self):
        lifecycle._pool.clear()
        lifecycle._admission_lock = None
        # 3500 MB, reserve 1000: room for two of a, b, c (1000 each), not three.
        self.sup = FakeSupervisor(3500, 1000, {"a": 1000, "b": 1000, "c": 1000, "big": 2500})
        self._orig = lifecycle.supervisor_request
        lifecycle.supervisor_request = self.sup

    def tearDown(self):
        lifecycle.supervisor_request = self._orig
        for p in Path("/tmp").glob("cerebrate-worker-59999-*.refcount"):
            p.unlink()

    def workers(self, *slots):
        ws = {s: lifecycle.Worker(f"model-{s}", {"worker": s, "model": f"/m/{s}"}, host="h", supervisor_port=59999) for s in slots}
        for w in ws.values():
            w.activate()
        return ws

    async def request(self, w, seconds=0.0):
        async def call():
            await asyncio.sleep(seconds)
            return w.slot
        return await w.run(call)

    def run_async(self, coro):
        async def main():
            try:
                return await coro
            finally:
                for w in list(lifecycle._pool):
                    w._idle_task.cancel()
        return asyncio.run(main())

    def test_on_demand_start_and_idle_victim_lru(self):
        async def scenario():
            ws = self.workers("a", "b", "c")
            await self.request(ws["a"])
            await asyncio.sleep(0.01)
            await self.request(ws["b"])
            self.assertEqual(self.sup.running, {"a", "b"})
            await self.request(ws["c"])          # no room: a (least recently used, idle) is stopped
            self.assertEqual(self.sup.running, {"b", "c"})
            self.assertFalse(ws["a"].counted)
            await self.request(ws["a"])          # a starts again on its next request; b is now the LRU
            self.assertEqual(self.sup.running, {"a", "c"})
        self.run_async(scenario())

    def test_busy_worker_is_never_stopped_and_request_waits(self):
        async def scenario():
            ws = self.workers("a", "b", "c")
            await self.request(ws["b"])
            slow = asyncio.create_task(self.request(ws["a"], seconds=0.8))   # a busy for 0.8 s
            await asyncio.sleep(0.1)
            await self.request(ws["b"])          # b is touched now: a is the only other, and it's busy
            t0 = time.monotonic()
            await self.request(ws["c"])          # b idle -> stopped, room for c right away
            self.assertLess(time.monotonic() - t0, 0.5)
            self.assertIn("a", self.sup.running)
            await slow
        self.run_async(scenario())

    def test_waits_for_busy_then_fails_with_reason(self):
        async def scenario():
            ws = self.workers("a", "b", "big")
            ta = asyncio.create_task(self.request(ws["a"], seconds=5))
            await asyncio.sleep(0.1)
            t0 = time.monotonic()
            with self.assertRaises(lifecycle.WorkerUnavailable) as cm:
                await self.request(ws["big"])    # needs a's memory; a stays busy past the 2 s wait
            self.assertGreaterEqual(time.monotonic() - t0, 1.9)
            self.assertIn("capacity", str(cm.exception))
            self.assertIn("model-a", str(cm.exception))
            self.assertIn("a", self.sup.running)
            ta.cancel()
        self.run_async(scenario())

    def test_wait_succeeds_when_busy_worker_finishes(self):
        async def scenario():
            ws = self.workers("a", "big")
            ta = asyncio.create_task(self.request(ws["a"], seconds=0.7))
            await asyncio.sleep(0.1)
            await self.request(ws["big"])        # waits ~0.6 s, then a is idle and stopped
            self.assertEqual(self.sup.running, {"big"})
            await ta
        self.run_async(scenario())

    def test_lost_worker_is_restarted_once(self):
        async def scenario():
            ws = self.workers("a")
            calls = []

            async def flaky():
                calls.append(1)
                if len(calls) == 1:
                    raise ConnectionError("worker gone")
                return "ok"
            self.assertEqual(await ws["a"].run(flaky), "ok")
            self.assertEqual([c for c, s in self.sup.log], ["START", "STOP", "START"])
        self.run_async(scenario())

    def test_other_refusal_is_not_retried(self):
        async def scenario():
            ws = self.workers("a")
            orig = lifecycle.supervisor_request
            lifecycle.supervisor_request = lambda *a: "ERROR: model file not found: /m/a\n"
            try:
                with self.assertRaises(lifecycle.WorkerUnavailable) as cm:
                    await self.request(ws["a"])
                self.assertIn("model file not found", str(cm.exception))
            finally:
                lifecycle.supervisor_request = orig
        self.run_async(scenario())

    def test_idle_stop(self):
        async def scenario():
            # The policy file's idle window: 1 s here (environment), polled every 0.5 s.
            ws = self.workers("a")
            await self.request(ws["a"])
            self.assertIn("a", self.sup.running)
            await asyncio.sleep(1.8)
            self.assertNotIn("a", self.sup.running)
            self.assertFalse(ws["a"].counted)
        self.run_async(scenario())


if __name__ == "__main__":
    unittest.main()
