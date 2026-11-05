"""Integration tests for the master/workers demo (requires running bus)."""

import os
import uuid

import pytest

from borgnet.demo.master_worker import run_demo
from borgnet.transport.iac_bus import IacBusClient


BUS_URL = os.environ.get("BUS_URL", "http://127.0.0.1:8091")
BUS_TOKEN = os.environ.get("BUS_API_TOKEN", "")


def bus_available() -> bool:
    """Check if IAC bus is reachable."""
    import requests
    try:
        resp = requests.get(f"{BUS_URL}/health", timeout=2)
        return resp.status_code == 200
    except Exception:
        return False


@pytest.fixture
def live_client():
    """Create a client connected to live IAC bus."""
    return IacBusClient(base_url=BUS_URL, token=BUS_TOKEN or None)


@pytest.mark.skipif(not bus_available(), reason="IAC bus not available")
class TestQueueLeasingLive:
    """Live tests for the queue-leasing client methods."""

    def test_enqueue_claim_ack_cycle(self, live_client):
        queue = f"test-queue-{uuid.uuid4().hex[:8]}"

        result = live_client.enqueue(
            queue=queue, sender="tester", message={"task_id": "t-0"}
        )
        assert result.get("success") is True
        msg_id = result["message"]["id"]
        assert result["message"]["status"] == "pending"

        claimed = live_client.claim(queue=queue, worker="w-1", lease_seconds=30)
        assert claimed is not None
        assert claimed["id"] == msg_id
        assert claimed["status"] == "leased"
        assert claimed["lease_id"]

        acked = live_client.ack(
            queue=queue,
            worker="w-1",
            message_id=msg_id,
            lease_id=claimed["lease_id"],
        )
        assert acked.get("success") is True

        # Queue is now empty: claim returns None (HTTP 204).
        assert live_client.claim(queue=queue, worker="w-1") is None

    def test_nack_requeues_message(self, live_client):
        queue = f"test-queue-{uuid.uuid4().hex[:8]}"

        result = live_client.enqueue(queue=queue, sender="tester", message="job")
        msg_id = result["message"]["id"]

        claimed = live_client.claim(queue=queue, worker="w-1", lease_seconds=30)
        assert claimed["id"] == msg_id

        nacked = live_client.nack(
            queue=queue,
            worker="w-1",
            message_id=msg_id,
            lease_id=claimed["lease_id"],
            requeue=True,
        )
        assert nacked.get("success") is True

        # Message is pending again and claimable by another worker.
        reclaimed = live_client.claim(queue=queue, worker="w-2", lease_seconds=30)
        assert reclaimed is not None
        assert reclaimed["id"] == msg_id
        assert reclaimed["leased_by"] == "w-2"
        assert reclaimed["lease_id"] != claimed["lease_id"]

        live_client.ack(
            queue=queue,
            worker="w-2",
            message_id=msg_id,
            lease_id=reclaimed["lease_id"],
        )


@pytest.mark.skipif(not bus_available(), reason="IAC bus not available")
class TestMasterWorkerDemoLive:
    """Run the full kill-recovery demo against the live bus."""

    def test_run_demo_kill_recovery(self):
        result = run_demo(
            bus_url=BUS_URL,
            token=BUS_TOKEN or None,
            num_tasks=4,
            num_workers=2,
            lease_seconds=2,
        )

        assert result["success"] is True
        assert result["tasks_completed"] == 4
        assert result["duplicates"] == 0
        # The doomed worker claimed a task and died; a survivor recovered it.
        assert len(result["dead_worker_claimed"]) == 1
        assert result["recovered_task_ids"] == result["dead_worker_claimed"]
