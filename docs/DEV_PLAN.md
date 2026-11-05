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
| Python project with Poetry and pytest | Done | CI runs pytest on Python 3.10–3.13 |
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
| Strategy propagation between agents | Not started | Roadmap item 2 |

### 3) Resilience and adversarial tests — Partial
| Item | Status | Notes |
|---|---|---|
| Node failure injection | Done | Worker death in agent tests; kill-recovery demo, offline and live |
| Malicious or corrupted agent simulation | Not started | Trust and quarantine are unit-tested only |
| Metrics: task completion | Done | `metrics.py` |
| Metrics: recovery time, anomaly false-positive rate | Not started | Roadmap item 8 |

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
2. **Peer-to-peer strategy transmission.** Not started. A trust-gated
   horizontal channel through which agents share and adopt strategies, so
   memes spread between agents and not only within one pool.
3. **Wire the protocol through the transport.** Not started. Send
   `MessageEnvelope` and `SignedEnvelope` over the bus instead of plain
   strings, and validate performatives and priorities against the spec.
4. **Stronger signing.** Not started. Per-agent signing keys, signed quorum
   votes, and a persistent nonce store that prunes expired nonces.
5. **Goal DAG and control plane.** Not started. Global goal decomposed into a
   DAG of subgoals with `networkx`, plus resource and spawn budgets.
6. **Contract-net bidding.** Not started. Request, propose, and agree flow
   for delegating subgoals.
7. **Heartbeats and presence.** Not started. Agents announce presence with a
   TTL so peers can detect failures.
8. **Scenario suites and evaluation.** Not started. Multi-agent runs with node
   loss, partitions, malicious agents, and backlog spikes. Measure recovery
   time, throughput, and anomaly false-positive rate, and compare stigmergic
   task selection with a central queue.
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
| Signed goal envelopes and chain of custody | Done, shared secret only |
| Replay rejection by nonce | Done, in-memory only |
| Quorum approval for critical actions | Done, with optional voter roster |
| Lease and heartbeat timeouts for self-healing | Leases done; heartbeats not started |
| Spawn budgets to prevent uncontrolled growth | Not started |

## Reference Systems to Adapt (benign)
- NATS or Redis Streams for message transport.
- libp2p for mesh networking concepts.
- etcd or Consul for leases and leader election concepts.
- Temporal for durable workflow concepts.

## Evaluation Metrics
| Metric | Measured today |
|---|---|
| Throughput (tasks per minute) | Counts only; no rate yet |
| Resilience (time to recover from node loss) | No; the demo reports elapsed time only |
| Stability (variance in completion rates) | No |
| Security (false positive and false negative rate for anomalies) | No |
