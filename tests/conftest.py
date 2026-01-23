"""Pytest configuration and shared fixtures."""

import pytest

from borgnet.metrics import Metrics
from borgnet.sim import Agent, Simulation, Task


@pytest.fixture
def empty_simulation():
    """Create an empty simulation."""
    return Simulation()


@pytest.fixture
def simulation_with_agents():
    """Create a simulation with 3 agents."""
    sim = Simulation()
    sim.add_agent(Agent(agent_id="agent-1", role="worker", capabilities=["python"]))
    sim.add_agent(Agent(agent_id="agent-2", role="worker", capabilities=["go"]))
    sim.add_agent(Agent(agent_id="agent-3", role="supervisor"))
    return sim


@pytest.fixture
def simulation_with_tasks():
    """Create a simulation with agents and tasks."""
    sim = Simulation()
    sim.add_agent(Agent(agent_id="agent-1"))
    sim.add_agent(Agent(agent_id="agent-2"))
    sim.add_task(Task(task_id="task-1", task_type="deploy", lease_ttl=30))
    sim.add_task(Task(task_id="task-2", task_type="test", lease_ttl=60))
    sim.add_task(Task(task_id="task-3", task_type="build", lease_ttl=45))
    return sim


@pytest.fixture
def fresh_metrics():
    """Create a fresh metrics instance."""
    return Metrics()
