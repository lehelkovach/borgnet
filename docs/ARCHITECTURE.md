# BorgNet Architecture

This is a reference for the code as it exists today. Planned work is in
[`DEV_PLAN.md`](DEV_PLAN.md), and the README's status table summarizes both.

## Package layout

```
borgnet/
  sim.py               Tasks, agents, leases, and a simulated clock
  agent.py             AgentRunner: one agent's select/claim/execute/report loop
  stigmergy.py         DemandMap: shared demand signal with evaporation
  memetic.py           Strategy and StrategyPool: fitness, selection, evolution
  propagation.py       PeerExchange: trust-gated strategy sharing between agents
  security.py          SignedEnvelope, EnvelopeVerifier, QuorumManager, trust
  metrics.py           Counters and summaries
  models.py            Pydantic schemas for the draft protocol (not yet wired in)
  logging.py           Logger naming and configuration
  transport/iac_bus.py IacBusClient: HTTP client for the IAC Bus
  demo/master_worker.py  Master/workers kill-recovery demo over the bus
scripts/
  demo_master_workers.py  CLI for the demo
  ci.sh                   Container CI: build test images and run them
Containerfile           OCI test image, one per Python version
package.json            npm scripts that run CI; no npm dependencies
.githooks/pre-push      Opt-in hook that runs `npm test` before every push
```

Every module logs through `borgnet.logging.get_logger("<module>")`, which
returns a logger named `borgnet.<module>`. Call `configure_logging("DEBUG")` to
see them.

## Simulation and leases (`sim.py`)

A `Simulation` holds tasks and agents and keeps its own integer clock,
`now`, advanced by `tick(seconds)`.

A `Task` moves through these states:

```
queued --assign_task--> running --complete_task--> done | failed
                           |
                           +--lease expiry in tick() or requeue_task()--> queued
```

- `assign_task(task_id, agent_id)` sets the owner and a lease that expires at
  `now + lease_ttl`.
- `tick()` returns every running task whose lease has expired to the queue and
  counts it as reassigned.
- `complete_task(task_id, success, agent_id=None)` and
  `requeue_task(task_id, agent_id=None)` act only on running tasks. If
  `agent_id` is given it must be the current lease owner. Both return `False`
  and change nothing otherwise, so a stale worker cannot finish or drop a task
  that was re-assigned, and no task is counted twice.

### Presence

`Simulation(presence_ttl=N)` expects every agent to call `heartbeat(agent_id)`
at least once every `N` seconds of simulated time.

- On each `tick()`, an agent silent for more than `N` seconds is dropped. Its
  running tasks go back to the queue at once, without waiting for their
  leases, and `metrics.lost_agents` counts it.
- A dropped agent is no longer a member. `heartbeat()` returns `False` for it
  until it is added again.
- Without `presence_ttl`, agents are never dropped.

## Agent loop (`agent.py`)

`AgentRunner` drives one agent against a shared `Simulation`, `DemandMap`,
and `TrustRegistry`, plus a `StrategyPool`. The pool can be shared, or each
agent can keep its own and exchange strategies through a `PeerExchange`.
Runners coordinate only through the demand map, the leases, and that
exchange.

Each `step()` does the following:

1. If the agent is quarantined, stop with outcome `quarantined`. A
   quarantined agent therefore stops sending heartbeats.
2. Send a heartbeat. If the simulation does not know the agent, because it
   was dropped for silence or never added, add it again.
3. Evaporate the demand map, then list the queued tasks the agent can handle.
   An agent with no declared capabilities handles every task type.
4. Deposit demand for each candidate's type, then choose the candidate whose
   type has the highest demand. If there is none, stop with outcome `idle`.
5. Claim the task's lease.
6. Pick a strategy from the pool by fitness-weighted selection, or none if the
   pool is empty.
7. Run the injected `Worker`. It returns a fitness score; raising models a
   worker that dies mid-task.

| Result of step 7 | Outcome | Effect |
|---|---|---|
| Worker raised | `requeued` | Trust failure, strategy fitness 0, demand deposited, task requeued |
| Fitness above `success_threshold` | `completed` | Task done, trust success, strategy fitness updated |
| Fitness at or below threshold | `failed` | Task failed, trust failure, demand deposited, strategy fitness updated |
| Lease was lost while the worker ran | `lease_lost` | Nothing is credited; the task belongs to whoever holds it now |

`run(max_steps)` repeats `step()` until the agent is idle or quarantined.

The `Worker` protocol is a single method,
`run(task, strategy) -> float`. `StubWorker` is an in-process implementation
for tests. The module makes no network calls itself.

## Stigmergy (`stigmergy.py`)

A `DemandMap` holds one `DemandSignal` per task type.

- `deposit(task_type, amount)` adds intensity, creating the signal if needed.
- `evaporate(elapsed=None)` multiplies every intensity by
  `(1 - decay_rate) ** elapsed` and drops signals below `min_intensity`. With
  no argument, `elapsed` is the wall-clock time since the last evaporation.
- `highest_demand()`, `ranked_demand()`, and `snapshot()` read the map.

The map uses wall-clock time while `Simulation` uses its own clock. That is
fine for the single-process loop, but simulations that jump the clock forward
should pass `elapsed` explicitly.

## Memetic strategies (`memetic.py`)

A `Strategy` is a dictionary of parameters plus a fitness score, a source
agent, and a generation number.

- `clone(agent_id)` copies the parameters into a new generation with fitness 0.
- `mutate(rate)` changes each parameter with probability `rate`. Booleans are
  flipped. Floats are scaled by a random factor between 0.8 and 1.2. Integers
  move by -1, 0, or +1 and never go below 0. Other types are left alone.

A `StrategyPool` holds up to `max_strategies` strategies.

- `update_fitness(id, value)` blends the new value in as an exponential moving
  average, keeping 70% of the old score.
- `select(count)` samples with probability proportional to fitness, shifted so
  the weakest strategy still has weight 1.
- `evolve()` clones and mutates the top `elite_fraction` of strategies, then
  prunes the weakest ones beyond the size limit.
- `diversity()` is the number of distinct source agents divided by the pool
  size.

## Strategy exchange (`propagation.py`)

A `PeerExchange` is the horizontal channel between agents that each keep
their own `StrategyPool`. Agents `join(agent_id, pool)`. `share(agent_id)`
offers that agent's best strategy to every peer, or to `fanout` peers chosen
at random. `gossip_round()` lets every member share once.

Each receiver applies an `AdoptionPolicy` to every offer. It adopts only if
all of these hold:

| Check | Rejection reason |
|---|---|
| The sender is not the receiver | `self` |
| The sender is a member of the exchange | `unknown_sender` |
| The sender is not quarantined | `sender_quarantined` |
| The sender's trust is at least `min_sender_trust`, default 0.8 | `sender_untrusted` |
| The receiver does not already hold the same parameters | `already_known` |
| The offered fitness beats the receiver's best by more than `fitness_margin` | `not_better` |

The sender reports its own fitness, so an adopted strategy starts at the
offered fitness times `prior_weight`, default 0.5. It then has to earn the
rest through the receiver's own results. The adopted copy records the sender
as its source and one more generation. `PeerExchange.outcomes` counts every
decision by reason.

Limits: the exchange is in-process, and a sender is not penalized when a
strategy it shared does badly for the receiver.

## Security (`security.py`)

### Signed envelopes

`SignedEnvelope.compute_signature(secret)` signs a canonical JSON
serialization of every integrity-relevant field with HMAC-SHA256. The signed
fields are goal id, origin id, parent goal id, chain of custody, nonce, issue
time, expiry, and payload. Changing any of them after signing breaks
verification.

`EnvelopeVerifier.verify(envelope)` accepts an envelope only if the
signature is valid, it has not expired, and its nonce has not been seen
before.

- **Keys.** `EnvelopeVerifier(secret)` uses one key for every agent.
  `EnvelopeVerifier(keys={origin_id: key})` gives each origin its own key, so
  an envelope verifies only under the key of the origin it names, and unknown
  origins are rejected.
- **Freshness.** With `max_age_s`, envelopes issued longer ago than that, or
  more than `clock_skew_s` in the future, are rejected.
- **Replay memory.** A nonce is forgotten once its envelope would fail the
  expiry or age check anyway. With `max_age_s` set, memory stays bounded.

Limitations:

- The keys are symmetric HMAC keys. Whoever runs the verifier holds every key
  and could sign as anyone.
- Seen nonces live in memory, so replay protection resets when the process
  restarts.
- Without `max_age_s`, nonces of envelopes with no expiry are kept forever.

### Quorum

`QuorumManager(required_votes, total_voters, voters=None)` approves a proposal
once `required_votes` voters approve it.

- With a `voters` roster, only listed ids may vote and `total_voters` is the
  roster size. Without a roster, any id may vote until `total_voters` distinct
  ids have voted. That caps the count but cannot stop made-up ids, so pass a
  roster for anything that matters.
- A voter may change their vote until the proposal is final.
- `commit()` succeeds once quorum is reached. `reject()` succeeds once quorum
  can no longer be reached. Either decision is final: later votes are ignored
  and the opposite decision is refused.
- Voter ids are plain strings. Votes are not signed yet.

### Trust

Each agent's `TrustScore` starts at 1.0. A success adds 0.1, up to 2.0. A
failure subtracts 0.2 and an anomaly subtracts 0.5, down to 0. The
`TrustRegistry` quarantines an agent whose score falls below 0.3, and
`rehabilitate()` lifts the quarantine.

## Transport (`transport/iac_bus.py`)

`IacBusClient(base_url, token=None, timeout_s=10)` talks to an IAC Bus over
HTTP, sending a bearer token when one is given.

| Method | Request | Returns |
|---|---|---|
| `post_message(channel, sender, message)` | `POST /bus/messages` | Bus response |
| `get_messages(channel, since_id, limit)` | `GET /bus/messages` | List of messages |
| `enqueue(queue, sender, message, priority)` | `POST /bus/messages` with a `queue` field | Bus response |
| `claim(queue, worker, lease_seconds)` | `POST /bus/queues/claim` | Claimed message with `lease_id`, or `None` on HTTP 204 |
| `ack(queue, worker, message_id, lease_id)` | `POST /bus/queues/ack` | Bus response |
| `nack(queue, worker, message_id, lease_id, requeue)` | `POST /bus/queues/nack` | Bus response |
| `health_check()` | `GET /health` | `True` on HTTP 200 |

Every method except `health_check()` logs and re-raises timeouts, HTTP errors,
and other request errors. HTTP error logs include the status code and the
first 200 characters of the response body.

## Kill-recovery demo (`demo/master_worker.py`)

`run_demo()` creates a fresh queue and results channel, then:

1. The `Master` enqueues the tasks.
2. Several `Worker` threads claim, work, ack, and post a completion report.
   Worker 0 starts first and exits right after its first claim without
   acking, which models a crash mid-lease.
3. The master polls the results channel until every task is reported or the
   deadline passes.

Workers survive bus errors. A failed claim is retried, and a failed ack is
treated as a lost lease, so that attempt is not reported. The result reports
`success` only if every task completed exactly once and a survivor completed
the crashed worker's task. It also reports `worker_errors`.

## Models (`models.py`)

`MessageEnvelope`, `TaskPayload`, and `PresencePayload` are Pydantic models for
the draft protocol in [`PROTOCOL.md`](PROTOCOL.md). No other module uses them
yet. The transport sends plain strings and dictionaries, and
`SignedEnvelope` is a separate type.

## Why stigmergy

Stigmergy means agents coordinate indirectly, by reading and changing a shared
signal, instead of messaging each other or waiting for a scheduler to assign
work. Ant colonies do this with pheromone trails. In BorgNet the signal is
the demand map.

Reasons it fits this design:

- **No central scheduler.** Any agent can choose work by reading the map, so
  there is no assignment service to fail or to become a bottleneck.
- **Coordination cost stays flat.** Each agent reads and writes one map
  instead of negotiating with every peer.
- **It corrects itself.** Unmet demand keeps being reinforced, including by
  failed attempts. Finished work stops being reinforced and evaporates.
- **It degrades gracefully.** If agents disappear, their signals and leased
  tasks remain for the others.
- **It pairs with leases.** The map says where work is needed, and the lease
  guarantees each task has one owner at a time.

Limits of the current implementation:

- The demand map is one in-process object, so it is a shared point rather than
  a distributed one. A distributed version needs a replicated or bus-backed
  map.
- Every agent goes for the highest-demand type. Leases prevent duplicate work,
  but agents can still crowd onto one type.
- The decay rate and deposit amount trade responsiveness against stability,
  and there is no tuning guidance yet.
- No benchmark yet compares stigmergic selection with a central queue or with
  contract-net bidding. Until the scenario suites in the roadmap exist, the
  benefits above are design hypotheses, not measured results.
