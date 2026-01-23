"""Security primitives: signatures, quorum, and trust scoring."""

from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
import uuid


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

    def compute_signature(self, secret: str) -> str:
        """Compute HMAC-SHA256 signature."""
        data = f"{self.goal_id}:{self.origin_id}:{self.nonce}:{self.issued_at}"
        sig = hmac.new(secret.encode(), data.encode(), hashlib.sha256).hexdigest()
        self.signature = sig
        return sig

    def verify_signature(self, secret: str) -> bool:
        """Verify HMAC signature."""
        data = f"{self.goal_id}:{self.origin_id}:{self.nonce}:{self.issued_at}"
        expected = hmac.new(secret.encode(), data.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(self.signature or "", expected)

    def is_expired(self) -> bool:
        """Check if envelope has expired."""
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at


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
        self.proposals: Dict[str, Dict[str, Vote]] = {}  # proposal_id -> {voter_id: Vote}
        self.committed: Set[str] = set()
        self.rejected: Set[str] = set()

    def create_proposal(self, proposal_id: str) -> None:
        """Create a new proposal awaiting votes."""
        if proposal_id not in self.proposals:
            self.proposals[proposal_id] = {}

    def vote(self, proposal_id: str, voter_id: str, approve: bool) -> None:
        """Cast a vote on a proposal."""
        if proposal_id not in self.proposals:
            self.create_proposal(proposal_id)
        self.proposals[proposal_id][voter_id] = Vote(
            voter_id=voter_id, proposal_id=proposal_id, approve=approve
        )

    def tally(self, proposal_id: str) -> Dict[str, int]:
        """Count votes for a proposal."""
        votes = self.proposals.get(proposal_id, {})
        approvals = sum(1 for v in votes.values() if v.approve)
        rejections = sum(1 for v in votes.values() if not v.approve)
        return {"approvals": approvals, "rejections": rejections, "total": len(votes)}

    def is_quorum_reached(self, proposal_id: str) -> bool:
        """Check if quorum is reached for approval."""
        tally = self.tally(proposal_id)
        return tally["approvals"] >= self.required_votes

    def is_rejected(self, proposal_id: str) -> bool:
        """Check if proposal is definitively rejected."""
        tally = self.tally(proposal_id)
        remaining = self.total_voters - tally["total"]
        max_possible = tally["approvals"] + remaining
        return max_possible < self.required_votes

    def commit(self, proposal_id: str) -> bool:
        """Commit a proposal if quorum reached."""
        if self.is_quorum_reached(proposal_id):
            self.committed.add(proposal_id)
            return True
        return False

    def reject(self, proposal_id: str) -> bool:
        """Reject a proposal if not enough votes possible."""
        if self.is_rejected(proposal_id):
            self.rejected.add(proposal_id)
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
        self.successes += 1
        self.score = min(2.0, self.score + 0.1)
        self.last_updated = time.time()

    def record_failure(self) -> None:
        """Record a failed action."""
        self.failures += 1
        self.score = max(0.0, self.score - 0.2)
        self.last_updated = time.time()

    def record_anomaly(self) -> None:
        """Record an anomalous/suspicious action."""
        self.anomalies += 1
        self.score = max(0.0, self.score - 0.5)
        self.last_updated = time.time()

    def is_trusted(self, threshold: float = 0.5) -> bool:
        """Check if agent is trusted above threshold."""
        return self.score >= threshold


class TrustRegistry:
    """Registry of trust scores for all agents."""

    def __init__(self, default_score: float = 1.0, quarantine_threshold: float = 0.3):
        self.scores: Dict[str, TrustScore] = {}
        self.default_score = default_score
        self.quarantine_threshold = quarantine_threshold
        self.quarantined: Set[str] = set()

    def get_or_create(self, agent_id: str) -> TrustScore:
        """Get or create a trust score for an agent."""
        if agent_id not in self.scores:
            self.scores[agent_id] = TrustScore(agent_id=agent_id, score=self.default_score)
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
            self.quarantined.add(agent_id)

    def is_quarantined(self, agent_id: str) -> bool:
        """Check if agent is quarantined."""
        return agent_id in self.quarantined

    def rehabilitate(self, agent_id: str) -> None:
        """Remove agent from quarantine."""
        self.quarantined.discard(agent_id)

    def snapshot(self) -> Dict[str, Any]:
        """Return registry state."""
        return {
            "agent_count": len(self.scores),
            "quarantined_count": len(self.quarantined),
            "average_score": (
                sum(s.score for s in self.scores.values()) / len(self.scores)
                if self.scores else 0.0
            ),
        }
