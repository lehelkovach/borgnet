"""Unit tests for security primitives."""

import time

from borgnet.security import (
    EnvelopeVerifier,
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

    def test_signature_covers_payload(self):
        # Tampering with the payload after signing must invalidate the signature.
        env = SignedEnvelope(
            goal_id="goal-1", origin_id="agent-a", payload={"action": "read"}
        )
        env.compute_signature("secret")
        assert env.verify_signature("secret") is True
        env.payload["action"] = "delete_everything"
        assert env.verify_signature("secret") is False

    def test_signature_covers_chain_of_custody(self):
        # Tampering with provenance must invalidate the signature.
        env = SignedEnvelope(
            goal_id="goal-1", origin_id="agent-a", chain_of_custody=["agent-a"]
        )
        env.compute_signature("secret")
        env.chain_of_custody.append("attacker")
        assert env.verify_signature("secret") is False

    def test_signature_covers_expiry(self):
        # Extending the expiry after signing must invalidate the signature.
        env = SignedEnvelope(
            goal_id="goal-1", origin_id="agent-a", expires_at=time.time() + 10
        )
        env.compute_signature("secret")
        env.expires_at = time.time() + 10_000
        assert env.verify_signature("secret") is False


class TestEnvelopeVerifier:
    def test_accepts_fresh_signed_envelope(self):
        env = SignedEnvelope(goal_id="goal-1", origin_id="agent-a")
        env.compute_signature("secret")
        verifier = EnvelopeVerifier("secret")
        assert verifier.verify(env) is True

    def test_rejects_bad_signature(self):
        env = SignedEnvelope(goal_id="goal-1", origin_id="agent-a")
        env.compute_signature("secret")
        assert EnvelopeVerifier("wrong-secret").verify(env) is False

    def test_rejects_replayed_nonce(self):
        env = SignedEnvelope(goal_id="goal-1", origin_id="agent-a")
        env.compute_signature("secret")
        verifier = EnvelopeVerifier("secret")
        assert verifier.verify(env) is True
        # Replaying the identical, validly signed envelope must be rejected.
        assert verifier.verify(env) is False

    def test_rejects_expired_envelope(self):
        env = SignedEnvelope(
            goal_id="goal-1", origin_id="agent-a", expires_at=time.time() - 1
        )
        env.compute_signature("secret")
        assert EnvelopeVerifier("secret").verify(env) is False

    def test_distinct_nonces_both_accepted(self):
        verifier = EnvelopeVerifier("secret")
        for _ in range(2):
            env = SignedEnvelope(goal_id="goal-1", origin_id="agent-a")
            env.compute_signature("secret")
            assert verifier.verify(env) is True


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


class TestQuorumIntegrity:
    """Regression tests for quorum vote validation and finality."""

    def test_roster_rejects_unknown_voters(self):
        qm = QuorumManager(required_votes=2, voters=["a", "b", "c"])
        assert qm.vote("p", "sybil-1", approve=True) is False
        assert qm.vote("p", "sybil-2", approve=True) is False
        assert qm.commit("p") is False
        assert qm.vote("p", "a", approve=True) is True
        assert qm.vote("p", "b", approve=True) is True
        assert qm.commit("p") is True

    def test_roster_sets_total_voters(self):
        qm = QuorumManager(required_votes=3, voters=["a", "b", "c", "d"])
        assert qm.total_voters == 4

    def test_without_roster_vote_count_is_capped(self):
        qm = QuorumManager(required_votes=2, total_voters=3)
        for voter in ["a", "b", "c"]:
            assert qm.vote("p", voter, approve=False) is True
        assert qm.vote("p", "d", approve=False) is False
        assert qm.tally("p")["total"] == 3

    def test_existing_voter_can_change_vote_at_cap(self):
        qm = QuorumManager(required_votes=2, total_voters=2)
        qm.vote("p", "a", approve=False)
        qm.vote("p", "b", approve=True)
        assert qm.vote("p", "a", approve=True) is True
        assert qm.commit("p") is True

    def test_rejected_proposal_cannot_be_committed(self):
        qm = QuorumManager(required_votes=2, voters=["a", "b", "c"])
        qm.vote("p", "a", approve=False)
        qm.vote("p", "b", approve=False)
        assert qm.reject("p") is True
        assert qm.vote("p", "c", approve=True) is False
        assert qm.commit("p") is False
        assert "p" not in qm.committed

    def test_committed_proposal_cannot_be_rejected(self):
        qm = QuorumManager(required_votes=2, voters=["a", "b", "c"])
        qm.vote("p", "a", approve=True)
        qm.vote("p", "b", approve=True)
        assert qm.commit("p") is True
        assert qm.vote("p", "c", approve=False) is False
        assert qm.reject("p") is False
        assert qm.is_final("p")

    def test_invalid_required_votes_raises(self):
        for required, total in [(0, 3), (4, 3)]:
            try:
                QuorumManager(required_votes=required, total_voters=total)
                assert False, "expected ValueError"
            except ValueError:
                pass
