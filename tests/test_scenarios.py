"""Tests for the scenario harness and the properties it measures."""

import random

import pytest

from borgnet.scenarios import (
    Scenario,
    default_suite,
    format_markdown,
    main,
    run_scenario,
    run_suite,
)

CRASHES = ((10, 2), (20, 1))


def _run(**kwargs):
    kwargs.setdefault("tasks", 80)
    return run_scenario(Scenario(name="test", **kwargs))


def test_runs_are_deterministic_and_restore_global_random():
    random.seed(123)
    expected_next = random.random()
    random.seed(123)
    first = _run(crashes=CRASHES, adversaries=1, respawn=True, seed=7)
    assert random.random() == expected_next
    second = _run(crashes=CRASHES, adversaries=1, respawn=True, seed=7)
    assert first == second


def test_baseline_finishes_every_task():
    report = _run()
    assert report.finished == report.tasks
    assert report.orphaned == 0
    assert report.recovery_rate == 1.0
    assert report.boundary_attempts == 0


def test_crashed_agents_work_is_recovered():
    report = _run(crashes=CRASHES)
    assert report.orphaned > 0
    assert report.recovered == report.orphaned
    assert report.agents_lost == 3
    assert report.finished == report.tasks


def test_heartbeats_reclaim_orphans_faster_than_lease_expiry():
    with_heartbeats = _run(crashes=CRASHES, presence_ttl=2, lease_ttl=12)
    lease_only = _run(crashes=CRASHES, presence_ttl=None, lease_ttl=12)
    assert with_heartbeats.mean_reclaim_ticks < lease_only.mean_reclaim_ticks


def test_coordinator_outage_stalls_only_the_central_queue():
    outage = (10, 30)
    central = _run(coordination="central", coordinator_outage=outage)
    stigmergy = _run(coordination="stigmergy", coordinator_outage=outage)
    assert central.ticks > stigmergy.ticks


def test_authorized_respawn_stays_within_budget():
    report = _run(crashes=CRASHES, respawn=True)
    assert report.authorized_spawn_requests == 3
    assert report.authorized_spawns == 3
    assert report.uncontrolled_spawns == 0


@pytest.mark.parametrize("coordination", ["stigmergy", "central"])
def test_adversaries_never_break_the_rules_and_get_quarantined(coordination):
    report = _run(
        coordination=coordination, adversaries=2, crashes=CRASHES, respawn=True, tasks=120
    )
    assert report.boundary_attempts > 0
    assert report.boundary_violations == 0
    assert report.unauthorized_spawn_attempts > 0
    assert report.uncontrolled_spawns == 0
    assert report.adversaries_quarantined == report.adversaries == 2


def test_adoption_cap_limits_poisoning_damage():
    seeds = range(4)
    common = dict(name="poison", adversaries=2, crashes=CRASHES, respawn=True, tasks=120)
    capped = run_suite([Scenario(**common)], seeds)[0]
    uncapped = run_suite([Scenario(**common, cap_adopted_fitness=False)], seeds)[0]
    assert capped.honest_quarantined < uncapped.honest_quarantined
    assert capped.task_success_rate > uncapped.task_success_rate


def test_invalid_scenarios_raise():
    with pytest.raises(ValueError):
        Scenario(name="x", coordination="mesh")
    with pytest.raises(ValueError):
        Scenario(name="x", agents=2, crashes=((5, 3),))


def test_suite_formats_and_cli_runs(capsys):
    rows = run_suite(default_suite()[:2], seeds=[0])
    table = format_markdown(rows)
    assert "baseline/stigmergy" in table and "node-loss/stigmergy" in table
    assert main(["--seeds", "1", "--json"]) == 0
    assert '"scenario": "baseline/stigmergy"' in capsys.readouterr().out
