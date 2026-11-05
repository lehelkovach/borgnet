# BorgNet Protocol (Draft)

## Envelope
All messages use a common envelope:

{
  "id": "msg-uuid",
  "ts": "ISO-8601",
  "performative": "request|propose|agree|inform|confirm|cancel|heartbeat",
  "sender": "agent-id",
  "receiver": "agent-id|role:supervisor|group:cluster|broadcast",
  "conversation_id": "conv-uuid",
  "in_reply_to": "msg-uuid",
  "ttl_ms": 60000,
  "priority": "low|normal|high|critical",
  "payload": {}
}

## Task Delegation
- request: supervisor announces subgoal or task
- propose: agent bids or estimates
- agree: supervisor assigns lease
- inform: progress update
- confirm: completion or failure

## Presence
Heartbeat payload includes:
- agent_id
- role
- capabilities
- ttl_ms

## Leases
Tasks must include:
- task_id
- lease_id
- lease_ttl_ms

## Channels (optional)
- presence
- delegation
- ops
- alerts

## Implementation status

This spec is a draft and the code follows only part of it. Wiring it through
the transport is roadmap item 3 in `DEV_PLAN.md`.

| Spec element | In code | Gap |
|---|---|---|
| Envelope fields | `models.MessageEnvelope` | `performative` and `priority` accept any string instead of the listed values. `receiver` is optional. |
| Signing and provenance | `security.SignedEnvelope` | A separate type from `MessageEnvelope`. It signs goal id, origin, parent goal, chain of custody, nonce, issue time, expiry, and payload. |
| Task delegation performatives | None | No request, propose, agree, inform, or confirm flow exists yet (roadmap item 6). |
| Presence heartbeats | `models.PresencePayload` | Schema only; nothing sends or reads heartbeats (roadmap item 7). |
| Lease fields | `sim.Task` | Has an owner and `lease_ttl` in seconds. There is no `lease_id` and no `lease_ttl_ms`. Bus queue leases do carry a `lease_id`. |
| Channels | IAC Bus channels and queues | The demo uses one work queue and one results channel. The named channels above are not used. |

No module sends `MessageEnvelope` today. The transport sends plain strings on
channels and JSON-compatible values on queues.
