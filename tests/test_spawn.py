"""Tests for spawn budgets and authorized replication."""

import pytest

from borgnet.agent import AgentRunner, StubWorker
from borgnet.memetic import StrategyPool
from borgnet.security import EnvelopeVerifier, SignedEnvelope, TrustRegistry
from borgnet.sim import Agent, Simulation, Task
from borgnet.spawn import SpawnBudget, SpawnController, authorize_spawn
from borgnet.stigmergy import DemandMap

KEY = "control-plane-key"


def _setup(budget=None, roots=("a1",), trust=None):
    sim = Simulation(trust=trust)
    for agent_id in roots:
        sim.add_agent(Agent(agent_id=agent_id, role="worker", capabilities=["build"]))
    verifier = EnvelopeVerifier(
        keys={"control-plane": KEY}, max_age_s=60, clock=lambda: float(sim.now)
    )
    controller = SpawnController(
        sim, budget or SpawnBudget(max_agents=10), verifier, trust=trust
    )
    return sim, controller


def _auth(sim, parent="a1", count=1, key=KEY, **kwargs):
    return authorize_spawn(parent, count, key, issued_at=float(sim.now), **kwargs)


class TestAuthorization:
    def test_authorized_spawn_creates_children(self):
        sim, controller = _setup()
        result = controller.request("a1", _auth(sim, count=2))
        assert result.ok
        assert result.children == ("a1/1", "a1/2")
        child = sim.agents["a1/1"]
        assert child.role == "worker" and child.capabilities == ["build"]
        assert controller.lineage("a1/2") == ["a1/2", "a1"]
        assert controller.unaccounted(["a1"]) == set()

    def test_forged_signature_rejected(self):
        sim, controller = _setup()
        result = controller.request("a1", _auth(sim, key="stolen-guess"))
        assert result.outcome == "unauthorized"
        assert set(sim.agents) == {"a1"}

    def test_self_authorization_rejected(self):
        sim, controller = _setup()
        # An agent signing its own authorization is not the control plane.
        forged = authorize_spawn("a1", 1, "a1-key", authority_id="a1", issued_at=0.0)
        assert controller.request("a1", forged).outcome == "unauthorized"

    def test_replayed_authorization_rejected(self):
        sim, controller = _setup()
        auth = _auth(sim)
        assert controller.request("a1", auth).ok
        assert controller.request("a1", auth).outcome == "unauthorized"
        assert len(controller.spawned) == 1

    def test_expired_authorization_rejected(self):
        sim, controller = _setup()
        auth = _auth(sim, valid_for=5)
        sim.tick(6)
        assert controller.request("a1", auth).outcome == "unauthorized"

    def test_tampered_count_rejected(self):
        sim, controller = _setup()
        auth = _auth(sim, count=1)
        auth.payload["count"] = 5
        assert controller.request("a1", auth).outcome == "unauthorized"

    def test_authorization_for_another_parent_is_out_of_scope(self):
        sim, controller = _setup(roots=("a1", "a2"))
        assert controller.request("a2", _auth(sim, parent="a1")).outcome == "out_of_scope"

    @pytest.mark.parametrize("payload", [
        {"action": "delete", "parent": "a1", "count": 1},
        {"action": "spawn", "parent": "a1", "count": 0},
        {"action": "spawn", "parent": "a1", "count": "2"},
        {"action": "spawn", "parent": "a1", "count": True},
    ])
    def test_malformed_payload_is_out_of_scope(self, payload):
        sim, controller = _setup()
        env = SignedEnvelope(
            goal_id="g", origin_id="control-plane", issued_at=0.0, payload=payload
        )
        env.compute_signature(KEY)
        assert controller.request("a1", env).outcome == "out_of_scope"


class TestBudget:
    def test_unknown_parent(self):
        sim, controller = _setup()
        assert controller.request("ghost", _auth(sim, parent="ghost")).outcome == "unknown_parent"

    def test_quarantined_parent(self):
        trust = TrustRegistry()
        sim, controller = _setup(trust=trust)
        trust.record_anomaly("a1")
        trust.record_anomaly("a1")
        assert controller.request("a1", _auth(sim)).outcome == "parent_quarantined"

    def test_depth_limit(self):
        sim, controller = _setup(SpawnBudget(max_agents=10, max_depth=1))
        assert controller.request("a1", _auth(sim)).ok
        result = controller.request("a1/1", _auth(sim, parent="a1/1"))
        assert result.outcome == "depth_limit"

    def test_per_parent_limit_is_all_or_nothing(self):
        sim, controller = _setup(SpawnBudget(max_agents=10, max_children=2))
        assert controller.request("a1", _auth(sim, count=3)).outcome == "parent_limit"
        assert set(sim.agents) == {"a1"}

    def test_population_limit(self):
        sim, controller = _setup(SpawnBudget(max_agents=2, max_children=5))
        assert controller.request("a1", _auth(sim, count=2)).outcome == "population_limit"
        assert controller.request("a1", _auth(sim, count=1)).ok

    def test_invalid_budget_raises(self):
        with pytest.raises(ValueError):
            SpawnBudget(max_agents=0)
        with pytest.raises(ValueError):
            SpawnBudget(max_agents=5, child_ttl=0)


class TestLifetime:
    def test_expired_child_is_retired_and_cannot_rejoin(self):
        sim, controller = _setup(SpawnBudget(max_agents=10, child_ttl=5))
        (child,) = controller.request("a1", _auth(sim)).children
        sim.add_task(Task(task_id="t1", task_type="build", lease_ttl=60))
        sim.assign_task("t1", child)
        sim.tick(4)
        assert controller.retire_expired() == []
        sim.tick(1)
        assert controller.retire_expired() == [child]
        assert sim.tasks["t1"].status == "queued"
        runner = AgentRunner(
            Agent(agent_id=child), sim, StrategyPool(), DemandMap(), TrustRegistry(),
            StubWorker(),
        )
        assert runner.step().outcome == "retired"
        assert child not in sim.agents

    def test_retired_child_frees_parent_slot(self):
        sim, controller = _setup(SpawnBudget(max_agents=10, max_children=1, child_ttl=2))
        assert controller.request("a1", _auth(sim)).ok
        assert controller.request("a1", _auth(sim)).outcome == "parent_limit"
        sim.tick(2)
        controller.retire_expired()
        result = controller.request("a1", _auth(sim))
        assert result.ok and result.children == ("a1/2",)


def test_audit_finds_agents_that_bypassed_the_controller():
    sim, controller = _setup()
    controller.request("a1", _auth(sim))
    sim.add_agent(Agent(agent_id="rogue"))
    assert controller.unaccounted(["a1"]) == {"rogue"}
    assert controller.outcomes["spawned"] == 1
