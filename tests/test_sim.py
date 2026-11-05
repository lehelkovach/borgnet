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


def test_requeue_task_returns_to_queue():
    sim = Simulation()
    sim.add_agent(Agent(agent_id="a1"))
    sim.add_task(Task(task_id="t1", task_type="deploy", lease_ttl=30))
    sim.assign_task("t1", "a1")
    assert sim.tasks["t1"].status == "running"

    sim.requeue_task("t1")

    task = sim.tasks["t1"]
    assert task.status == "queued"
    assert task.owner is None
    assert task.lease_expires_at is None
    assert sim.metrics.reassigned_tasks == 1


def test_requeue_unknown_task_raises():
    sim = Simulation()
    try:
        sim.requeue_task("nope")
        assert False, "expected KeyError"
    except KeyError:
        pass


def test_zero_ttl_lease_expires():
    # Regression: an expiry time of 0 is falsy and used to never expire.
    sim = Simulation()
    sim.add_task(Task(task_id="t1", task_type="deploy", lease_ttl=0))
    sim.assign_task("t1", "a1")
    sim.tick(1)
    assert sim.tasks["t1"].status == "queued"


def test_double_completion_counted_once():
    # Regression: completing a finished task again used to count it twice.
    sim = Simulation()
    sim.add_task(Task(task_id="t1", task_type="deploy"))
    sim.assign_task("t1", "a1")
    assert sim.complete_task("t1") is True
    assert sim.complete_task("t1") is False
    assert sim.metrics.completed_tasks == 1


def test_complete_queued_task_rejected():
    sim = Simulation()
    sim.add_task(Task(task_id="t1", task_type="deploy"))
    assert sim.complete_task("t1") is False
    assert sim.tasks["t1"].status == "queued"
    assert sim.metrics.completed_tasks == 0


def test_stale_owner_cannot_complete_reassigned_task():
    sim = Simulation()
    sim.add_task(Task(task_id="t1", task_type="deploy", lease_ttl=10))
    sim.assign_task("t1", "a1")
    sim.tick(10)  # a1's lease expires
    sim.assign_task("t1", "a2")
    assert sim.complete_task("t1", agent_id="a1") is False
    assert sim.tasks["t1"].owner == "a2"
    assert sim.complete_task("t1", agent_id="a2") is True


def test_requeue_finished_task_rejected():
    sim = Simulation()
    sim.add_task(Task(task_id="t1", task_type="deploy"))
    sim.assign_task("t1", "a1")
    sim.complete_task("t1")
    assert sim.requeue_task("t1") is False
    assert sim.tasks["t1"].status == "done"
    assert sim.metrics.reassigned_tasks == 0


def test_requeue_by_non_owner_rejected():
    sim = Simulation()
    sim.add_task(Task(task_id="t1", task_type="deploy"))
    sim.assign_task("t1", "a1")
    assert sim.requeue_task("t1", agent_id="a2") is False
    assert sim.tasks["t1"].status == "running"
