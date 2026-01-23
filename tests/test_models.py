from datetime import datetime, timezone

from borgnet.models import MessageEnvelope, PresencePayload, TaskPayload


def test_message_envelope_defaults():
    msg = MessageEnvelope(
        id="msg-1",
        ts=datetime.now(timezone.utc),
        performative="inform",
        sender="agent-a",
        conversation_id="conv-1",
        payload={"ok": True},
    )
    assert msg.priority == "normal"
    assert msg.payload["ok"] is True


def test_task_payload_fields():
    task = TaskPayload(
        task_id="task-1",
        task_type="deploy",
        resource={"kind": "repo", "id": "borgnet"},
    )
    assert task.task_type == "deploy"


def test_presence_payload():
    presence = PresencePayload(agent_id="agent-a", role="worker", ttl_ms=30000)
    assert presence.ttl_ms == 30000
