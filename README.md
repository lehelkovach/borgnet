# BorgNet

**BorgNet — Distributed Adaptive Memetic Hive for Goal‑Directed Agents**

## What it is
BorgNet is a research‑oriented framework for building distributed, goal‑directed
agent swarms that adapt over time, propagate successful strategies (memes), and
remain resilient under failure or adversarial conditions.

## Why it exists
Centralized orchestration struggles with scale, resilience, and heterogeneous
tools. BorgNet explores a hybrid hierarchical‑mesh model where global objectives
are decomposed into subgoals and executed by a self‑organizing swarm.

## How it works (high level)
- A **control plane** maintains the global goal DAG and resource budgets.
- An **agent mesh** bids on subgoals and self‑assigns via leases.
- A **stigmergic demand map** signals where attention is needed.
- **Memetic adaptation** spreads successful strategies across agents.
- **Resilience policies** requeue tasks and isolate suspicious nodes.

## Goal Requirements
- Global objective defined as a DAG of subgoals
- Clear success metrics (throughput, uptime, resilience)
- Resource budgets (compute, spawn count, time)
- Safety constraints (auth, approval thresholds)
- Progress visibility (state + audit trail)
- Failover rules (requeue, redundancy, timeout)

## Implementation Patterns
- Goal DAG + leases for task ownership
- Contract‑net bidding for delegation
- Quorum approvals for high‑impact actions
- Stigmergic demand map for dynamic task selection
- Memetic propagation of successful strategies
- CTDE RL (central training, decentralized execution)
- Anomaly detection + trust scoring for resilience
- Spawn budgets + TTL for controlled growth

## Solutions It Provides
- Scales coordination without centralized bottlenecks
- Survives node failures through leases and redundancy
- Adaptive specialization based on workload and performance
- Secure goal propagation with provenance and quorum checks
- Controlled growth to prevent runaway resource use
- Faster recovery via self‑healing requeue mechanisms
- Distributed planning across heterogeneous tools/resources
- Auditable decision trail for accountability and debugging

## Current Modules
- **Simulation** (`borgnet/sim.py`) — task leasing, requeue, agent loop
- **Metrics** (`borgnet/metrics.py`) — throughput, failure, resilience tracking
- **Stigmergy** (`borgnet/stigmergy.py`) — demand map for decentralized task selection
- **Memetic** (`borgnet/memetic.py`) — strategy pool with evolution and propagation
- **Security** (`borgnet/security.py`) — signed envelopes, quorum voting, trust scoring
- **Models** (`borgnet/models.py`) — Pydantic message/task/presence schemas
- **Transport** (`borgnet/transport/iac_bus.py`) — IAC Bus HTTP adapter

## Tests
- 64 unit and integration tests
- Run with `pytest -v`
- Live transport tests require running IAC bus (`BUS_URL` env var)

## Quick Start
```bash
# Clone
git clone https://github.com/lehelkovach/borgnet.git
cd borgnet

# Create venv and install deps
python3 -m venv .venv
./.venv/bin/pip install pydantic requests networkx pytest pytest-cov

# Run tests
./.venv/bin/pytest -v
```

## Repository Docs
- `docs/DEV_PLAN.md` — roadmap and milestones
- `docs/PROTOCOL.md` — message envelope and performatives
- `docs/THREAT_MODEL.md` — adversarial assumptions and mitigations
- `docs/REFERENCES.md` — benign systems and protocols to adapt
