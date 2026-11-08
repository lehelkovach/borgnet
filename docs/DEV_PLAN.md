# BorgNet Dev Plan

Purpose: research and prototype a goal-directed memetic agent hive with
distributed coordination, adaptive specialization, and resilience against
node failure and adversarial behavior.

## Scope
- Research protocol and architecture for a hierarchical mesh agent swarm.
- Build a simulator and baseline transport adapter (IAC Bus initially).
- Provide a message schema for goals, tasks, and leases.
- Include safety constraints: auth, provenance, and quorum for critical actions.

## Milestones

Status values: **Done**, **Partial**, **Not started**.

### 1) Project scaffold — Partial
| Item | Status | Notes |
|---|---|---|
| Python project with Poetry and pytest | Done | `npm test` runs pytest in OCI containers on Python 3.10–3.13; an opt-in pre-push hook runs it on every push |
| Core data models: task, lease, presence | Done | `sim.py`, `models.py` |
| Goal DAG model | Not started | `networkx` is declared for this but not used yet |
| Docs: protocol spec, threat model, evaluation metrics | Done | Drafts; see status notes in each doc |

### 2) Simulation core — Partial
| Item | Status | Notes |
|---|---|---|
| Agent loop with local policies | Done | Single agent, `agent.py` (roadmap item 1) |
| Goal bidding | Not started | Roadmap item 6 |
| Task lease handling and requeue | Done | `sim.py` |
| Stigmergic demand map | Done | `stigmergy.py`, with evaporation |
| Memetic strategy pool | Done | `memetic.py` |
| Strategy propagation between agents | Done | In-process, trust-gated, `propagation.py` (roadmap item 2) |

### 3) Resilience and adversarial tests — Partial
| Item | Status | Notes |
|---|---|---|
| Node failure injection | Done | Worker death in agent tests; kill-recovery demo, offline and live |
| Failure detection by heartbeat | Done | Simulation presence TTL (roadmap item 7) |
| Malicious or corrupted agent simulation | Done | Scripted insiders in `scenarios.py` |
| Metrics: task completion | Done | `metrics.py` |
| Metrics: recovery time, anomaly false-positive rate | Done | Reported per run; see `EVALUATION.md` |

### 4) Transport adapters — Partial
| Item | Status | Notes |
|---|---|---|
| IAC Bus adapter over HTTP | Done | Messages plus queue leasing |
| NATS or Redis Streams adapters | Not started | Roadmap item 9 |

The original top three priorities were the simulation engine, the IAC Bus
adapter, and metrics hooks. All three are done.

## Roadmap

Numbered so code and commits can refer to items. Items are roughly in order.

1. **Single-agent worker loop.** Done. One agent selects work from the demand
   map, claims a lease, runs a pluggable worker, and reports to trust and the
   strategy pool. See `borgnet/agent.py`.
2. **Peer-to-peer strategy transmission.** Done, in-process. Agents keep
   their own pools and share through a trust-gated `PeerExchange`; adopted
   strategies start with discounted fitness. See `borgnet/propagation.py`.
   Carrying offers over the bus is part of item 3.
3. **Wire the protocol through the transport.** Not started. Send
   `MessageEnvelope` and `SignedEnvelope` over the bus instead of plain
   strings, validate performatives and priorities against the spec, and carry
   heartbeats and strategy offers between processes.
4. **Stronger signing.** Partial. Done: per-origin HMAC keys, a maximum
   envelope age, and a nonce store that forgets nonces once replays would
   fail anyway. Remaining: asymmetric signatures, signed quorum votes, and a
   persistent nonce store.
5. **Goal DAG and control plane.** Partial. Done: spawn budgets with signed
   control-plane authorization and child lifetimes, in `borgnet/spawn.py`.
   Remaining: the global goal as a DAG of subgoals with `networkx`, and
   resource budgets.
6. **Contract-net bidding.** Not started. Request, propose, and agree flow
   for delegating subgoals.
7. **Heartbeats and presence.** Done in the simulation. Agents that miss
   their heartbeats are dropped and their tasks requeued before leases
   expire. See `Simulation(presence_ttl=...)`. Heartbeats over the bus are
   part of item 3.
8. **Scenario suites and evaluation.** Done for a single process.
   `borgnet/scenarios.py` runs node loss, coordinator outage, insiders, and
   authorized respawn under stigmergy and a central queue, and
   `docs/EVALUATION.md` reports the results. Remaining: partitions and
   message loss, which need item 3, and adaptive adversaries.
9. **NATS or Redis Streams transport.** Not started.
10. **Optional reinforcement learning loop** with central training and
    decentralized execution. Not started.

## Architecture Notes
- Control plane: global goal DAG, resource budgets, spawn limits.
- Agent mesh: local decision rules, role shifts, gossip presence.
- Protocol: performatives (request, propose, agree, inform, confirm).
- Module-level detail for what exists today is in `docs/ARCHITECTURE.md`.

## Dependencies
- networkx: reserved for the goal DAG (roadmap item 5); not imported yet.
- pydantic: data models and validation.
- requests: IAC Bus HTTP adapter.
- pytest and pytest-cov: tests.

## Safety and Governance
| Control | Status |
|---|---|
| Signed goal envelopes and chain of custody | Done; one shared key or per-origin keys |
| Replay rejection by nonce | Done; bounded with a maximum age, in memory only |
| Quorum approval for critical actions | Done, with optional voter roster |
| Lease and heartbeat timeouts for self-healing | Done in the simulation |
| Spawn budgets to prevent uncontrolled growth | Done; signed authorization, population, per-parent, depth, and lifetime limits |

## Reference Systems to Adapt (benign)
- NATS or Redis Streams for message transport.
- libp2p for mesh networking concepts.
- etcd or Consul for leases and leader election concepts.
- Temporal for durable workflow concepts.

## Evaluation Metrics
| Metric | Measured today |
|---|---|
| Throughput (tasks per minute) | Yes, tasks per tick in the scenario suite |
| Resilience (time to recover from node loss) | Yes, ticks to reclaim orphaned work and recovery rate |
| Stability (variance in completion rates) | No |
| Security (false positive and false negative rate for anomalies) | Yes, honest agents and insiders quarantined per run |
