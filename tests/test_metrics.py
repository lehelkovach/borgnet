"""Unit tests for metrics module."""

from borgnet.metrics import Metrics


def test_metrics_defaults():
    m = Metrics()
    assert m.completed_tasks == 0
    assert m.failed_tasks == 0
    assert m.reassigned_tasks == 0
    assert m.active_agents == 0
    assert m.total_tasks == 0


def test_task_completed_increments():
    m = Metrics()
    m.task_completed()
    m.task_completed()
    assert m.completed_tasks == 2


def test_task_failed_increments():
    m = Metrics()
    m.task_failed()
    assert m.failed_tasks == 1


def test_task_reassigned_increments():
    m = Metrics()
    m.task_reassigned()
    m.task_reassigned()
    m.task_reassigned()
    assert m.reassigned_tasks == 3


def test_snapshot_returns_dict():
    m = Metrics()
    m.completed_tasks = 5
    m.failed_tasks = 2
    m.active_agents = 3
    m.total_tasks = 10
    m.notes["custom_metric"] = 42.0

    snap = m.snapshot()
    assert snap["completed_tasks"] == 5.0
    assert snap["failed_tasks"] == 2.0
    assert snap["active_agents"] == 3.0
    assert snap["total_tasks"] == 10.0
    assert snap["custom_metric"] == 42.0
