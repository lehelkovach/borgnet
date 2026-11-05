"""Unit tests for the single-agent worker loop."""

from borgnet.agent import AgentRunner, StubWorker
from borgnet.memetic import Strategy, StrategyPool
from borgnet.security import TrustRegistry
from borgnet.sim import Agent, Simulation, Task
from borgnet.stigmergy import DemandMap


def _runner(worker, capabilities=None, tasks=(("t1", "deploy"),), with_strategy=True):
    sim = Simulation()
    agent = Agent(agent_id="a1", capabilities=list(capabilities or []))
    sim.add_agent(agent)
    for task_id, task_type in tasks:
        sim.add_task(Task(task_id=task_id, task_type=task_type, lease_ttl=30))
    pool = StrategyPool()
    if with_strategy:
        pool.add_strategy(Strategy(params={"temperature": 1.0}))
    demand = DemandMap()
    trust = TrustRegistry()
    runner = AgentRunner(agent, sim, pool, demand, trust, worker)
    return runner, sim, pool, demand, trust


class TestAgentRunner:
    def test_claims_lease_and_completes(self):
        runner, sim, _, _, trust = _runner(StubWorker(fitness=1.0))
        result = runner.step()
        assert result.outcome == "completed"
        assert result.task_id == "t1"
        assert sim.tasks["t1"].status == "done"
        assert sim.tasks["t1"].owner is None  # lease released
        assert trust.get_or_create("a1").score > 1.0  # success raised trust

    def test_idle_when_no_task(self):
        runner, _, _, _, _ = _runner(StubWorker(), tasks=())
        assert runner.step().outcome == "idle"

    def test_soft_failure_records_failure(self):
        runner, sim, _, demand, trust = _runner(StubWorker(fitness=0.0))
        result = runner.step()
        assert result.outcome == "failed"
        assert sim.tasks["t1"].status == "failed"
        assert trust.get_or_create("a1").score < 1.0  # failure lowered trust
        assert demand.get_intensity("deploy") > 0  # demand still standing

    def test_worker_death_requeues(self):
        runner, sim, _, _, trust = _runner(StubWorker(raises=True))
        result = runner.step()
        assert result.outcome == "requeued"
        assert sim.tasks["t1"].status == "queued"  # back on the queue
        assert sim.tasks["t1"].owner is None
        assert trust.get_or_create("a1").score < 1.0  # death counted as failure

    def test_capability_filter_skips_unhandled(self):
        runner, sim, _, _, _ = _runner(
            StubWorker(fitness=1.0), capabilities=["deploy"], tasks=(("t1", "build"),)
        )
        assert runner.step().outcome == "idle"
        assert sim.tasks["t1"].status == "queued"  # untouched

    def test_quarantined_agent_skips(self):
        runner, sim, _, _, trust = _runner(StubWorker(fitness=1.0))
        trust.record_anomaly("a1")
        trust.record_anomaly("a1")  # 1.0 -> 0.5 -> 0.0, below 0.3 threshold
        assert trust.is_quarantined("a1")
        result = runner.step()
        assert result.outcome == "quarantined"
        assert sim.tasks["t1"].status == "queued"  # no lease claimed

    def test_strategy_selected_and_fitness_updated(self):
        runner, _, pool, _, _ = _runner(StubWorker(fitness=1.0))
        result = runner.step()
        assert result.strategy_id is not None
        # Reported fitness fed back into the pool (EMA from 0.0 toward 1.0).
        assert pool.strategies[result.strategy_id].fitness > 0.0

    def test_demand_deposited_on_observe(self):
        runner, _, _, demand, _ = _runner(StubWorker(fitness=1.0))
        assert demand.get_intensity("deploy") == 0.0
        runner.step()
        assert demand.get_intensity("deploy") > 0.0

    def test_runs_until_idle(self):
        runner, sim, _, _, _ = _runner(
            StubWorker(fitness=1.0), tasks=(("t1", "deploy"), ("t2", "deploy"))
        )
        results = runner.run(max_steps=10)
        assert results[-1].outcome == "idle"
        assert sim.tasks["t1"].status == "done"
        assert sim.tasks["t2"].status == "done"

    def test_runs_with_empty_strategy_pool(self):
        # Agent still works when no strategy is available to select.
        runner, sim, _, _, _ = _runner(StubWorker(fitness=1.0), with_strategy=False)
        result = runner.step()
        assert result.outcome == "completed"
        assert result.strategy_id is None
        assert sim.tasks["t1"].status == "done"
