# Threat Model (Draft)

## Assumptions
- Agents may fail or be compromised.
- Messages can be forged without signatures.
- Network partitions can occur.

## Threats
- Forged goal commands
- Sabotage or corrupted outputs
- Resource exhaustion via uncontrolled spawning
- Replay or delay attacks on tasks

## Mitigations
- Signed envelopes and chain of custody
- Quorum approvals for critical actions
- Leases and heartbeats for task ownership
- Spawn budgets and TTL for new agents
