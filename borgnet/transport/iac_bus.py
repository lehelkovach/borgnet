"""IAC Bus HTTP transport adapter."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import requests

from borgnet.logging import get_logger

_log = get_logger("transport.iac_bus")


class IacBusClient:
    """HTTP client for IAC Bus message broker."""

    def __init__(self, base_url: str, token: str | None = None, timeout_s: int = 10):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout_s = timeout_s
        _log.debug(
            "IacBusClient initialized: url=%s token=%s timeout=%d",
            self.base_url,
            "***" if token else None,
            timeout_s,
        )

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def post_message(self, channel: str, sender: str, message: str) -> Dict[str, Any]:
        """Post a message to the bus."""
        url = f"{self.base_url}/bus/messages"
        payload = {"channel": channel, "sender": sender, "message": message}

        _log.debug(
            "POST message: url=%s channel=%s sender=%s message_len=%d",
            url,
            channel,
            sender,
            len(message),
        )

        try:
            resp = requests.post(
                url,
                headers=self._headers(),
                json=payload,
                timeout=self.timeout_s,
            )
            resp.raise_for_status()
            result = resp.json()
            msg_id = result.get("message", {}).get("id", "unknown")
            _log.info(
                "Message posted: channel=%s sender=%s id=%s",
                channel,
                sender,
                msg_id,
            )
            return result

        except requests.exceptions.Timeout:
            _log.error(
                "POST timeout: url=%s channel=%s timeout=%ds",
                url,
                channel,
                self.timeout_s,
            )
            raise

        except requests.exceptions.HTTPError as e:
            _log.error(
                "POST HTTP error: url=%s status=%s response=%s",
                url,
                e.response.status_code if e.response else "N/A",
                e.response.text[:200] if e.response else "N/A",
            )
            raise

        except requests.exceptions.RequestException as e:
            _log.error("POST request error: url=%s error=%s", url, e)
            raise

    def get_messages(
        self,
        channel: str,
        since_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Fetch messages from the bus."""
        url = f"{self.base_url}/bus/messages"
        params: Dict[str, Any] = {"channel": channel, "limit": limit}
        if since_id:
            params["since_id"] = since_id

        _log.debug(
            "GET messages: url=%s channel=%s since_id=%s limit=%d",
            url,
            channel,
            since_id,
            limit,
        )

        try:
            resp = requests.get(
                url,
                headers=self._headers(),
                params=params,
                timeout=self.timeout_s,
            )
            resp.raise_for_status()
            messages = resp.json().get("messages", [])
            _log.info(
                "Messages fetched: channel=%s count=%d since_id=%s",
                channel,
                len(messages),
                since_id,
            )
            return messages

        except requests.exceptions.Timeout:
            _log.error(
                "GET timeout: url=%s channel=%s timeout=%ds",
                url,
                channel,
                self.timeout_s,
            )
            raise

        except requests.exceptions.HTTPError as e:
            _log.error(
                "GET HTTP error: url=%s status=%s response=%s",
                url,
                e.response.status_code if e.response else "N/A",
                e.response.text[:200] if e.response else "N/A",
            )
            raise

        except requests.exceptions.RequestException as e:
            _log.error("GET request error: url=%s error=%s", url, e)
            raise

    def enqueue(
        self,
        queue: str,
        sender: str,
        message: Any,
        priority: int = 0,
    ) -> Dict[str, Any]:
        """Enqueue a message onto a work queue.

        The bus treats any message posted to ``/bus/messages`` with a
        non-empty ``queue`` field as a pending queue item that workers can
        claim via :meth:`claim`.
        """
        url = f"{self.base_url}/bus/messages"
        payload = {
            "queue": queue,
            "sender": sender,
            "message": message,
            "priority": priority,
        }

        _log.debug(
            "ENQUEUE message: url=%s queue=%s sender=%s priority=%d",
            url,
            queue,
            sender,
            priority,
        )

        try:
            resp = requests.post(
                url,
                headers=self._headers(),
                json=payload,
                timeout=self.timeout_s,
            )
            resp.raise_for_status()
            result = resp.json()
            msg_id = result.get("message", {}).get("id", "unknown")
            _log.info(
                "Message enqueued: queue=%s sender=%s id=%s",
                queue,
                sender,
                msg_id,
            )
            return result

        except requests.exceptions.Timeout:
            _log.error(
                "ENQUEUE timeout: url=%s queue=%s timeout=%ds",
                url,
                queue,
                self.timeout_s,
            )
            raise

        except requests.exceptions.HTTPError as e:
            _log.error(
                "ENQUEUE HTTP error: url=%s status=%s response=%s",
                url,
                e.response.status_code if e.response else "N/A",
                e.response.text[:200] if e.response else "N/A",
            )
            raise

        except requests.exceptions.RequestException as e:
            _log.error("ENQUEUE request error: url=%s error=%s", url, e)
            raise

    def claim(
        self,
        queue: str,
        worker: str,
        lease_seconds: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """Claim the next pending message from a queue.

        Returns the claimed message dict (including ``id`` and ``lease_id``)
        or ``None`` when the queue has no pending messages (HTTP 204).
        """
        url = f"{self.base_url}/bus/queues/claim"
        payload: Dict[str, Any] = {"queue": queue, "worker": worker}
        if lease_seconds is not None:
            payload["lease_seconds"] = lease_seconds

        _log.debug(
            "CLAIM: url=%s queue=%s worker=%s lease_seconds=%s",
            url,
            queue,
            worker,
            lease_seconds,
        )

        try:
            resp = requests.post(
                url,
                headers=self._headers(),
                json=payload,
                timeout=self.timeout_s,
            )
            resp.raise_for_status()
            if resp.status_code == 204:
                _log.debug("Claim empty: queue=%s worker=%s", queue, worker)
                return None
            message = resp.json().get("message")
            _log.info(
                "Message claimed: queue=%s worker=%s id=%s lease_id=%s",
                queue,
                worker,
                message.get("id") if message else None,
                message.get("lease_id") if message else None,
            )
            return message

        except requests.exceptions.Timeout:
            _log.error(
                "CLAIM timeout: url=%s queue=%s timeout=%ds",
                url,
                queue,
                self.timeout_s,
            )
            raise

        except requests.exceptions.HTTPError as e:
            _log.error(
                "CLAIM HTTP error: url=%s status=%s response=%s",
                url,
                e.response.status_code if e.response else "N/A",
                e.response.text[:200] if e.response else "N/A",
            )
            raise

        except requests.exceptions.RequestException as e:
            _log.error("CLAIM request error: url=%s error=%s", url, e)
            raise

    def ack(
        self,
        queue: str,
        worker: str,
        message_id: str,
        lease_id: str,
    ) -> Dict[str, Any]:
        """Acknowledge (complete) a leased message, removing it from the queue."""
        url = f"{self.base_url}/bus/queues/ack"
        payload = {
            "queue": queue,
            "worker": worker,
            "message_id": message_id,
            "lease_id": lease_id,
        }

        _log.debug(
            "ACK: url=%s queue=%s worker=%s message_id=%s lease_id=%s",
            url,
            queue,
            worker,
            message_id,
            lease_id,
        )

        try:
            resp = requests.post(
                url,
                headers=self._headers(),
                json=payload,
                timeout=self.timeout_s,
            )
            resp.raise_for_status()
            result = resp.json()
            _log.info(
                "Message acked: queue=%s worker=%s message_id=%s",
                queue,
                worker,
                message_id,
            )
            return result

        except requests.exceptions.Timeout:
            _log.error(
                "ACK timeout: url=%s queue=%s timeout=%ds",
                url,
                queue,
                self.timeout_s,
            )
            raise

        except requests.exceptions.HTTPError as e:
            _log.error(
                "ACK HTTP error: url=%s status=%s response=%s",
                url,
                e.response.status_code if e.response else "N/A",
                e.response.text[:200] if e.response else "N/A",
            )
            raise

        except requests.exceptions.RequestException as e:
            _log.error("ACK request error: url=%s error=%s", url, e)
            raise

    def nack(
        self,
        queue: str,
        worker: str,
        message_id: str,
        lease_id: str,
        requeue: bool = True,
    ) -> Dict[str, Any]:
        """Negative-acknowledge a leased message.

        With ``requeue=True`` (default) the message is released back to
        pending so another worker can claim it.
        """
        url = f"{self.base_url}/bus/queues/nack"
        payload = {
            "queue": queue,
            "worker": worker,
            "message_id": message_id,
            "lease_id": lease_id,
            "requeue": requeue,
        }

        _log.debug(
            "NACK: url=%s queue=%s worker=%s message_id=%s lease_id=%s requeue=%s",
            url,
            queue,
            worker,
            message_id,
            lease_id,
            requeue,
        )

        try:
            resp = requests.post(
                url,
                headers=self._headers(),
                json=payload,
                timeout=self.timeout_s,
            )
            resp.raise_for_status()
            result = resp.json()
            _log.info(
                "Message nacked: queue=%s worker=%s message_id=%s requeue=%s",
                queue,
                worker,
                message_id,
                requeue,
            )
            return result

        except requests.exceptions.Timeout:
            _log.error(
                "NACK timeout: url=%s queue=%s timeout=%ds",
                url,
                queue,
                self.timeout_s,
            )
            raise

        except requests.exceptions.HTTPError as e:
            _log.error(
                "NACK HTTP error: url=%s status=%s response=%s",
                url,
                e.response.status_code if e.response else "N/A",
                e.response.text[:200] if e.response else "N/A",
            )
            raise

        except requests.exceptions.RequestException as e:
            _log.error("NACK request error: url=%s error=%s", url, e)
            raise

    def health_check(self) -> bool:
        """Check if the bus is healthy."""
        url = f"{self.base_url}/health"
        _log.debug("Health check: url=%s", url)

        try:
            resp = requests.get(url, timeout=self.timeout_s)
            healthy = resp.status_code == 200
            if healthy:
                _log.debug("Bus healthy: url=%s", self.base_url)
            else:
                _log.warning(
                    "Bus unhealthy: url=%s status=%d",
                    self.base_url,
                    resp.status_code,
                )
            return healthy

        except requests.exceptions.RequestException as e:
            _log.error("Health check failed: url=%s error=%s", url, e)
            return False
