"""Security primitives: signatures, quorum, and trust scoring."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from borgnet.logging import get_logger

_log = get_logger("security")


@dataclass
class SignedEnvelope:
    """
    A signed message envelope with provenance.

    Includes origin chain, nonce, timestamps, and HMAC signature.
    """

    goal_id: str
    origin_id: str
    parent_goal_id: Optional[str] = None
    chain_of_custody: List[str] = field(default_factory=list)
    nonce: str = field(default_factory=lambda: uuid.uuid4().hex)
    issued_at: float = field(default_factory=time.time)
    expires_at: Optional[float] = None
    payload: Dict[str, Any] = field(default_factory=dict)
    signature: Optional[str] = None

    def _signing_bytes(self) -> bytes:
        """Canonical, order-stable serialization of all integrity-relevant fields.

        The signature must cover the ENTIRE envelope, not just a few header
        fields, so that tampering with the payload, the provenance chain, or
        the expiry is detected. Fields are sorted for a deterministic result.
        """
        canonical = {
            "goal_id": self.goal_id,
            "origin_id": self.origin_id,
            "parent_goal_id": self.parent_goal_id,
            "chain_of_custody": list(self.chain_of_custody),
            "nonce": self.nonce,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "payload": self.payload,
        }
        return json.dumps(
            canonical, sort_keys=True, separators=(",", ":"), default=str
        ).encode()

    def compute_signature(self, secret: str) -> str:
        """Compute HMAC-SHA256 signature over the full envelope."""
        sig = hmac.new(
            secret.encode(), self._signing_bytes(), hashlib.sha256
        ).hexdigest()
        self.signature = sig
        _log.debug(
            "Signature computed: goal=%s origin=%s sig=%s...",
            self.goal_id,
            self.origin_id,
            sig[:16],
        )
        return sig

    def verify_signature(self, secret: str) -> bool:
        """Verify the HMAC signature over the full envelope."""
        expected = hmac.new(
            secret.encode(), self._signing_bytes(), hashlib.sha256
        ).hexdigest()
        valid = hmac.compare_digest(self.signature or "", expected)
        if valid:
            _log.debug("Signature verified: goal=%s origin=%s", self.goal_id, self.origin_id)
        else:
            _log.warning(
                "Signature verification failed: goal=%s origin=%s",
                self.goal_id,
                self.origin_id,
            )
        return valid

    def is_expired(self) -> bool:
        """Check if envelope has expired."""
        if self.expires_at is None:
            return False
        expired = time.time() > self.expires_at
        if expired:
            _log.debug(
                "Envelope expired: goal=%s expires_at=%.0f now=%.0f",
                self.goal_id,
                self.expires_at,
                time.time(),
            )
        return expired


class EnvelopeVerifier:
    """Stateful verifier enforcing signature, expiry, and replay protection.

    A valid signature alone does not make an envelope safe to act on: a
    captured envelope can be replayed verbatim, and its signature still
    verifies. This verifier rejects an envelope whose signature is invalid,
    whose expiry has passed, or whose nonce has already been accepted.
    """

    def __init__(self, secret: str):
        self._secret = secret
        self._seen_nonces: Set[str] = set()

    def verify(self, envelope: "SignedEnvelope") -> bool:
        """Return True only for a fresh, unexpired, correctly signed envelope."""
        if not envelope.verify_signature(self._secret):
            return False
        if envelope.is_expired():
            _log.warning(
                "Envelope rejected (expired): goal=%s origin=%s",
                envelope.goal_id,
                envelope.origin_id,
            )
            return False
        if envelope.nonce in self._seen_nonces:
            _log.warning(
                "Envelope rejected (replayed nonce): goal=%s origin=%s nonce=%s",
                envelope.goal_id,
                envelope.origin_id,
                envelope.nonce,
            )
            return False
        self._seen_nonces.add(envelope.nonce)
        return True


@dataclass
class Vote:
    """A vote on a proposal."""

    voter_id: str
    proposal_id: str
    approve: bool
    timestamp: float = field(default_factory=time.time)


class QuorumManager:
    """
    Manage quorum-based approvals for high-impact actions.

    Proposals require N-of-M votes before committing.
    """

    def __init__(self, required_votes: int = 2, total_voters: int = 3):
        self.required_votes = required_votes
        self.total_voters = total_voters
        self.proposals: Dict[str, Dict[str, Vote]] = {}
        self.committed: Set[str] = set()
        self.rejected: Set[str] = set()
        _log.debug(
            "QuorumManager initialized: required=%d total=%d",
            required_votes,
            total_voters,
        )

    def create_proposal(self, proposal_id: str) -> None:
        """Create a new proposal awaiting votes."""
        if proposal_id not in self.proposals:
            self.proposals[proposal_id] = {}
            _log.info("Proposal created: id=%s", proposal_id)

    def vote(self, proposal_id: str, voter_id: str, approve: bool) -> None:
        """Cast a vote on a proposal."""
        if proposal_id not in self.proposals:
            self.create_proposal(proposal_id)

        self.proposals[proposal_id][voter_id] = Vote(
            voter_id=voter_id, proposal_id=proposal_id, approve=approve
        )
        _log.info(
            "Vote cast: proposal=%s voter=%s approve=%s",
            proposal_id,
            voter_id,
            approve,
        )

    def tally(self, proposal_id: str) -> Dict[str, int]:
        """Count votes for a proposal."""
        votes = self.proposals.get(proposal_id, {})
        approvals = sum(1 for v in votes.values() if v.approve)
        rejections = sum(1 for v in votes.values() if not v.approve)
        result = {"approvals": approvals, "rejections": rejections, "total": len(votes)}
        _log.debug("Vote tally: proposal=%s %s", proposal_id, result)
        return result

    def is_quorum_reached(self, proposal_id: str) -> bool:
        """Check if quorum is reached for approval."""
        tally = self.tally(proposal_id)
        reached = tally["approvals"] >= self.required_votes
        if reached:
            _log.debug("Quorum reached: proposal=%s approvals=%d", proposal_id, tally["approvals"])
        return reached

    def is_rejected(self, proposal_id: str) -> bool:
        """Check if proposal is definitively rejected."""
        tally = self.tally(proposal_id)
        remaining = self.total_voters - tally["total"]
        max_possible = tally["approvals"] + remaining
        rejected = max_possible < self.required_votes
        if rejected:
            _log.debug(
                "Proposal definitively rejected: proposal=%s max_possible=%d required=%d",
                proposal_id,
                max_possible,
                self.required_votes,
            )
        return rejected

    def commit(self, proposal_id: str) -> bool:
        """Commit a proposal if quorum reached."""
        if self.is_quorum_reached(proposal_id):
            self.committed.add(proposal_id)
            _log.info("Proposal committed: id=%s", proposal_id)
            return True
        _log.debug("Commit failed (no quorum): proposal=%s", proposal_id)
        return False

    def reject(self, proposal_id: str) -> bool:
        """Reject a proposal if not enough votes possible."""
        if self.is_rejected(proposal_id):
            self.rejected.add(proposal_id)
            _log.info("Proposal rejected: id=%s", proposal_id)
            return True
        return False


@dataclass
class TrustScore:
    """Trust score for an agent."""

    agent_id: str
    score: float = 1.0
    successes: int = 0
    failures: int = 0
    anomalies: int = 0
    last_updated: float = field(default_factory=time.time)

    def record_success(self) -> None:
        """Record a successful action."""
        old_score = self.score
        self.successes += 1
        self.score = min(2.0, self.score + 0.1)
        self.last_updated = time.time()
        _log.debug(
            "Trust success: agent=%s old=%.2f new=%.2f total_successes=%d",
            self.agent_id,
            old_score,
            self.score,
            self.successes,
        )

    def record_failure(self) -> None:
        """Record a failed action."""
        old_score = self.score
        self.failures += 1
        self.score = max(0.0, self.score - 0.2)
        self.last_updated = time.time()
        _log.warning(
            "Trust failure: agent=%s old=%.2f new=%.2f total_failures=%d",
            self.agent_id,
            old_score,
            self.score,
            self.failures,
        )

    def record_anomaly(self) -> None:
        """Record an anomalous/suspicious action."""
        old_score = self.score
        self.anomalies += 1
        self.score = max(0.0, self.score - 0.5)
        self.last_updated = time.time()
        _log.error(
            "Trust anomaly: agent=%s old=%.2f new=%.2f total_anomalies=%d",
            self.agent_id,
            old_score,
            self.score,
            self.anomalies,
        )

    def is_trusted(self, threshold: float = 0.5) -> bool:
        """Check if agent is trusted above threshold."""
        trusted = self.score >= threshold
        _log.debug(
            "Trust check: agent=%s score=%.2f threshold=%.2f trusted=%s",
            self.agent_id,
            self.score,
            threshold,
            trusted,
        )
        return trusted


class TrustRegistry:
    """Registry of trust scores for all agents."""

    def __init__(self, default_score: float = 1.0, quarantine_threshold: float = 0.3):
        self.scores: Dict[str, TrustScore] = {}
        self.default_score = default_score
        self.quarantine_threshold = quarantine_threshold
        self.quarantined: Set[str] = set()
        _log.debug(
            "TrustRegistry initialized: default=%.2f quarantine_threshold=%.2f",
            default_score,
            quarantine_threshold,
        )

    def get_or_create(self, agent_id: str) -> TrustScore:
        """Get or create a trust score for an agent."""
        if agent_id not in self.scores:
            self.scores[agent_id] = TrustScore(
                agent_id=agent_id, score=self.default_score
            )
            _log.info("Trust score created: agent=%s score=%.2f", agent_id, self.default_score)
        return self.scores[agent_id]

    def record_success(self, agent_id: str) -> None:
        """Record success for an agent."""
        self.get_or_create(agent_id).record_success()

    def record_failure(self, agent_id: str) -> None:
        """Record failure for an agent."""
        self.get_or_create(agent_id).record_failure()
        self._check_quarantine(agent_id)

    def record_anomaly(self, agent_id: str) -> None:
        """Record anomaly for an agent."""
        self.get_or_create(agent_id).record_anomaly()
        self._check_quarantine(agent_id)

    def _check_quarantine(self, agent_id: str) -> None:
        """Quarantine agent if score drops too low."""
        score = self.scores.get(agent_id)
        if score and score.score < self.quarantine_threshold:
            if agent_id not in self.quarantined:
                self.quarantined.add(agent_id)
                _log.warning(
                    "Agent quarantined: id=%s score=%.2f threshold=%.2f",
                    agent_id,
                    score.score,
                    self.quarantine_threshold,
                )

    def is_quarantined(self, agent_id: str) -> bool:
        """Check if agent is quarantined."""
        quarantined = agent_id in self.quarantined
        if quarantined:
            _log.debug("Agent is quarantined: id=%s", agent_id)
        return quarantined

    def rehabilitate(self, agent_id: str) -> None:
        """Remove agent from quarantine."""
        if agent_id in self.quarantined:
            self.quarantined.discard(agent_id)
            _log.info("Agent rehabilitated: id=%s", agent_id)

    def snapshot(self) -> Dict[str, Any]:
        """Return registry state."""
        avg_score = (
            sum(s.score for s in self.scores.values()) / len(self.scores)
            if self.scores
            else 0.0
        )
        return {
            "agent_count": len(self.scores),
            "quarantined_count": len(self.quarantined),
            "average_score": avg_score,
        }
