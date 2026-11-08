# Threat Model (Draft)

## Assumptions
- Agents may fail or be compromised.
- Messages can be forged without signatures.
- Network partitions can occur.
- By default all agents share one signing secret, so a compromised agent can
  sign as any other agent. Per-origin keys remove that, but the verifier
  still holds every key.

## Threats
- Forged goal commands
- Tampering with a signed envelope's payload, provenance, or expiry
- Replay or delay attacks on tasks
- Sabotage or corrupted outputs
- Sybil votes: made-up voter ids pushing a quorum decision
- Strategy poisoning: an agent spreads a bad strategy by inflating the
  fitness it reports
- Stale workers completing or dropping tasks after losing their lease
- Insiders taking over other agents' leases or completing their tasks
- Strategy laundering: honest agents passing on a poisoned strategy they
  adopted, so it spreads with their trust instead of the attacker's
- Uncontrolled replication: agents creating agents without authorization
- Resource exhaustion via uncontrolled spawning

## Mitigations

| Mitigation | Threats addressed | Status |
|---|---|---|
| HMAC signature over the full envelope (`SignedEnvelope`) | Forgery, tampering | Implemented. Optional per-origin keys; asymmetric signatures are roadmap item 4. |
| Expiry, maximum age, and nonce replay rejection (`EnvelopeVerifier`) | Replay, delay | Implemented. Nonce memory is bounded with a maximum age, but lives in memory, so protection resets on restart. |
| Chain of custody on goals | Forgery, provenance | Field exists and is signed. Nothing appends to or checks it yet. |
| Quorum approval with a voter roster (`QuorumManager`) | Forged high-impact actions, Sybil votes | Implemented. Without a roster only the vote count is capped. Votes are not signed yet. |
| Trust scores and quarantine (`TrustRegistry`) | Sabotage, corrupted outputs | Implemented. Refused rule-breaking calls count as anomalies in the scenario harness. Task failure lowers trust just like misbehavior, so about one honest agent in a hundred gets quarantined (see `EVALUATION.md`). |
| Leases with expiry and owner checks (`Simulation`, bus queues) | Failed agents, stale workers | Implemented. |
| Lease authority rules in `Simulation.assign_task` | Insider lease theft, quarantined agents working | Implemented. Only queued tasks, only members, never retired or quarantined agents. 0 of 76,343 insider rule-breaking calls accepted in the scenario suite. |
| Trust-gated strategy adoption with a fitness cap (`PeerExchange`) | Strategy poisoning, laundering | Implemented. Untrusted and quarantined senders are ignored, and adopted fitness is discounted and capped at the receiver's best. Senders are not yet penalized when a shared strategy does badly. |
| Heartbeats and presence TTL | Silent failures, partitions | Implemented in the simulation. Not yet carried over the bus (roadmap item 3). |
| Signed spawn authorization and budgets (`SpawnController`) | Uncontrolled replication, resource exhaustion | Implemented. Single-use, expiring control-plane authorization; population, per-parent, depth, and lifetime limits; an audit for agents that bypassed it. 0 of 16,007 forged or replayed authorizations accepted in the scenario suite. |
| Partition handling | Network partitions | Not started. Leases recover work after a partition heals, but there is no split-brain protection. |
