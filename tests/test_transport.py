"""Unit tests for transport module (mocked HTTP)."""

from unittest.mock import MagicMock, patch

import pytest

from borgnet.transport.iac_bus import IacBusClient


@pytest.fixture
def client():
    return IacBusClient(base_url="http://localhost:8091", token="testtoken")


def test_headers_with_token(client):
    headers = client._headers()
    assert headers["Authorization"] == "Bearer testtoken"
    assert headers["Content-Type"] == "application/json"


def test_headers_without_token():
    c = IacBusClient(base_url="http://localhost:8091", token=None)
    headers = c._headers()
    assert "Authorization" not in headers


@patch("borgnet.transport.iac_bus.requests.post")
def test_post_message_success(mock_post, client):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"success": True, "message": {"id": "msg-1"}}
    mock_resp.raise_for_status = MagicMock()
    mock_post.return_value = mock_resp

    result = client.post_message(channel="ops", sender="agent-a", message="hello")

    mock_post.assert_called_once()
    assert result["success"] is True
    assert result["message"]["id"] == "msg-1"


@patch("borgnet.transport.iac_bus.requests.get")
def test_get_messages_success(mock_get, client):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "messages": [
            {"id": "msg-1", "channel": "ops", "sender": "agent-a", "message": "hello"}
        ]
    }
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    messages = client.get_messages(channel="ops", limit=10)

    mock_get.assert_called_once()
    assert len(messages) == 1
    assert messages[0]["id"] == "msg-1"


@patch("borgnet.transport.iac_bus.requests.get")
def test_get_messages_with_since_id(mock_get, client):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"messages": []}
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    client.get_messages(channel="ops", since_id="msg-0", limit=20)

    call_args = mock_get.call_args
    assert call_args.kwargs["params"]["since_id"] == "msg-0"
    assert call_args.kwargs["params"]["limit"] == 20
