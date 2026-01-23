# BorgNet

Goal Requirements
- Global objective defined as a DAG of subgoals
- Clear success metrics (throughput, uptime, resilience)
- Resource budgets (compute, spawn count, time)
- Safety constraints (auth, approval thresholds)
- Progress visibility (state + audit trail)
- Failover rules (requeue, redundancy, timeout)

Implementation Patterns
- Goal DAG + leases for task ownership
- Contract-net bidding for delegation
- Quorum approvals for high-impact actions
- Stigmergic demand map for dynamic task selection
- Memetic propagation of successful strategies
- CTDE RL (central training, decentralized execution)
- Anomaly detection + trust scoring for resilience
- Spawn budgets + TTL for controlled growth

Solutions It Provides
- Scales coordination without centralized bottlenecks
- Survives node failures through leases and redundancy
- Adaptive specialization based on workload and performance
- Secure goal propagation with provenance and quorum checks
- Controlled growth to prevent runaway resource use
- Faster recovery via self-healing requeue mechanisms
- Distributed planning across heterogeneous tools/resources
- Auditable decision trail for accountability and debugging

Top 3 Focus Areas
- Simulation engine (agent loop, leases, demand map)
- IAC bus adapter (HTTP transport)
- Metrics and evaluation hooks
