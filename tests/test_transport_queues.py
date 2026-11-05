"""Unit tests for IacBusClient queue-leasing methods (mocked HTTP)."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from borgnet.transport.iac_bus import IacBusClient


@pytest.fixture
def client():
    return IacBusClient(base_url="http://localhost:8091", token="testtoken")


@patch("borgnet.transport.iac_bus.requests.post")
def test_enqueue_success(mock_post, client):
    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_resp.json.return_value = {
        "success": True,
        "message": {"id": "msg-1", "queue": "work", "status": "pending"},
    }
    mock_resp.raise_for_status = MagicMock()
    mock_post.return_value = mock_resp

    result = client.enqueue(
        queue="work", sender="master", message={"task_id": "task-0"}
    )

    mock_post.assert_called_once()
    call_args = mock_post.call_args
    assert call_args.args[0] == "http://localhost:8091/bus/messages"
    assert call_args.kwargs["json"]["queue"] == "work"
    assert call_args.kwargs["json"]["sender"] == "master"
    assert call_args.kwargs["json"]["message"] == {"task_id": "task-0"}
    assert call_args.kwargs["json"]["priority"] == 0
    assert result["success"] is True
    assert result["message"]["id"] == "msg-1"


@patch("borgnet.transport.iac_bus.requests.post")
def test_claim_success(mock_post, client):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "message": {
            "id": "msg-1",
            "queue": "work",
            "status": "leased",
            "leased_by": "worker-1",
            "lease_id": "lease-abc",
        }
    }
    mock_resp.raise_for_status = MagicMock()
    mock_post.return_value = mock_resp

    message = client.claim(queue="work", worker="worker-1", lease_seconds=30)

    mock_post.assert_called_once()
    call_args = mock_post.call_args
    assert call_args.args[0] == "http://localhost:8091/bus/queues/claim"
    assert call_args.kwargs["json"] == {
        "queue": "work",
        "worker": "worker-1",
        "lease_seconds": 30,
    }
    assert message["id"] == "msg-1"
    assert message["lease_id"] == "lease-abc"


@patch("borgnet.transport.iac_bus.requests.post")
def test_claim_empty_queue_returns_none(mock_post, client):
    mock_resp = MagicMock()
    mock_resp.status_code = 204
    mock_resp.raise_for_status = MagicMock()
    mock_post.return_value = mock_resp

    message = client.claim(queue="work", worker="worker-1")

    call_args = mock_post.call_args
    assert "lease_seconds" not in call_args.kwargs["json"]
    assert message is None


@patch("borgnet.transport.iac_bus.requests.post")
def test_ack_success(mock_post, client):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"success": True, "message": {"id": "msg-1"}}
    mock_resp.raise_for_status = MagicMock()
    mock_post.return_value = mock_resp

    result = client.ack(
        queue="work", worker="worker-1", message_id="msg-1", lease_id="lease-abc"
    )

    mock_post.assert_called_once()
    call_args = mock_post.call_args
    assert call_args.args[0] == "http://localhost:8091/bus/queues/ack"
    assert call_args.kwargs["json"] == {
        "queue": "work",
        "worker": "worker-1",
        "message_id": "msg-1",
        "lease_id": "lease-abc",
    }
    assert result["success"] is True


@patch("borgnet.transport.iac_bus.requests.post")
def test_nack_requeue(mock_post, client):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "success": True,
        "message": {"id": "msg-1", "status": "pending"},
    }
    mock_resp.raise_for_status = MagicMock()
    mock_post.return_value = mock_resp

    result = client.nack(
        queue="work",
        worker="worker-1",
        message_id="msg-1",
        lease_id="lease-abc",
    )

    mock_post.assert_called_once()
    call_args = mock_post.call_args
    assert call_args.args[0] == "http://localhost:8091/bus/queues/nack"
    assert call_args.kwargs["json"] == {
        "queue": "work",
        "worker": "worker-1",
        "message_id": "msg-1",
        "lease_id": "lease-abc",
        "requeue": True,
    }
    assert result["success"] is True


@patch("borgnet.transport.iac_bus.requests.post")
def test_nack_no_requeue(mock_post, client):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"success": True, "message": {"id": "msg-1"}}
    mock_resp.raise_for_status = MagicMock()
    mock_post.return_value = mock_resp

    client.nack(
        queue="work",
        worker="worker-1",
        message_id="msg-1",
        lease_id="lease-abc",
        requeue=False,
    )

    call_args = mock_post.call_args
    assert call_args.kwargs["json"]["requeue"] is False


@patch("borgnet.transport.iac_bus.requests.post")
def test_ack_http_error_raises(mock_post, client):
    mock_resp = MagicMock()
    mock_resp.status_code = 409
    error = requests.exceptions.HTTPError(response=mock_resp)
    mock_resp.raise_for_status.side_effect = error
    mock_resp.text = '{"error": "lease id mismatch"}'
    mock_post.return_value = mock_resp

    with pytest.raises(requests.exceptions.HTTPError):
        client.ack(
            queue="work",
            worker="worker-1",
            message_id="msg-1",
            lease_id="stale-lease",
        )


@patch("borgnet.transport.iac_bus.requests.post")
def test_claim_uses_auth_headers(mock_post, client):
    mock_resp = MagicMock()
    mock_resp.status_code = 204
    mock_resp.raise_for_status = MagicMock()
    mock_post.return_value = mock_resp

    client.claim(queue="work", worker="worker-1")

    call_args = mock_post.call_args
    assert call_args.kwargs["headers"]["Authorization"] == "Bearer testtoken"
