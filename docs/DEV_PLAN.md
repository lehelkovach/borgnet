# BorgNet Dev Plan

Purpose: research and prototype a goal directed memetic agent hive with
distributed coordination, adaptive specialization, and resilience against
node failure and adversarial behavior.

## Scope
- Research protocol and architecture for a hierarchical mesh agent swarm.
- Build a simulator and baseline transport adapter (IAC Bus initially).
- Provide a message schema for goals, tasks, and leases.
- Include safety constraints: auth, provenance, and quorum for critical actions.

## Milestones
1) Project scaffold
   - Python project with Poetry, pytest, and networkx.
   - Core data models (goal DAG, task, lease, presence).
   - Docs: protocol spec, threat model, and evaluation metrics.

2) Simulation core
   - Agent loop with local policies and goal bidding.
   - Task lease handling and requeue logic.
   - Stigmergic demand map and memetic strategy propagation.

3) Resilience and adversarial tests
   - Node failure injection.
   - Malicious or corrupted agent simulation.
   - Metrics: task completion, recovery time, false positive rate.

4) Transport adapters
   - IAC Bus adapter (HTTP).
   - Optional adapters: NATS or Redis Streams.

## Top 3 Implementation Priorities
1) Simulation engine (task leases, requeue, demand map stubs).
2) IAC bus transport adapter for messaging.
3) Metrics and evaluation hooks for resilience and throughput.

## Architecture Notes
- Control plane: global goal DAG, resource budgets, spawn limits.
- Agent mesh: local decision rules, role shifts, gossip presence.
- Protocol: performatives (request, propose, agree, inform, confirm).

## Initial Dependencies
- networkx: goal DAG and graph analysis.
- pydantic: data models and validation.
- pytest: tests.
- requests: optional HTTP adapter.

## Safety and Governance
- Signed goal envelopes and chain of custody.
- Quorum approval for critical actions.
- Lease and heartbeat timeouts for self healing.
- Spawn budgets to prevent uncontrolled growth.

## Reference Systems to Adapt (benign)
- NATS or Redis Streams for message transport.
- libp2p for mesh networking concepts.
- etcd or Consul for leases and leader election concepts.
- Temporal for durable workflow concepts.

## Evaluation Metrics
- Throughput (tasks per minute).
- Resilience (time to recover from node loss).
- Stability (variance in completion rates).
- Security (false positive and false negative rate for anomalies).
