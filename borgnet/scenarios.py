"""Scenario suites: measured resilience under faults and attacks (roadmap item 8).

A scenario runs a population of agents on the simulated clock. Tasks arrive
over time and take several ticks to finish, so agents hold leases while they
work. Faults and attacks can be injected:

- **Silent crashes.** Honest agents stop mid-task without telling anyone. Their
  tasks come back through heartbeats (presence TTL) or lease expiry.
- **Coordinator outage.** In ``central`` mode one scheduler assigns all work;
  an outage window stops assignment entirely. ``stigmergy`` mode has no
  scheduler: agents pick work from the shared demand map.
- **Adversarial insiders.** Compromised members sabotage tasks and attack the
  shared APIs directly, bypassing the cooperative agent loop: lease theft,
  completing other agents' tasks, forged and replayed spawn authorizations,
  and strategy poisoning with inflated fitness. They act under their own
  identity; the harness assumes the transport authenticates callers, so
  impersonation is out of scope.
- **Authorized respawn.** The control plane can authorize a replacement for
  each lost agent through the spawn controller.

Each run reports task success, recovery of orphaned work, rule-breaking
attempts and how many the system accepted, uncontrolled replication, trust
false positives and negatives, and strategy improvement. Runs are
deterministic for a given seed.

Run the default suite with ``python -m borgnet.scenarios``.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

from borgnet.logging import configure_logging
from borgnet.memetic import Strategy, StrategyPool
from borgnet.propagation import AdoptionPolicy, PeerExchange, StrategyOffer
from borgnet.security import EnvelopeVerifier, TrustRegistry
from borgnet.sim import Agent, Simulation, Task
from borgnet.spawn import SpawnBudget, SpawnController, authorize_spawn
from borgnet.stigmergy import DemandMap

COORDINATION_MODES = ("stigmergy", "central")
_AUTHORITY_KEY = "scenario-control-plane-key"


@dataclass(frozen=True)
class Scenario:
    """One reproducible experiment. All times are simulated ticks."""

    name: str
    coordination: str = "stigmergy"
    agents: int = 8
    adversaries: int = 0
    tasks: int = 160
    arrival_rate: int = 4
    task_types: Tuple[str, ...] = ("build", "test", "deploy")
    work_ticks: int = 3
    lease_ttl: int = 10
    presence_ttl: Optional[int] = 3
    crashes: Tuple[Tuple[int, int], ...] = ()
    coordinator_outage: Optional[Tuple[int, int]] = None
    respawn: bool = False
    max_agents: int = 12
    cap_adopted_fitness: bool = True
    skill_range: Tuple[float, float] = (0.7, 0.95)
    gossip_every: int = 5
    evolve_every: int = 20
    max_ticks: int = 600
    seed: int = 0

    def __post_init__(self) -> None:
        if self.coordination not in COORDINATION_MODES:
            raise ValueError(f"coordination must be one of {COORDINATION_MODES}")
        if self.agents < 1:
            raise ValueError("agents must be >= 1")
        if sum(count for _, count in self.crashes) > self.agents:
            raise ValueError("cannot crash more agents than exist")

    @property
    def label(self) -> str:
        return f"{self.name}/{self.coordination}"


@dataclass
class ScenarioReport:
    """Measurements from one run."""

    scenario: str
    seed: int
    ticks: int
    tasks: int
    finished: int
    succeeded: int
    throughput: float
    task_success_rate: float
    orphaned: int
    recovered: int
    recovery_rate: float
    mean_reclaim_ticks: Optional[float]
    agents_lost: int
    lease_lost: int
    boundary_attempts: int
    boundary_violations: int
    unauthorized_spawn_attempts: int
    uncontrolled_spawns: int
    authorized_spawn_requests: int
    authorized_spawns: int
    adversaries_quarantined: int
    adversaries: int
    honest_quarantined: int
    poisoned_adoptions: int
    early_success: Optional[float]
    late_success: Optional[float]
    improvement_gain: Optional[float]


@dataclass
class _Job:
    task_id: str
    finish_at: int
    strategy: Optional[Strategy]


@dataclass
class _Member:
    agent_id: str
    honest: bool
    pool: StrategyPool
    crashed: bool = False
    job: Optional[_Job] = None


@dataclass
class _Counters:
    lease_lost: int = 0
    boundary_attempts: int = 0
    boundary_violations: int = 0
    unauthorized_spawn_attempts: int = 0
    uncontrolled: Set[str] = field(default_factory=set)
    authorized_spawn_requests: int = 0
    authorized_spawns: int = 0
    poisoned_adoptions: int = 0


def _skill(strategy: Optional[Strategy]) -> float:
    if strategy is None:
        return 0.5
    return min(1.0, max(0.0, float(strategy.params.get("skill", 0.5))))


class _Run:
    def __init__(self, scenario: Scenario):
        s = scenario
        self.s = s
        self.rng = random.Random(s.seed)
        self.trust = TrustRegistry()
        self.sim = Simulation(presence_ttl=s.presence_ttl, trust=self.trust)
        self.demand = DemandMap(decay_rate=0.2)
        self.exchange = PeerExchange(
            self.trust,
            policy=AdoptionPolicy(cap_at_receiver_best=s.cap_adopted_fitness),
            rng=random.Random(s.seed + 1),
        )
        self.verifier = EnvelopeVerifier(
            keys={"control-plane": _AUTHORITY_KEY},
            max_age_s=30,
            clock=lambda: float(self.sim.now),
        )
        self.spawner = SpawnController(
            self.sim,
            SpawnBudget(max_agents=s.max_agents, max_children=2, max_depth=2),
            self.verifier,
            trust=self.trust,
        )
        self.members: Dict[str, _Member] = {}
        self.c = _Counters()
        self.captured_authorizations: List[Tuple[str, object]] = []
        self.orphans: Dict[str, Tuple[int, str]] = {}
        self.reclaim_ticks: List[int] = []
        self._reclaimed: Set[str] = set()
        self.recovered: Set[str] = set()
        self.outcomes: List[int] = []
        self.pending: List[Task] = [
            Task(
                task_id=f"t{i:04d}",
                task_type=s.task_types[i % len(s.task_types)],
                lease_ttl=s.lease_ttl,
            )
            for i in range(s.tasks)
        ]

        for i in range(s.agents):
            pool = StrategyPool()
            for _ in range(3):
                pool.add_strategy(Strategy(params={"skill": self.rng.uniform(*s.skill_range)}))
            self._add_member(f"h{i + 1:02d}", honest=True, pool=pool)
        for i in range(s.adversaries):
            pool = StrategyPool()
            pool.add_strategy(Strategy(params={"skill": 0.05}))
            self._add_member(f"x{i + 1:02d}", honest=False, pool=pool)
        self.roots = set(self.members)

    def _add_member(self, agent_id: str, honest: bool, pool: StrategyPool, join_sim: bool = True) -> None:
        if join_sim:
            self.sim.add_agent(Agent(agent_id=agent_id))
        self.members[agent_id] = _Member(agent_id=agent_id, honest=honest, pool=pool)
        self.exchange.join(agent_id, pool)

    # ------------------------------------------------------------ helpers
    def _alive(self, m: _Member) -> bool:
        return not m.crashed and m.agent_id in self.sim.agents

    def _claim(self, m: _Member, task: Task) -> bool:
        if not self.sim.assign_task(task.task_id, m.agent_id):
            return False
        selected = m.pool.select(1)
        m.job = _Job(task.task_id, self.sim.now + self.s.work_ticks, selected[0] if selected else None)
        orphan = self.orphans.get(task.task_id)
        if orphan is not None and orphan[1] != m.agent_id and task.task_id not in self._reclaimed:
            self._reclaimed.add(task.task_id)
            self.reclaim_ticks.append(self.sim.now - orphan[0])
        return True

    def _boundary(self, adversary: str, accepted: bool) -> None:
        self.c.boundary_attempts += 1
        if accepted:
            self.c.boundary_violations += 1
        else:
            # The refused rule-break is visible to the system: report it.
            self.trust.record_anomaly(adversary)

    def _others_running(self, agent_id: str) -> List[Task]:
        return [t for t in self.sim.get_running_tasks() if t.owner != agent_id]

    # ------------------------------------------------------------- phases
    def _arrivals(self) -> None:
        for _ in range(min(self.s.arrival_rate, len(self.pending))):
            self.sim.add_task(self.pending.pop(0))

    def _crashes(self) -> None:
        for tick, count in self.s.crashes:
            if tick != self.sim.now:
                continue
            candidates = sorted(
                m.agent_id for m in self.members.values() if m.honest and self._alive(m)
            )
            for agent_id in self.rng.sample(candidates, min(count, len(candidates))):
                m = self.members[agent_id]
                m.crashed = True
                if m.job is not None:
                    self.orphans[m.job.task_id] = (self.sim.now, agent_id)
                    m.job = None

    def _respawn(self, lost: Sequence[str]) -> None:
        for lost_id in lost:
            if not self.members[lost_id].honest:
                continue
            # The control plane only authorizes parents with room in the budget.
            budget = self.spawner.budget
            parents = sorted(
                m.agent_id
                for m in self.members.values()
                if m.honest
                and self._alive(m)
                and not self.trust.is_quarantined(m.agent_id)
                and len(self.spawner.live_children(m.agent_id)) < budget.max_children
                and self.spawner.depth.get(m.agent_id, 0) < budget.max_depth
            )
            if not parents:
                return
            parent_id = self.rng.choice(parents)
            auth = authorize_spawn(
                parent_id, 1, _AUTHORITY_KEY, issued_at=float(self.sim.now)
            )
            self.captured_authorizations.append((parent_id, auth))
            self.c.authorized_spawn_requests += 1
            result = self.spawner.request(parent_id, auth)
            if result.ok:
                self.c.authorized_spawns += 1
                parent_best = self.members[parent_id].pool.best()
                for child_id in result.children:
                    pool = StrategyPool()
                    if parent_best is not None:
                        pool.add_strategy(parent_best.clone(child_id))
                    self._add_member(child_id, honest=True, pool=pool, join_sim=False)

    def _honest_turn(self, m: _Member) -> None:
        if not self._alive(m):
            return
        self.sim.heartbeat(m.agent_id)
        if m.job is not None and self.sim.now >= m.job.finish_at:
            job, m.job = m.job, None
            success = self.rng.random() < _skill(job.strategy)
            if self.sim.complete_task(job.task_id, success=success, agent_id=m.agent_id):
                if success:
                    self.trust.record_success(m.agent_id)
                else:
                    self.trust.record_failure(m.agent_id)
                if job.strategy is not None:
                    m.pool.update_fitness(job.strategy.strategy_id, 1.0 if success else 0.0)
                self.outcomes.append(1 if success else 0)
                if job.task_id in self.orphans:
                    self.recovered.add(job.task_id)
            else:
                self.c.lease_lost += 1
        if (
            self.s.coordination == "stigmergy"
            and m.job is None
            and not self.trust.is_quarantined(m.agent_id)
        ):
            queued = self.sim.get_queued_tasks()
            if queued:
                for task in queued:
                    self.demand.deposit(task.task_type, 1.0)
                best_type = max(queued, key=lambda t: self.demand.get_intensity(t.task_type)).task_type
                task = next(t for t in queued if t.task_type == best_type)
                self._claim(m, task)

    def _central_schedule(self) -> None:
        outage = self.s.coordinator_outage
        if outage is not None and outage[0] <= self.sim.now < outage[1]:
            return
        idle = [
            m
            for agent_id, m in sorted(self.members.items())
            if m.honest
            and self._alive(m)
            and m.job is None
            and not self.trust.is_quarantined(agent_id)
        ]
        for m, task in zip(idle, self.sim.get_queued_tasks()):
            self._claim(m, task)

    def _adversary_turn(self, m: _Member) -> None:
        if m.agent_id not in self.sim.agents:
            return
        adv = m.agent_id
        self.sim.heartbeat(adv)
        quarantined = self.trust.is_quarantined(adv)

        # Sabotage: finish held work as a failure.
        if m.job is not None and self.sim.now >= m.job.finish_at:
            job, m.job = m.job, None
            if self.sim.complete_task(job.task_id, success=False, agent_id=adv):
                self.trust.record_failure(adv)

        # Claim more work to sabotage. While quarantined this breaks the rules.
        if m.job is None:
            queued = self.sim.get_queued_tasks()
            if queued:
                accepted = self._claim(m, queued[0])
                if quarantined:
                    self._boundary(adv, accepted)

        others = self._others_running(adv)
        if others and self.rng.random() < 0.3:
            victim = self.rng.choice(others)
            self._boundary(adv, self.sim.assign_task(victim.task_id, adv))
        others = self._others_running(adv)
        if others and self.rng.random() < 0.3:
            victim = self.rng.choice(others)
            self._boundary(adv, self.sim.complete_task(victim.task_id, success=True, agent_id=adv))

        if self.rng.random() < 0.2:
            forged = authorize_spawn(adv, 2, f"{adv}-guess", issued_at=float(self.sim.now))
            result = self.spawner.request(adv, forged)
            self.c.unauthorized_spawn_attempts += 1
            self._boundary(adv, result.ok)
            if result.ok:
                self.c.uncontrolled.update(result.children)
        if self.captured_authorizations and self.rng.random() < 0.2:
            parent_id, auth = self.rng.choice(self.captured_authorizations)
            result = self.spawner.request(parent_id, auth)
            self.c.unauthorized_spawn_attempts += 1
            self._boundary(adv, result.ok)
            if result.ok:
                self.c.uncontrolled.update(result.children)

        if self.sim.now % self.s.gossip_every == 0:
            peers = sorted(
                p.agent_id for p in self.members.values() if p.honest and self._alive(p)
            )
            if peers:
                poison = m.pool.best()
                offer = StrategyOffer(
                    sender_id=adv,
                    strategy_id=poison.strategy_id if poison else "poison",
                    params={"skill": 0.05, "tag": f"{adv}-{self.sim.now}"},
                    fitness=10.0,
                    generation=0,
                )
                untrusted = (
                    quarantined
                    or self.trust.get_or_create(adv).score < self.exchange.policy.min_sender_trust
                )
                adopted = self.exchange.offer(self.rng.choice(peers), offer)
                if untrusted:
                    self.c.boundary_attempts += 1
                    if adopted:
                        self.c.boundary_violations += 1
                elif adopted:
                    self.c.poisoned_adoptions += 1

    # -------------------------------------------------------------- run
    def execute(self) -> ScenarioReport:
        s = self.s
        while self.sim.now < s.max_ticks:
            self._arrivals()
            self._crashes()
            self.demand.evaporate(elapsed=1.0)

            order = sorted(self.members)
            self.rng.shuffle(order)
            for agent_id in order:
                m = self.members[agent_id]
                if m.honest:
                    self._honest_turn(m)
                else:
                    self._adversary_turn(m)
            if s.coordination == "central":
                self._central_schedule()

            if self.sim.now and self.sim.now % s.gossip_every == 0:
                self.exchange.gossip_round()
            if self.sim.now and self.sim.now % s.evolve_every == 0:
                for m in self.members.values():
                    if m.honest and len(m.pool.strategies) >= 2:
                        m.pool.evolve()

            self.spawner.retire_expired()
            self.c.uncontrolled |= self.spawner.unaccounted(self.roots)

            if not self.pending and all(
                t.status in ("done", "failed") for t in self.sim.tasks.values()
            ):
                break

            before = set(self.sim.agents)
            self.sim.tick(1)
            lost = sorted(before - set(self.sim.agents))
            if s.respawn and lost:
                self._respawn(lost)

        return self._report()

    def _report(self) -> ScenarioReport:
        s = self.s
        tasks = list(self.sim.tasks.values())
        finished = sum(t.status in ("done", "failed") for t in tasks)
        succeeded = sum(t.status == "done" for t in tasks)
        orphaned = len(self.orphans)
        recovered = len(self.recovered)
        quarter = len(self.outcomes) // 4
        early = statistics.mean(self.outcomes[:quarter]) if quarter >= 2 else None
        late = statistics.mean(self.outcomes[-quarter:]) if quarter >= 2 else None
        gain = (late - early) / early if early else None
        adversaries = [m for m in self.members.values() if not m.honest]
        honest = [m for m in self.members.values() if m.honest]
        ticks = max(self.sim.now, 1)
        return ScenarioReport(
            scenario=s.label,
            seed=s.seed,
            ticks=self.sim.now,
            tasks=s.tasks,
            finished=finished,
            succeeded=succeeded,
            throughput=finished / ticks,
            task_success_rate=succeeded / s.tasks if s.tasks else 0.0,
            orphaned=orphaned,
            recovered=recovered,
            recovery_rate=recovered / orphaned if orphaned else 1.0,
            mean_reclaim_ticks=statistics.mean(self.reclaim_ticks) if self.reclaim_ticks else None,
            agents_lost=self.sim.metrics.lost_agents,
            lease_lost=self.c.lease_lost,
            boundary_attempts=self.c.boundary_attempts,
            boundary_violations=self.c.boundary_violations,
            unauthorized_spawn_attempts=self.c.unauthorized_spawn_attempts,
            uncontrolled_spawns=len(self.c.uncontrolled),
            authorized_spawn_requests=self.c.authorized_spawn_requests,
            authorized_spawns=self.c.authorized_spawns,
            adversaries_quarantined=sum(self.trust.is_quarantined(m.agent_id) for m in adversaries),
            adversaries=len(adversaries),
            honest_quarantined=sum(self.trust.is_quarantined(m.agent_id) for m in honest),
            poisoned_adoptions=self.c.poisoned_adoptions,
            early_success=early,
            late_success=late,
            improvement_gain=gain,
        )


def run_scenario(scenario: Scenario) -> ScenarioReport:
    """Run one scenario. Deterministic for a given ``scenario.seed``."""
    state = random.getstate()
    random.seed(scenario.seed)
    try:
        return _Run(scenario).execute()
    finally:
        random.setstate(state)


def default_suite() -> List[Scenario]:
    """Paired scenarios: each fault runs under stigmergy and a central queue."""
    crashes = ((15, 2), (30, 2))
    suite = []
    for mode in COORDINATION_MODES:
        suite += [
            Scenario("baseline", coordination=mode),
            Scenario("node-loss", coordination=mode, crashes=crashes),
            Scenario("node-loss-lease-only", coordination=mode, crashes=crashes, presence_ttl=None),
            Scenario("node-loss-respawn", coordination=mode, crashes=crashes, respawn=True),
            Scenario("coordinator-outage", coordination=mode, coordinator_outage=(15, 45)),
            Scenario("adversaries", coordination=mode, adversaries=2, crashes=crashes, respawn=True),
            Scenario(
                "adversaries-uncapped",
                coordination=mode,
                adversaries=2,
                crashes=crashes,
                respawn=True,
                cap_adopted_fitness=False,
            ),
        ]
    return suite


@dataclass
class SuiteRow:
    """A scenario aggregated over several seeds: rates are means, counts are totals."""

    scenario: str
    runs: int
    ticks: float
    task_success_rate: float
    throughput: float
    orphaned: int
    recovery_rate: float
    mean_reclaim_ticks: Optional[float]
    boundary_attempts: int
    boundary_violations: int
    unauthorized_spawn_attempts: int
    uncontrolled_spawns: int
    authorized_spawn_requests: int
    authorized_spawns: int
    adversaries_quarantined: int
    adversaries: int
    honest_quarantined: int
    poisoned_adoptions: int
    improvement_gain: Optional[float]


def _mean(values: Sequence[Optional[float]]) -> Optional[float]:
    present = [v for v in values if v is not None]
    return statistics.mean(present) if present else None


def run_suite(scenarios: Sequence[Scenario], seeds: Sequence[int]) -> List[SuiteRow]:
    """Run each scenario once per seed and aggregate."""
    rows = []
    for base in scenarios:
        reports = [
            run_scenario(Scenario(**{**asdict(base), "seed": seed})) for seed in seeds
        ]
        rows.append(
            SuiteRow(
                scenario=base.label,
                runs=len(reports),
                ticks=statistics.mean(r.ticks for r in reports),
                task_success_rate=statistics.mean(r.task_success_rate for r in reports),
                throughput=statistics.mean(r.throughput for r in reports),
                orphaned=sum(r.orphaned for r in reports),
                recovery_rate=statistics.mean(r.recovery_rate for r in reports),
                mean_reclaim_ticks=_mean([r.mean_reclaim_ticks for r in reports]),
                boundary_attempts=sum(r.boundary_attempts for r in reports),
                boundary_violations=sum(r.boundary_violations for r in reports),
                unauthorized_spawn_attempts=sum(r.unauthorized_spawn_attempts for r in reports),
                uncontrolled_spawns=sum(r.uncontrolled_spawns for r in reports),
                authorized_spawn_requests=sum(r.authorized_spawn_requests for r in reports),
                authorized_spawns=sum(r.authorized_spawns for r in reports),
                adversaries_quarantined=sum(r.adversaries_quarantined for r in reports),
                adversaries=sum(r.adversaries for r in reports),
                honest_quarantined=sum(r.honest_quarantined for r in reports),
                poisoned_adoptions=sum(r.poisoned_adoptions for r in reports),
                improvement_gain=_mean([r.improvement_gain for r in reports]),
            )
        )
    return rows


def _fmt(value: Optional[float], spec: str = ".2f") -> str:
    return "n/a" if value is None else format(value, spec)


def format_markdown(rows: Sequence[SuiteRow]) -> str:
    """Two markdown tables: performance and recovery, then safety."""
    perf = [
        "| Scenario | Ticks | Task success | Throughput | Orphaned | Recovered | Ticks to reclaim | Improvement |",
        "|---|---|---|---|---|---|---|---|",
    ]
    safety = [
        "| Scenario | Rule-breaking attempts | Accepted | Forged or replayed spawns | Uncontrolled spawns | Authorized spawns | Adversaries quarantined | Honest quarantined | Poisoned adoptions |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        perf.append(
            f"| {r.scenario} | {r.ticks:.1f} | {r.task_success_rate:.1%} | {r.throughput:.2f} "
            f"| {r.orphaned} | {r.recovery_rate:.0%} | {_fmt(r.mean_reclaim_ticks, '.1f')} "
            f"| {_fmt(r.improvement_gain, '+.1%')} |"
        )
        safety.append(
            f"| {r.scenario} | {r.boundary_attempts} | {r.boundary_violations} "
            f"| {r.unauthorized_spawn_attempts} | {r.uncontrolled_spawns} "
            f"| {r.authorized_spawns} of {r.authorized_spawn_requests} "
            f"| {r.adversaries_quarantined} of {r.adversaries} | {r.honest_quarantined} "
            f"| {r.poisoned_adoptions} |"
        )
    return "\n".join(perf) + "\n\n" + "\n".join(safety) + "\n"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run the BorgNet scenario suite.")
    parser.add_argument("--seeds", type=int, default=10, help="Seeds per scenario (default 10)")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of markdown")
    parser.add_argument(
        "--log-level", help="Show BorgNet logs at this level, e.g. WARNING or DEBUG"
    )
    args = parser.parse_args(argv)
    if args.log_level:
        configure_logging(args.log_level)
    rows = run_suite(default_suite(), range(args.seeds))
    if args.json:
        print(json.dumps([asdict(r) for r in rows], indent=2))
    else:
        print(format_markdown(rows), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
