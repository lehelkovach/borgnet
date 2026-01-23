"""Integration tests for simulation workflow."""

import pytest

from borgnet.sim import Agent, Simulation, Task


class TestSimulationWorkflow:
    """Test full simulation workflows."""

    def test_multi_agent_task_distribution(self):
        """Test multiple agents processing multiple tasks."""
        sim = Simulation()
        sim.add_agent(Agent(agent_id="a1", role="worker"))
        sim.add_agent(Agent(agent_id="a2", role="worker"))
        sim.add_agent(Agent(agent_id="a3", role="worker"))

        for i in range(5):
            sim.add_task(Task(task_id=f"t{i}", task_type="deploy", lease_ttl=30))

        assert sim.metrics.total_tasks == 5
        assert sim.metrics.active_agents == 3

        # Assign tasks round-robin style
        agent_ids = list(sim.agents.keys())
        for i, task_id in enumerate(sim.tasks.keys()):
            sim.assign_task(task_id, agent_ids[i % len(agent_ids)])

        # All tasks should be running
        for task in sim.tasks.values():
            assert task.status == "running"
            assert task.owner is not None

    def test_task_completion_updates_metrics(self):
        """Test that completing tasks updates metrics correctly."""
        sim = Simulation()
        sim.add_agent(Agent(agent_id="a1"))
        sim.add_task(Task(task_id="t1", task_type="test"))
        sim.add_task(Task(task_id="t2", task_type="test"))
        sim.add_task(Task(task_id="t3", task_type="test"))

        sim.assign_task("t1", "a1")
        sim.assign_task("t2", "a1")
        sim.assign_task("t3", "a1")

        sim.complete_task("t1", success=True)
        sim.complete_task("t2", success=True)
        sim.complete_task("t3", success=False)

        assert sim.metrics.completed_tasks == 2
        assert sim.metrics.failed_tasks == 1

    def test_lease_expiry_cascade(self):
        """Test that multiple lease expiries are handled in one tick."""
        sim = Simulation()
        sim.add_agent(Agent(agent_id="a1"))

        for i in range(3):
            sim.add_task(Task(task_id=f"t{i}", task_type="deploy", lease_ttl=10))
            sim.assign_task(f"t{i}", "a1")

        # Fast forward past all leases
        sim.tick(15)

        # All tasks should be requeued
        for task in sim.tasks.values():
            assert task.status == "queued"
            assert task.owner is None

        assert sim.metrics.reassigned_tasks == 3

    def test_partial_completion_before_expiry(self):
        """Test completing a task before lease expires."""
        sim = Simulation()
        sim.add_agent(Agent(agent_id="a1"))
        sim.add_task(Task(task_id="t1", task_type="deploy", lease_ttl=60))

        sim.assign_task("t1", "a1")
        sim.tick(30)  # Halfway through lease
        sim.complete_task("t1", success=True)

        assert sim.tasks["t1"].status == "done"
        assert sim.metrics.completed_tasks == 1
        assert sim.metrics.reassigned_tasks == 0

    def test_agent_role_assignment(self):
        """Test agents with different roles."""
        sim = Simulation()
        sim.add_agent(Agent(agent_id="supervisor", role="supervisor"))
        sim.add_agent(Agent(agent_id="worker1", role="worker"))
        sim.add_agent(Agent(agent_id="worker2", role="worker"))

        supervisors = [a for a in sim.agents.values() if a.role == "supervisor"]
        workers = [a for a in sim.agents.values() if a.role == "worker"]

        assert len(supervisors) == 1
        assert len(workers) == 2

    def test_agent_capabilities(self):
        """Test agents with different capabilities."""
        sim = Simulation()
        sim.add_agent(Agent(agent_id="a1", capabilities=["python", "docker"]))
        sim.add_agent(Agent(agent_id="a2", capabilities=["go", "kubernetes"]))

        a1 = sim.agents["a1"]
        a2 = sim.agents["a2"]

        assert "python" in a1.capabilities
        assert "kubernetes" in a2.capabilities


class TestMetricsSnapshot:
    """Test metrics snapshot functionality."""

    def test_snapshot_after_workflow(self):
        """Test snapshot captures full workflow state."""
        sim = Simulation()
        sim.add_agent(Agent(agent_id="a1"))
        sim.add_agent(Agent(agent_id="a2"))

        for i in range(10):
            sim.add_task(Task(task_id=f"t{i}", task_type="deploy", lease_ttl=5))

        # Assign half, let some expire
        for i in range(5):
            sim.assign_task(f"t{i}", "a1")

        sim.tick(10)  # Expire all
        sim.assign_task("t0", "a2")
        sim.complete_task("t0", success=True)

        snap = sim.metrics.snapshot()
        assert snap["total_tasks"] == 10.0
        assert snap["active_agents"] == 2.0
        assert snap["completed_tasks"] == 1.0
        assert snap["reassigned_tasks"] == 5.0
