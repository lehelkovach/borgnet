from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class MessageEnvelope(BaseModel):
    id: str
    ts: datetime
    performative: str
    sender: str
    receiver: Optional[str] = None
    conversation_id: str
    in_reply_to: Optional[str] = None
    ttl_ms: Optional[int] = None
    priority: str = "normal"
    payload: Dict[str, Any] = Field(default_factory=dict)


class TaskPayload(BaseModel):
    task_id: str
    task_type: str
    resource: Dict[str, str]
    requirements: Dict[str, Any] = Field(default_factory=dict)
    constraints: Dict[str, Any] = Field(default_factory=dict)
    inputs: Dict[str, Any] = Field(default_factory=dict)


class PresencePayload(BaseModel):
    agent_id: str
    role: str
    capabilities: list[str] = Field(default_factory=list)
    ttl_ms: int
    supervisor_id: Optional[str] = None
    scope: Optional[str] = None
