"""Tests for heartbeats and presence TTL in the simulation."""

import pytest

from borgnet.agent import AgentRunner, StubWorker
from borgnet.memetic import StrategyPool
from borgnet.security import TrustRegistry
from borgnet.sim import Agent, Simulation, Task
from borgnet.stigmergy import DemandMap


def _sim(ttl=5):
    sim = Simulation(presence_ttl=ttl)
    sim.add_agent(Agent(agent_id="a1"))
    sim.add_agent(Agent(agent_id="a2"))
    sim.add_task(Task(task_id="t1", task_type="build", lease_ttl=60))
    return sim


def test_silent_agent_dropped_and_task_requeued_before_lease_expiry():
    sim = _sim(ttl=5)
    sim.assign_task("t1", "a1")
    for _ in range(6):
        sim.tick(1)
        sim.heartbeat("a2")
    assert "a1" not in sim.agents
    assert "a2" in sim.agents
    assert sim.tasks["t1"].status == "queued"  # well before the 60s lease
    assert sim.tasks["t1"].owner is None
    assert sim.metrics.lost_agents == 1
    assert sim.metrics.reassigned_tasks == 1
    assert sim.metrics.active_agents == 1


def test_heartbeats_keep_agent_present():
    sim = _sim(ttl=5)
    sim.assign_task("t1", "a1")
    for _ in range(20):
        sim.tick(1)
        sim.heartbeat("a1")
        sim.heartbeat("a2")
    assert set(sim.agents) == {"a1", "a2"}
    assert sim.tasks["t1"].status == "running"


def test_ttl_boundary():
    sim = _sim(ttl=5)
    sim.tick(5)  # silent for exactly the TTL: still present
    assert "a1" in sim.agents
    sim.tick(1)  # silent for longer than the TTL: dropped
    assert "a1" not in sim.agents


def test_without_presence_ttl_agents_are_never_dropped():
    sim = Simulation()
    sim.add_agent(Agent(agent_id="a1"))
    sim.tick(10_000)
    assert "a1" in sim.agents


def test_heartbeat_from_unknown_agent_is_rejected():
    sim = _sim()
    assert sim.heartbeat("ghost") is False
    assert sim.heartbeat("a1") is True


def test_negative_ttl_rejected():
    with pytest.raises(ValueError):
        Simulation(presence_ttl=-1)


def _runner(sim, agent):
    return AgentRunner(
        agent, sim, StrategyPool(), DemandMap(), TrustRegistry(), StubWorker(fitness=1.0)
    )


def test_agent_runner_steps_are_heartbeats():
    sim = Simulation(presence_ttl=5)
    agent = Agent(agent_id="a1")
    sim.add_agent(agent)
    runner = _runner(sim, agent)
    sim.tick(4)
    runner.step()  # heartbeat at t=4 (idle: no tasks)
    sim.tick(4)  # t=8, silent for 4s
    assert "a1" in sim.agents


def test_dropped_agent_rejoins_on_next_step():
    sim = Simulation(presence_ttl=2)
    agent = Agent(agent_id="a1")
    sim.add_agent(agent)
    sim.add_task(Task(task_id="t1", task_type="build", lease_ttl=60))
    runner = _runner(sim, agent)
    sim.tick(5)
    assert "a1" not in sim.agents
    result = runner.step()
    assert "a1" in sim.agents
    assert result.outcome == "completed"
