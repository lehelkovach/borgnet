"""Unit tests for security primitives."""

import time

from borgnet.security import (
    QuorumManager,
    SignedEnvelope,
    TrustRegistry,
    TrustScore,
)


class TestSignedEnvelope:
    def test_compute_signature(self):
        env = SignedEnvelope(goal_id="goal-1", origin_id="agent-a")
        sig = env.compute_signature("secret")
        assert sig is not None
        assert env.signature == sig

    def test_verify_signature_valid(self):
        env = SignedEnvelope(goal_id="goal-1", origin_id="agent-a")
        env.compute_signature("secret")
        assert env.verify_signature("secret") is True

    def test_verify_signature_invalid(self):
        env = SignedEnvelope(goal_id="goal-1", origin_id="agent-a")
        env.compute_signature("secret")
        assert env.verify_signature("wrong-secret") is False

    def test_is_expired(self):
        env = SignedEnvelope(
            goal_id="goal-1",
            origin_id="agent-a",
            expires_at=time.time() - 10,  # Already expired
        )
        assert env.is_expired() is True

    def test_is_not_expired(self):
        env = SignedEnvelope(
            goal_id="goal-1",
            origin_id="agent-a",
            expires_at=time.time() + 3600,
        )
        assert env.is_expired() is False

    def test_no_expiry(self):
        env = SignedEnvelope(goal_id="goal-1", origin_id="agent-a")
        assert env.is_expired() is False


class TestQuorumManager:
    def test_create_proposal(self):
        qm = QuorumManager(required_votes=2, total_voters=3)
        qm.create_proposal("prop-1")
        assert "prop-1" in qm.proposals

    def test_vote(self):
        qm = QuorumManager(required_votes=2, total_voters=3)
        qm.vote("prop-1", "voter-a", approve=True)
        qm.vote("prop-1", "voter-b", approve=True)
        
        tally = qm.tally("prop-1")
        assert tally["approvals"] == 2

    def test_quorum_reached(self):
        qm = QuorumManager(required_votes=2, total_voters=3)
        qm.vote("prop-1", "voter-a", approve=True)
        qm.vote("prop-1", "voter-b", approve=True)
        
        assert qm.is_quorum_reached("prop-1") is True

    def test_quorum_not_reached(self):
        qm = QuorumManager(required_votes=2, total_voters=3)
        qm.vote("prop-1", "voter-a", approve=True)
        
        assert qm.is_quorum_reached("prop-1") is False

    def test_is_rejected(self):
        qm = QuorumManager(required_votes=2, total_voters=3)
        qm.vote("prop-1", "voter-a", approve=False)
        qm.vote("prop-1", "voter-b", approve=False)
        
        assert qm.is_rejected("prop-1") is True

    def test_commit(self):
        qm = QuorumManager(required_votes=2, total_voters=3)
        qm.vote("prop-1", "voter-a", approve=True)
        qm.vote("prop-1", "voter-b", approve=True)
        
        assert qm.commit("prop-1") is True
        assert "prop-1" in qm.committed


class TestTrustScore:
    def test_record_success(self):
        ts = TrustScore(agent_id="agent-a", score=1.0)
        ts.record_success()
        
        assert ts.successes == 1
        assert ts.score > 1.0

    def test_record_failure(self):
        ts = TrustScore(agent_id="agent-a", score=1.0)
        ts.record_failure()
        
        assert ts.failures == 1
        assert ts.score < 1.0

    def test_record_anomaly(self):
        ts = TrustScore(agent_id="agent-a", score=1.0)
        ts.record_anomaly()
        
        assert ts.anomalies == 1
        assert ts.score < 0.6

    def test_is_trusted(self):
        ts = TrustScore(agent_id="agent-a", score=1.0)
        assert ts.is_trusted(threshold=0.5) is True
        
        ts.score = 0.3
        assert ts.is_trusted(threshold=0.5) is False


class TestTrustRegistry:
    def test_get_or_create(self):
        registry = TrustRegistry()
        ts = registry.get_or_create("agent-a")
        
        assert ts.agent_id == "agent-a"
        assert "agent-a" in registry.scores

    def test_record_success(self):
        registry = TrustRegistry()
        registry.record_success("agent-a")
        
        assert registry.scores["agent-a"].successes == 1

    def test_quarantine_on_low_score(self):
        registry = TrustRegistry(quarantine_threshold=0.5)
        registry.get_or_create("agent-a")
        
        # Multiple anomalies to drop score
        for _ in range(5):
            registry.record_anomaly("agent-a")
        
        assert registry.is_quarantined("agent-a") is True

    def test_rehabilitate(self):
        registry = TrustRegistry(quarantine_threshold=0.5)
        registry.quarantined.add("agent-a")
        
        registry.rehabilitate("agent-a")
        assert registry.is_quarantined("agent-a") is False

    def test_snapshot(self):
        registry = TrustRegistry()
        registry.get_or_create("agent-a")
        registry.get_or_create("agent-b")
        
        snap = registry.snapshot()
        assert snap["agent_count"] == 2
        assert snap["quarantined_count"] == 0
