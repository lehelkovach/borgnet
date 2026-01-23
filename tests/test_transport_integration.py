"""Integration tests for IAC bus transport (requires running bus)."""

import os
import uuid

import pytest

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
class TestIacBusLive:
    """Live integration tests against running IAC bus."""

    def test_post_and_retrieve_message(self, live_client):
        """Post a message and retrieve it."""
        channel = f"test-{uuid.uuid4().hex[:8]}"
        sender = "test-agent"
        message = f"hello-{uuid.uuid4().hex[:8]}"

        result = live_client.post_message(channel=channel, sender=sender, message=message)
        assert result.get("success") is True
        msg_id = result["message"]["id"]

        messages = live_client.get_messages(channel=channel, limit=10)
        assert any(m["id"] == msg_id for m in messages)

    def test_since_id_filtering(self, live_client):
        """Test that since_id filters older messages."""
        channel = f"test-{uuid.uuid4().hex[:8]}"

        # Post two messages
        r1 = live_client.post_message(channel=channel, sender="agent", message="first")
        r2 = live_client.post_message(channel=channel, sender="agent", message="second")

        first_id = r1["message"]["id"]
        second_id = r2["message"]["id"]

        # Fetch since first message
        messages = live_client.get_messages(channel=channel, since_id=first_id, limit=10)

        # Should only get the second message
        ids = [m["id"] for m in messages]
        assert second_id in ids
        assert first_id not in ids

    def test_empty_channel(self, live_client):
        """Test fetching from a channel with no messages."""
        channel = f"empty-{uuid.uuid4().hex[:8]}"
        messages = live_client.get_messages(channel=channel, limit=10)
        assert messages == []
