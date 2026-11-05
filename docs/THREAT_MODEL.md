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
- Resource exhaustion via uncontrolled spawning

## Mitigations

| Mitigation | Threats addressed | Status |
|---|---|---|
| HMAC signature over the full envelope (`SignedEnvelope`) | Forgery, tampering | Implemented. Optional per-origin keys; asymmetric signatures are roadmap item 4. |
| Expiry, maximum age, and nonce replay rejection (`EnvelopeVerifier`) | Replay, delay | Implemented. Nonce memory is bounded with a maximum age, but lives in memory, so protection resets on restart. |
| Chain of custody on goals | Forgery, provenance | Field exists and is signed. Nothing appends to or checks it yet. |
| Quorum approval with a voter roster (`QuorumManager`) | Forged high-impact actions, Sybil votes | Implemented. Without a roster only the vote count is capped. Votes are not signed yet. |
| Trust scores and quarantine (`TrustRegistry`) | Sabotage, corrupted outputs | Implemented. Anomaly detection that feeds it is not built. |
| Leases with expiry and owner checks (`Simulation`, bus queues) | Failed agents, stale workers | Implemented. |
| Trust-gated strategy adoption (`PeerExchange`) | Strategy poisoning | Implemented. Untrusted and quarantined senders are ignored and adopted fitness is discounted. Senders are not yet penalized when a shared strategy does badly. |
| Heartbeats and presence TTL | Silent failures, partitions | Implemented in the simulation. Not yet carried over the bus (roadmap item 3). |
| Spawn budgets and TTL for new agents | Resource exhaustion | Not started (roadmap item 5). |
| Partition handling | Network partitions | Not started. Leases recover work after a partition heals, but there is no split-brain protection. |
