from borgnet.sim import Agent, Simulation, Task


def test_task_reassignment_on_lease_expiry():
    sim = Simulation()
    sim.add_agent(Agent(agent_id="a1"))
    sim.add_task(Task(task_id="t1", task_type="deploy", lease_ttl=5))
    sim.assign_task("t1", "a1")
    sim.tick(6)

    task = sim.tasks["t1"]
    assert task.status == "queued"
    assert task.owner is None
    assert sim.metrics.reassigned_tasks == 1
