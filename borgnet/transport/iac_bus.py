from __future__ import annotations

from typing import Any, Dict, List, Optional

import requests


class IacBusClient:
    def __init__(self, base_url: str, token: str | None = None, timeout_s: int = 10):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout_s = timeout_s

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def post_message(self, channel: str, sender: str, message: str) -> Dict[str, Any]:
        resp = requests.post(
            f"{self.base_url}/bus/messages",
            headers=self._headers(),
            json={"channel": channel, "sender": sender, "message": message},
            timeout=self.timeout_s,
        )
        resp.raise_for_status()
        return resp.json()

    def get_messages(
        self,
        channel: str,
        since_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        params = {"channel": channel, "limit": limit}
        if since_id:
            params["since_id"] = since_id
        resp = requests.get(
            f"{self.base_url}/bus/messages",
            headers=self._headers(),
            params=params,
            timeout=self.timeout_s,
        )
        resp.raise_for_status()
        return resp.json().get("messages", [])
