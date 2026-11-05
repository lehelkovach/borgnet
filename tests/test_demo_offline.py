"""Offline tests for the master/workers demo using an in-memory fake bus.

The live demo tests need a running IAC Bus and are skipped in CI. These run
the same kill-recovery logic against a small thread-safe fake that models
queue leases (claim, lease expiry, ack with lease-id check) and a results
channel, so recovery and worker error handling are exercised everywhere.
"""

import threading
import time
import uuid

import pytest
import requests

from borgnet.demo import master_worker
from borgnet.demo.master_worker import Worker


class FakeBus:
    def __init__(self):
        self.lock = threading.Lock()
        self.queues = {}
        self.channels = {}
        self.counter = 0

    def next_id(self):
        self.counter += 1
        return f"m-{self.counter:06d}"


class FakeBusClient:
    """Implements the subset of IacBusClient the demo uses."""

    def __init__(self, bus, fail_claims=0, fail_acks=0):
        self.bus = bus
        self.fail_claims = fail_claims
        self.fail_acks = fail_acks

    def enqueue(self, queue, sender, message, priority=0):
        with self.bus.lock:
            item = {"id": self.bus.next_id(), "message": message, "status": "pending"}
            self.bus.queues.setdefault(queue, []).append(item)
            return {"success": True, "message": dict(item)}

    def claim(self, queue, worker, lease_seconds=None):
        if self.fail_claims:
            self.fail_claims -= 1
            raise requests.exceptions.ConnectionError("bus unreachable")
        with self.bus.lock:
            now = time.monotonic()
            for item in self.bus.queues.get(queue, []):
                if item["status"] == "leased" and item["lease_expires"] <= now:
                    item["status"] = "pending"
                if item["status"] == "pending":
                    item.update(
                        status="leased",
                        leased_by=worker,
                        lease_id=uuid.uuid4().hex,
                        lease_expires=now + (lease_seconds or 30),
                    )
                    return dict(item)
            return None

    def ack(self, queue, worker, message_id, lease_id):
        if self.fail_acks:
            self.fail_acks -= 1
            raise requests.exceptions.HTTPError("409 lease id mismatch")
        with self.bus.lock:
            for item in self.bus.queues.get(queue, []):
                if item["id"] == message_id:
                    valid = (
                        item["status"] == "leased"
                        and item["lease_id"] == lease_id
                        and item["lease_expires"] > time.monotonic()
                    )
                    if not valid:
                        raise requests.exceptions.HTTPError("409 lease id mismatch")
                    item["status"] = "done"
                    return {"success": True}
            raise requests.exceptions.HTTPError("404 not found")

    def post_message(self, channel, sender, message):
        with self.bus.lock:
            msg = {"id": self.bus.next_id(), "sender": sender, "message": message}
            self.bus.channels.setdefault(channel, []).append(msg)
            return {"success": True, "message": msg}

    def get_messages(self, channel, since_id=None, limit=50):
        with self.bus.lock:
            msgs = self.bus.channels.get(channel, [])
            if since_id is not None:
                msgs = [m for m in msgs if m["id"] > since_id]
            return [dict(m) for m in msgs[:limit]]


@pytest.fixture
def fake_bus(monkeypatch):
    bus = FakeBus()
    monkeypatch.setattr(
        master_worker, "IacBusClient", lambda base_url, token=None: FakeBusClient(bus)
    )
    return bus


def test_run_demo_recovers_killed_workers_task(fake_bus):
    result = master_worker.run_demo(
        bus_url="fake://bus", num_tasks=4, num_workers=2, lease_seconds=0.3,
        work_seconds=0.01, deadline_s=10,
    )
    assert result["success"] is True
    assert result["tasks_completed"] == 4
    assert result["duplicates"] == 0
    assert len(result["dead_worker_claimed"]) == 1
    assert result["recovery_verified"] is True
    assert result["recovered_task_ids"] == result["dead_worker_claimed"]


def test_run_demo_fails_without_survivors(fake_bus):
    # One worker that dies: its task is never recovered, so the run must fail.
    result = master_worker.run_demo(
        bus_url="fake://bus", num_tasks=2, num_workers=1, lease_seconds=0.2,
        work_seconds=0.01, deadline_s=1,
    )
    assert result["success"] is False
    assert result["recovery_verified"] is False


def _run_worker_until(worker, predicate, timeout=5.0):
    thread = threading.Thread(target=worker.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not predicate():
        time.sleep(0.01)
    worker.stop()
    thread.join(timeout=2)
    assert not thread.is_alive()


def test_worker_survives_claim_errors():
    bus = FakeBus()
    FakeBusClient(bus).enqueue("q", "master", {"task_id": "t-0"})
    worker = Worker(
        FakeBusClient(bus, fail_claims=2), "q", "results", "w-1",
        work_seconds=0.0, poll_interval_s=0.01,
    )
    _run_worker_until(worker, lambda: worker.completed_task_ids == ["t-0"])
    assert worker.completed_task_ids == ["t-0"]
    assert worker.errors == 2


def test_worker_does_not_report_task_when_ack_fails():
    bus = FakeBus()
    FakeBusClient(bus).enqueue("q", "master", {"task_id": "t-0"})
    worker = Worker(
        FakeBusClient(bus, fail_acks=1), "q", "results", "w-1",
        lease_seconds=0.05, work_seconds=0.0, poll_interval_s=0.01,
    )
    # First ack fails; the lease then expires and the same worker re-claims
    # and completes the task. Only the successful attempt is reported.
    _run_worker_until(worker, lambda: worker.completed_task_ids == ["t-0"])
    assert worker.errors == 1
    assert worker.completed_task_ids == ["t-0"]
    assert len(bus.channels["results"]) == 1
