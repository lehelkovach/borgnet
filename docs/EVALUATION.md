# BorgNet Evaluation

This page reports what the scenario harness in `borgnet/scenarios.py`
measured. Every number comes from the command below and is reproducible:
runs are deterministic for a given seed.

```bash
npm run scenarios -- --seeds 30
# or
python3 -m borgnet.scenarios --seeds 30
```

Read the limits section before quoting any of it. This is a single-process
simulation, and several results follow from how the model is built.

## Setup

| Setting | Value |
|---|---|
| Honest agents | 8, each with 3 strategies of random skill between 0.7 and 0.95 |
| Tasks | 160 across 3 types, 4 arriving per tick, each taking 3 ticks |
| Load | Arrivals exceed capacity, so a backlog builds |
| Lease length | 10 ticks |
| Heartbeat timeout | 3 ticks, except in the lease-only scenarios |
| Node loss | 2 honest agents crash silently at tick 15 and 2 more at tick 30 |
| Coordinator outage | Ticks 15 to 45 |
| Insiders | 2 compromised members, in the adversary scenarios |
| Seeds | 30 per scenario |

Two coordination modes run every scenario:

- **stigmergy**: agents pick work from the shared demand map. There is no
  scheduler.
- **central**: one scheduler hands queued tasks to idle agents in arrival
  order. It stands in for a central work queue.

An insider is a member that has been compromised. It sabotages tasks it
claims and calls the shared APIs directly, skipping the cooperative agent
loop. It tries lease theft, completing other agents' tasks, forged and
replayed spawn authorizations, and strategy poisoning with an inflated
self-reported fitness. Every refused rule-breaking call is reported to trust
as an anomaly. Insiders act under their own identity: the model assumes the
transport authenticates callers, so impersonation is out of scope.

## Results

Rates are means over 30 runs. Counts are totals over 30 runs.

| Scenario | Ticks | Task success | Throughput | Orphaned | Recovered | Ticks to reclaim | Improvement |
|---|---|---|---|---|---|---|---|
| baseline/stigmergy | 61.4 | 82.8% | 2.61 | 0 | 100% | n/a | -2.5% |
| node-loss/stigmergy | 102.6 | 83.2% | 1.56 | 120 | 100% | 3.5 | -2.3% |
| node-loss-lease-only/stigmergy | 102.6 | 83.2% | 1.56 | 120 | 100% | 8.2 | -2.3% |
| node-loss-respawn/stigmergy | 64.0 | 83.8% | 2.50 | 120 | 100% | 3.0 | -0.1% |
| coordinator-outage/stigmergy | 61.4 | 82.8% | 2.61 | 0 | 100% | n/a | -2.5% |
| adversaries/stigmergy | 63.5 | 81.1% | 2.52 | 120 | 100% | 3.2 | +3.7% |
| adversaries-uncapped/stigmergy | 237.3 | 57.5% | 1.42 | 111 | 100% | 3.4 | +1.6% |
| baseline/central | 61.4 | 82.6% | 2.61 | 0 | 100% | n/a | -2.9% |
| node-loss/central | 103.9 | 83.7% | 1.54 | 119 | 100% | 3.1 | +2.0% |
| node-loss-lease-only/central | 103.9 | 83.7% | 1.54 | 119 | 100% | 8.1 | +2.0% |
| node-loss-respawn/central | 64.2 | 84.0% | 2.49 | 119 | 100% | 3.0 | +1.8% |
| coordinator-outage/central | 90.3 | 83.9% | 1.77 | 0 | 100% | n/a | -0.3% |
| adversaries/central | 64.0 | 80.9% | 2.50 | 119 | 100% | 3.0 | +4.5% |
| adversaries-uncapped/central | 332.7 | 43.4% | 0.89 | 110 | 100% | 3.0 | -15.9% |

| Scenario | Rule-breaking attempts | Accepted | Forged or replayed spawns | Uncontrolled spawns | Authorized spawns | Adversaries quarantined | Honest quarantined | Poisoned adoptions |
|---|---|---|---|---|---|---|---|---|
| baseline/stigmergy | 0 | 0 | 0 | 0 | 0 of 0 | 0 of 0 | 3 | 0 |
| node-loss/stigmergy | 0 | 0 | 0 | 0 | 0 of 0 | 0 of 0 | 1 | 0 |
| node-loss-lease-only/stigmergy | 0 | 0 | 0 | 0 | 0 of 0 | 0 of 0 | 1 | 0 |
| node-loss-respawn/stigmergy | 0 | 0 | 0 | 0 | 120 of 120 | 0 of 0 | 0 | 0 |
| coordinator-outage/stigmergy | 0 | 0 | 0 | 0 | 0 of 0 | 0 of 0 | 3 | 0 |
| adversaries/stigmergy | 7781 | 0 | 1337 | 0 | 120 of 120 | 60 of 60 | 1 | 28 |
| adversaries-uncapped/stigmergy | 25895 | 0 | 5547 | 0 | 120 of 120 | 60 of 60 | 145 | 28 |
| baseline/central | 0 | 0 | 0 | 0 | 0 of 0 | 0 of 0 | 2 | 0 |
| node-loss/central | 0 | 0 | 0 | 0 | 0 of 0 | 0 of 0 | 3 | 0 |
| node-loss-lease-only/central | 0 | 0 | 0 | 0 | 0 of 0 | 0 of 0 | 3 | 0 |
| node-loss-respawn/central | 0 | 0 | 0 | 0 | 120 of 120 | 0 of 0 | 3 | 0 |
| coordinator-outage/central | 0 | 0 | 0 | 0 | 0 of 0 | 0 of 0 | 2 | 0 |
| adversaries/central | 7751 | 0 | 1296 | 0 | 120 of 120 | 60 of 60 | 5 | 42 |
| adversaries-uncapped/central | 34916 | 0 | 7827 | 0 | 120 of 120 | 60 of 60 | 201 | 42 |

## What the results show

**Without faults, the two modes perform the same.** Both finish in about
61 ticks at 2.61 tasks per tick with about 83% task success. In this model
stigmergy has no throughput advantage over a central queue.

**A coordinator outage stalls only the central queue.** The 30-tick outage
stretched the central run from 61.4 to 90.3 ticks and cut throughput by a
third. Stigmergy was unaffected because it has no coordinator. This follows
directly from the model: a single scheduler is a single point of failure.
The size of the effect depends on how long the outage lasts.

**All work orphaned by silent crashes was recovered.** Losing half the agents
orphaned 1,177 in-progress tasks across all scenarios, and another agent
finished every one. Heartbeats reclaimed orphaned work in about 3.5 ticks,
against about 8.2 ticks with lease expiry alone, a 57% reduction. Total run
time did not change, though, because with a backlog the lost capacity
dominates, not how fast individual tasks are reclaimed.

**Authorized respawn restored capacity, within budget.** Replacing each lost
agent through the spawn controller brought run time back to 64 ticks against
61 without faults. All 720 authorized spawns succeeded.

**No rule-breaking call was accepted.** Insiders made 76,343 rule-breaking
calls across all adversary runs, including 16,007 forged or replayed spawn
authorizations. The system accepted none, no agent appeared outside the spawn
controller, and every insider was quarantined. With the adoption cap in place,
runs with insiders finished in about 64 ticks with 81% task success, close to
the fault-free runs.

**The harness found a poisoning cascade, and the fix works.** Before the
adoption cap, an insider that was still trusted could offer a strategy with an
inflated fitness. The receiver adopted it as its best strategy, then passed it
on to its peers as a trusted sender. Honest agents using it failed tasks and
were quarantined. The `adversaries-uncapped` rows keep that behavior: 145 and
201 honest agents quarantined, task success of 57% and 43%, and runs four to
five times longer. Capping adopted fitness at the receiver's own best brought
that to 1 and 5 honest agents quarantined, with poisoned adoptions unchanged.
The poison still gets tried; it just cannot dominate or spread.

**Trust scoring flags some honest agents.** Across the 300 runs without
insiders, 21 honest agents were quarantined, about one in a hundred. A task
failure costs 0.2 trust and a success earns only 0.1, so an honest agent with
70% skill drifts toward zero and an unlucky streak quarantines it. Task
failure is treated the same as misbehavior. Scoring competence separately
from integrity would fix this and is not done yet.

**Strategy evolution did not measurably help.** Late-run success was within
a few percent of early-run success in every fault-free and crash-only
scenario, between -2.9% and +2.0%. Selection is only weakly weighted by
fitness, because it shifts every weight so the weakest strategy still has
weight 1. At these run lengths the memetic layer does not improve outcomes.
The adversary runs show larger swings, but those reflect recovery from early
sabotage, not learning.

## Against the Navy NV012 topic metrics

The Navy SBIR topic DON27BZ02-NV012 lists measurable targets. Where the
harness measures the same thing:

| NV012 target | Measured here | Status |
|---|---|---|
| Safety and boundary violations 0% | 0 accepted of 76,343 rule-breaking calls | Met for the attacks modeled |
| Uncontrolled replication 0% | 0 accepted of 16,007 forged or replayed spawn authorizations; no unaccounted agents | Met for the attacks modeled |
| Replication success 100% when authorized | 720 of 720 authorized spawns | Met |
| Recovery rate 80% or more | 100% of 1,177 orphaned tasks | Met |
| Task success 90% or more | 81% to 84% | Not met. Set mostly by modeled agent skill, which averages 0.825 |
| Improvement gain over 20% | Within noise | Not met |
| Regression under 5% | Not measured | Not measured |

## Limits

- **Single process.** Agents share memory and a simulated clock. There is no
  network, so message loss, delay, and partitions are not modeled. Running
  across machines is roadmap item 3.
- **Scripted adversaries.** Insiders follow a fixed attack mix with fixed
  probabilities. There is no adaptive or colluding adversary, and only two
  insiders per run.
- **Authenticated callers assumed.** Insiders cannot impersonate other
  agents. Without an authenticated transport that assumption fails.
- **Zero accepted is not proof of safety.** It shows the enforcement points
  refuse the calls that were tried, not that no other attack path exists.
- **Simple baseline.** The central queue is first-in, first-out with perfect
  knowledge. Its outage penalty comes straight from the model.
- **Parameter-dependent.** Arrival rate, task length, lease and heartbeat
  timeouts, and agent skill all move these numbers. The suite fixes them as
  shown above.
- **Symmetric keys.** The spawn authority signs with an HMAC key the harness
  holds. A real control plane needs that key protected, and public-key
  signatures are roadmap item 4.
