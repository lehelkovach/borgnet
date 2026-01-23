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
