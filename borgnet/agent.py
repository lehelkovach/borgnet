"""Single-agent worker loop wiring the swarm primitives together.

This is roadmap item 1: a minimal running agent that ties the existing
primitives into one loop. One agent observes queued work, reinforces the
stigmergic demand map, claims a task lease, selects a strategy from the pool,
executes the task via a pluggable :class:`Worker`, reports the outcome, and
updates its trust score accordingly. A worker that raises mid-task (a "dead"
worker) requeues the task for a healthy peer.

Scope: this is deliberately a *single-agent* loop. Peer-to-peer strategy
transmission between agents (the trust-gated horizontal channel) is roadmap
item 2 and is intentionally not implemented here. The :class:`Worker` backend
is an injected dependency; this module makes no network calls of its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol

from borgnet.logging import get_logger
from borgnet.memetic import Strategy, StrategyPool
from borgnet.security import TrustRegistry
from borgnet.sim import Agent, Simulation, Task
from borgnet.stigmergy import DemandMap

_log = get_logger("agent")


class Worker(Protocol):
    """Pluggable execution backend.

    An implementation runs a task under a chosen strategy and returns a fitness
    score (higher is better). Raising an exception models a worker that dies
    mid-task. Real workers (an LLM call, a tool invocation) are injected by the
    caller; nothing here reaches the network on its own.
    """

    def run(self, task: Task, strategy: Optional[Strategy]) -> float:
        ...


class StubWorker:
    """Trivial in-process worker for tests and simulation. No external calls.

    Returns a fixed fitness. Set ``raises=True`` to model a worker that dies
    mid-task.
    """

    def __init__(self, fitness: float = 1.0, raises: bool = False):
        self.fitness = fitness
        self.raises = raises

    def run(self, task: Task, strategy: Optional[Strategy]) -> float:
        if self.raises:
            raise RuntimeError(f"stub worker died on task {task.task_id}")
        return self.fitness


@dataclass
class StepResult:
    """Outcome of a single :meth:`AgentRunner.step`."""

    outcome: str  # "completed" | "failed" | "requeued" | "idle" | "quarantined"
    task_id: Optional[str] = None
    strategy_id: Optional[str] = None
    fitness: Optional[float] = None


class AgentRunner:
    """Drives one agent through claim -> execute -> report cycles.

    The agent reads the shared demand map and trust registry, so several
    runners over the same ``Simulation`` coordinate indirectly (stigmergy) and
    are judged by the same externally-scored trust. Each runner, however, only
    acts for its own agent.
    """

    def __init__(
        self,
        agent: Agent,
        sim: Simulation,
        pool: StrategyPool,
        demand: DemandMap,
        trust: TrustRegistry,
        worker: Worker,
        success_threshold: float = 0.0,
    ):
        self.agent = agent
        self.sim = sim
        self.pool = pool
        self.demand = demand
        self.trust = trust
        self.worker = worker
        self.success_threshold = success_threshold
        _log.debug(
            "AgentRunner created: agent=%s success_threshold=%.3f",
            agent.agent_id,
            success_threshold,
        )

    def _can_handle(self, task: Task) -> bool:
        """An agent with no declared capabilities handles any task type."""
        if not self.agent.capabilities:
            return True
        return task.task_type in self.agent.capabilities

    def _select_task(self) -> Optional[Task]:
        """Pick a queued task via the stigmergic demand map.

        Observing queued work reinforces the demand signal for its type (the
        pheromone deposit), and the agent then prefers the handleable task
        whose type currently has the highest demand.
        """
        candidates = [t for t in self.sim.get_queued_tasks() if self._can_handle(t)]
        if not candidates:
            return None
        for task in candidates:
            self.demand.deposit(task.task_type, amount=1.0)
        candidates.sort(
            key=lambda t: self.demand.get_intensity(t.task_type), reverse=True
        )
        chosen = candidates[0]
        _log.debug(
            "Task selected: agent=%s task=%s type=%s demand=%.3f",
            self.agent.agent_id,
            chosen.task_id,
            chosen.task_type,
            self.demand.get_intensity(chosen.task_type),
        )
        return chosen

    def step(self) -> StepResult:
        """Run one claim-execute-report cycle. Returns what happened."""
        if self.trust.is_quarantined(self.agent.agent_id):
            _log.warning("Agent quarantined, skipping step: agent=%s", self.agent.agent_id)
            return StepResult(outcome="quarantined")

        task = self._select_task()
        if task is None:
            return StepResult(outcome="idle")

        # Claim the lease.
        self.sim.assign_task(task.task_id, self.agent.agent_id)

        # Select a strategy to execute under (may be None if the pool is empty).
        selected = self.pool.select(1)
        strategy = selected[0] if selected else None
        strategy_id = strategy.strategy_id if strategy else None

        # Execute via the injected worker.
        try:
            fitness = self.worker.run(task, strategy)
        except Exception as exc:  # worker died mid-task
            _log.warning(
                "Worker died mid-task: agent=%s task=%s error=%s",
                self.agent.agent_id,
                task.task_id,
                exc,
            )
            self.trust.record_failure(self.agent.agent_id)
            if strategy is not None:
                self.pool.update_fitness(strategy.strategy_id, 0.0)
            # The task still needs doing: reinforce demand and requeue it so a
            # healthy peer can pick it up.
            self.demand.deposit(task.task_type, amount=1.0)
            self.sim.requeue_task(task.task_id)
            return StepResult(
                outcome="requeued", task_id=task.task_id, strategy_id=strategy_id
            )

        # Worker returned: report success or failure by fitness.
        success = fitness > self.success_threshold
        self.sim.complete_task(task.task_id, success=success)
        if success:
            self.trust.record_success(self.agent.agent_id)
        else:
            self.trust.record_failure(self.agent.agent_id)
            # A failed attempt leaves demand for that task type standing.
            self.demand.deposit(task.task_type, amount=1.0)
        if strategy is not None:
            self.pool.update_fitness(strategy.strategy_id, fitness)

        return StepResult(
            outcome="completed" if success else "failed",
            task_id=task.task_id,
            strategy_id=strategy_id,
            fitness=fitness,
        )

    def run(self, max_steps: int = 100) -> list[StepResult]:
        """Step until idle or quarantined, or until ``max_steps`` is reached."""
        results: list[StepResult] = []
        for _ in range(max_steps):
            result = self.step()
            results.append(result)
            if result.outcome in ("idle", "quarantined"):
                break
        _log.info(
            "AgentRunner finished: agent=%s steps=%d last=%s",
            self.agent.agent_id,
            len(results),
            results[-1].outcome if results else "none",
        )
        return results
