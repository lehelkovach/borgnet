"""Peer-to-peer strategy transmission between agents (roadmap item 2).

Each agent keeps its own :class:`~borgnet.memetic.StrategyPool`. A
:class:`PeerExchange` is the horizontal channel between them: an agent offers
its best strategy to its peers, and each receiver decides for itself whether
to adopt it.

Adoption is gated on trust in the sender. Strategies from quarantined or
poorly trusted agents do not spread. An adopted strategy also starts with a
discounted fitness, because the sender reports its own fitness: the strategy
has to prove itself through the receiver's own results before it dominates
the receiver's selection.

This exchange runs in-process. Carrying offers over the IAC Bus belongs to
roadmap item 3.
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from borgnet.logging import get_logger
from borgnet.memetic import Strategy, StrategyPool
from borgnet.security import TrustRegistry

_log = get_logger("propagation")

ADOPTED = "adopted"
REJECT_SELF = "self"
REJECT_UNKNOWN_SENDER = "unknown_sender"
REJECT_QUARANTINED = "sender_quarantined"
REJECT_UNTRUSTED = "sender_untrusted"
REJECT_DUPLICATE = "already_known"
REJECT_NOT_BETTER = "not_better"


@dataclass(frozen=True)
class StrategyOffer:
    """A snapshot of one strategy, offered by one agent to its peers."""

    sender_id: str
    strategy_id: str
    params: Dict[str, Any]
    fitness: float
    generation: int

    @classmethod
    def from_strategy(cls, sender_id: str, strategy: Strategy) -> "StrategyOffer":
        return cls(
            sender_id=sender_id,
            strategy_id=strategy.strategy_id,
            params=dict(strategy.params),
            fitness=strategy.fitness,
            generation=strategy.generation,
        )


@dataclass(frozen=True)
class AdoptionPolicy:
    """Rules a receiver applies to every offer.

    Attributes:
        min_sender_trust: The sender's trust score must be at least this.
        fitness_margin: The offer's fitness must beat the receiver's best
            strategy by more than this.
        prior_weight: An adopted strategy starts at the offered fitness times
            this factor, between 0 and 1.
    """

    min_sender_trust: float = 0.8
    fitness_margin: float = 0.0
    prior_weight: float = 0.5

    def __post_init__(self) -> None:
        if not 0.0 <= self.prior_weight <= 1.0:
            raise ValueError(f"prior_weight must be in [0, 1], got {self.prior_weight}")
        if self.fitness_margin < 0.0:
            raise ValueError(f"fitness_margin must be >= 0, got {self.fitness_margin}")


class PeerExchange:
    """In-process horizontal channel for sharing strategies between agents.

    Agents :meth:`join` with their own pool. :meth:`share` offers one agent's
    best strategy to its peers, either all of them or ``fanout`` peers chosen
    at random. :meth:`gossip_round` lets every member share once.
    """

    def __init__(
        self,
        trust: TrustRegistry,
        policy: Optional[AdoptionPolicy] = None,
        fanout: Optional[int] = None,
        rng: Optional[random.Random] = None,
    ):
        if fanout is not None and fanout < 1:
            raise ValueError(f"fanout must be >= 1, got {fanout}")
        self.trust = trust
        self.policy = policy or AdoptionPolicy()
        self.fanout = fanout
        self.rng = rng or random.Random()
        self.pools: Dict[str, StrategyPool] = {}
        self.outcomes: Counter = Counter()
        _log.debug(
            "PeerExchange initialized: policy=%s fanout=%s", self.policy, fanout
        )

    def join(self, agent_id: str, pool: StrategyPool) -> None:
        """Add an agent and the pool it adopts strategies into."""
        self.pools[agent_id] = pool
        _log.info("Agent joined exchange: id=%s", agent_id)

    def leave(self, agent_id: str) -> None:
        """Remove an agent. Its pool is left untouched."""
        if self.pools.pop(agent_id, None) is not None:
            _log.info("Agent left exchange: id=%s", agent_id)

    def evaluate(self, receiver_id: str, offer: StrategyOffer) -> str:
        """Return ``"adopted"`` if ``receiver_id`` should adopt, else the reason not to."""
        pool = self.pools[receiver_id]
        if offer.sender_id == receiver_id:
            return REJECT_SELF
        if offer.sender_id not in self.pools:
            return REJECT_UNKNOWN_SENDER
        if self.trust.is_quarantined(offer.sender_id):
            return REJECT_QUARANTINED
        if self.trust.get_or_create(offer.sender_id).score < self.policy.min_sender_trust:
            return REJECT_UNTRUSTED
        if any(s.params == offer.params for s in pool.strategies.values()):
            return REJECT_DUPLICATE
        best = pool.best()
        if best is not None and offer.fitness <= best.fitness + self.policy.fitness_margin:
            return REJECT_NOT_BETTER
        return ADOPTED

    def offer(self, receiver_id: str, offer: StrategyOffer) -> bool:
        """Deliver one offer. Returns True if the receiver adopted it."""
        outcome = self.evaluate(receiver_id, offer)
        self.outcomes[outcome] += 1
        if outcome != ADOPTED:
            _log.debug(
                "Offer rejected: receiver=%s sender=%s strategy=%s reason=%s",
                receiver_id,
                offer.sender_id,
                offer.strategy_id,
                outcome,
            )
            return False

        adopted = Strategy(
            params=dict(offer.params),
            fitness=offer.fitness * self.policy.prior_weight,
            source_agent=offer.sender_id,
            generation=offer.generation + 1,
        )
        self.pools[receiver_id].add_strategy(adopted)
        _log.info(
            "Strategy adopted: receiver=%s sender=%s offered=%s new=%s fitness=%.3f",
            receiver_id,
            offer.sender_id,
            offer.strategy_id,
            adopted.strategy_id,
            adopted.fitness,
        )
        return True

    def share(self, sender_id: str) -> List[str]:
        """Offer ``sender_id``'s best strategy to its peers.

        Returns the ids of the peers that adopted it.
        """
        best = self.pools[sender_id].best()
        if best is None:
            return []
        peers = sorted(a for a in self.pools if a != sender_id)
        if self.fanout is not None and self.fanout < len(peers):
            peers = self.rng.sample(peers, self.fanout)
        offer = StrategyOffer.from_strategy(sender_id, best)
        return [peer for peer in peers if self.offer(peer, offer)]

    def gossip_round(self) -> Dict[str, List[str]]:
        """Let every member share once, in id order. Maps sender to adopters."""
        return {sender: self.share(sender) for sender in sorted(self.pools)}
