# BorgNet

BorgNet is a research prototype for coordinating a swarm of goal-directed
agents without a central scheduler. Agents pick work through a shared demand
signal (stigmergy), hold tasks under expiring leases so a dead agent's work is
recovered, spread successful strategies through an evolving pool (memetics),
and are scored for trust so misbehaving agents can be quarantined.

It is early-stage research code. Some parts of the design below are
implemented and tested; others are still plans. The status table says which
is which.

## Status

| Capability | Status | Where |
|---|---|---|
| Task leases, expiry, and requeue in a simulated clock | Implemented | `borgnet/sim.py` |
| Single-agent loop: select, claim, execute, report | Implemented | `borgnet/agent.py` |
| Stigmergic demand map with deposit and evaporation | Implemented | `borgnet/stigmergy.py` |
| Strategy pool with fitness, selection, mutation, evolution | Implemented | `borgnet/memetic.py` |
| HMAC-signed envelopes over the full envelope, expiry, replay rejection | Implemented, shared secret only | `borgnet/security.py` |
| N-of-M quorum voting with optional voter roster | Implemented | `borgnet/security.py` |
| Trust scores and quarantine | Implemented | `borgnet/security.py` |
| Throughput and failure counters | Implemented | `borgnet/metrics.py` |
| IAC Bus HTTP client: messages and queue leasing | Implemented | `borgnet/transport/iac_bus.py` |
| Master/workers kill-recovery demo over a live bus | Implemented, needs an IAC Bus with queue endpoints | `borgnet/demo/` |
| Message envelope schemas | Defined, not yet used by other modules | `borgnet/models.py` |
| Peer-to-peer strategy transmission between agents | Planned | roadmap item 2 |
| Goal DAG and control plane | Planned | roadmap |
| Contract-net bidding for delegation | Planned | roadmap |
| Heartbeats and presence | Planned | roadmap |
| Spawn budgets and agent TTL | Planned | roadmap |
| Per-agent signing keys | Planned | roadmap |
| NATS or Redis Streams transport | Planned | roadmap |
| Reinforcement learning (central training, decentralized execution) | Planned | roadmap |

The roadmap lives in [`docs/DEV_PLAN.md`](docs/DEV_PLAN.md).

## Quick start

```bash
git clone https://github.com/lehelkovach/borgnet.git
cd borgnet

python3 -m venv .venv
./.venv/bin/pip install -e . pytest pytest-cov

./.venv/bin/pytest
```

BorgNet needs Python 3.10 or newer. CI tests 3.10 through 3.13.

### Run one agent in-process

```python
from borgnet import (
    Agent, AgentRunner, DemandMap, Simulation, Strategy, StrategyPool,
    StubWorker, Task, TrustRegistry,
)

sim = Simulation()
agent = Agent(agent_id="a1")
sim.add_agent(agent)
for i in range(3):
    sim.add_task(Task(task_id=f"t{i}", task_type="build", lease_ttl=30))

pool = StrategyPool()
pool.add_strategy(Strategy(params={"temperature": 1.0}))

runner = AgentRunner(agent, sim, pool, DemandMap(), TrustRegistry(), StubWorker())
for step in runner.run():
    print(step.outcome, step.task_id)
print(sim.metrics.summary())
```

`StubWorker` returns a fixed fitness. A real backend implements the `Worker`
protocol in `borgnet/agent.py` and is passed in the same way.

### Kill-recovery demo over a live IAC Bus

The demo enqueues tasks, starts several workers, and kills one right after it
claims a task. It succeeds only if every task completes exactly once and a
surviving worker finishes the killed worker's task after its lease expires.

```bash
./.venv/bin/python scripts/demo_master_workers.py \
  --bus-url http://127.0.0.1:8091 --token devtoken \
  --tasks 8 --workers 3 --lease-seconds 5
```

This needs an IAC Bus that serves the queue endpoints
`/bus/queues/claim`, `/bus/queues/ack`, and `/bus/queues/nack`. The same demo
logic also runs offline against an in-memory fake bus in
`tests/test_demo_offline.py`.

## Tests and CI

`pytest` runs everything. Live bus tests skip themselves unless an IAC Bus
answers at `BUS_URL` (default `http://127.0.0.1:8091`), with an optional
`BUS_API_TOKEN`.

CI runs in OCI containers, not on GitHub. `scripts/ci.sh` builds one test
image per Python version from `Containerfile` and runs the suite in each. It
works with Podman or Docker and exits non-zero if any version fails.

```bash
scripts/ci.sh local    # build the images and run the tests on this machine
scripts/ci.sh build    # build only, and push when REGISTRY is set
scripts/ci.sh nomad    # build, push, run on Nomad, wait, and print the logs
```

On Nomad, [`deploy/nomad/borgnet-ci.nomad.hcl`](deploy/nomad/borgnet-ci.nomad.hcl)
is a parameterized batch job with one task group per Python version. The
script registers it, dispatches a run tagged with the current git commit,
waits for every group, and prints each group's test output. Failed runs are
not retried.

The Nomad clients need the `docker` or `podman` driver and must be able to get
the images. Set `REGISTRY` to push them to a registry the clients can pull
from, or leave it unset when the clients share the build machine's container
engine.

```bash
REGISTRY=registry.service.consul:5000 \
NOMAD_ADDR=http://nomad.service.consul:4646 \
  scripts/ci.sh nomad
```

The top of `scripts/ci.sh` lists every setting, including the Python
versions, the Nomad driver, and an optional bus URL for live tests.

## Documentation

| Doc | What it covers |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Module-by-module reference, the agent step cycle, lease and quorum rules, and why the design uses stigmergy |
| [`docs/DEV_PLAN.md`](docs/DEV_PLAN.md) | Milestones with status and the numbered roadmap |
| [`docs/PROTOCOL.md`](docs/PROTOCOL.md) | Draft message envelope and performatives, and how far the code follows it |
| [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md) | Adversarial assumptions, threats, and the status of each mitigation |
| [`docs/REFERENCES.md`](docs/REFERENCES.md) | Benign systems and protocols the design borrows from |

## Design goals

These describe where the project is heading. See the status table for what
exists today.

- A control plane holds the global goal as a DAG of subgoals, with resource
  budgets and spawn limits.
- An agent mesh bids on subgoals and self-assigns work through leases.
- A stigmergic demand map signals where attention is needed.
- Memetic adaptation spreads successful strategies across agents.
- Resilience policies requeue work from failed agents and isolate suspicious
  ones.
- High-impact actions need quorum approval, and every goal carries signed
  provenance.
