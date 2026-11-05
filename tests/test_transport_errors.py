"""Regression tests: HTTP errors must log the real status code and body.

These use a real ``requests.Response`` rather than a ``MagicMock``. A real
Response is falsy for 4xx/5xx statuses, which is exactly what hid the bug
where every HTTP error was logged as ``status=N/A response=N/A``.
"""

import logging
from unittest.mock import patch

import pytest
import requests

from borgnet.transport.iac_bus import IacBusClient, _http_error_details


def _error_response(status: int = 503, body: bytes = b'{"error": "bus down"}'):
    resp = requests.Response()
    resp.status_code = status
    resp._content = body
    resp.url = "http://localhost:8091/bus/messages"
    return resp


CALLS = [
    ("post", lambda c: c.post_message(channel="ops", sender="a", message="hi")),
    ("get", lambda c: c.get_messages(channel="ops")),
    ("post", lambda c: c.enqueue(queue="work", sender="a", message={"x": 1})),
    ("post", lambda c: c.claim(queue="work", worker="w-1")),
    ("post", lambda c: c.ack(queue="work", worker="w-1", message_id="m", lease_id="l")),
    ("post", lambda c: c.nack(queue="work", worker="w-1", message_id="m", lease_id="l")),
]


@pytest.mark.parametrize(
    "verb,call", CALLS, ids=["post_message", "get_messages", "enqueue", "claim", "ack", "nack"]
)
def test_http_error_logs_status_and_body(verb, call, caplog):
    caplog.set_level(logging.ERROR, logger="borgnet")
    client = IacBusClient(base_url="http://localhost:8091")
    with patch(f"borgnet.transport.iac_bus.requests.{verb}", return_value=_error_response()):
        with pytest.raises(requests.exceptions.HTTPError):
            call(client)
    logged = caplog.text
    assert "status=503" in logged
    assert "bus down" in logged
    assert "status=N/A" not in logged


def test_http_error_details_without_response():
    assert _http_error_details(requests.exceptions.HTTPError("boom")) == ("N/A", "N/A")


def test_http_error_details_truncates_body():
    err = requests.exceptions.HTTPError(response=_error_response(500, b"x" * 500))
    status, body = _http_error_details(err)
    assert status == 500
    assert len(body) == 200
