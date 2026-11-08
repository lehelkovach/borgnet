"""Spawn budgets and authorized replication (part of roadmap item 5).

Agents may create new agents only through a :class:`SpawnController`, and
only with a signed authorization from the control plane. An authorization is
a :class:`~borgnet.security.SignedEnvelope` whose origin is the control plane
and whose payload is ``{"action": "spawn", "parent": <agent id>, "count": n}``.
:func:`authorize_spawn` builds one.

The controller checks the authorization before anything else, so a forged or
replayed request learns nothing about the budget. The
:class:`~borgnet.security.EnvelopeVerifier` checks the signature, freshness,
and nonce, so each authorization works once and expires. The controller then
checks the :class:`SpawnBudget` and spawns every requested child or none.

Spawned agents can be given a lifetime. :meth:`SpawnController.retire_expired`
retires children whose lifetime ran out, requeues their tasks, and keeps them
from rejoining. :meth:`SpawnController.unaccounted` lists members that neither
started as roots nor came through the controller, which is how an audit
detects replication that bypassed it.
"""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Set, Tuple

from borgnet.logging import get_logger
from borgnet.security import EnvelopeVerifier, SignedEnvelope, TrustRegistry
from borgnet.sim import Agent, Simulation

_log = get_logger("spawn")

DEFAULT_AUTHORITY = "control-plane"

SPAWNED = "spawned"
REJECT_UNAUTHORIZED = "unauthorized"
REJECT_OUT_OF_SCOPE = "out_of_scope"
REJECT_UNKNOWN_PARENT = "unknown_parent"
REJECT_PARENT_QUARANTINED = "parent_quarantined"
REJECT_DEPTH = "depth_limit"
REJECT_PARENT_LIMIT = "parent_limit"
REJECT_POPULATION = "population_limit"


def authorize_spawn(
    parent_id: str,
    count: int,
    key: str,
    *,
    authority_id: str = DEFAULT_AUTHORITY,
    issued_at: Optional[float] = None,
    valid_for: float = 30.0,
) -> SignedEnvelope:
    """Build and sign a control-plane authorization for ``parent_id`` to spawn ``count`` agents."""
    issued = time.time() if issued_at is None else issued_at
    envelope = SignedEnvelope(
        goal_id=f"spawn:{parent_id}",
        origin_id=authority_id,
        issued_at=issued,
        expires_at=issued + valid_for,
        payload={"action": "spawn", "parent": parent_id, "count": count},
    )
    envelope.compute_signature(key)
    return envelope


@dataclass(frozen=True)
class SpawnBudget:
    """Limits on replication.

    Attributes:
        max_agents: Most members the simulation may hold after a spawn.
        max_children: Most live children one parent may have.
        max_depth: Most generations below a root agent. Roots are depth 0.
        child_ttl: Simulated seconds a spawned agent may live, or None.
    """

    max_agents: int
    max_children: int = 2
    max_depth: int = 2
    child_ttl: Optional[int] = None

    def __post_init__(self) -> None:
        if self.max_agents < 1:
            raise ValueError(f"max_agents must be >= 1, got {self.max_agents}")
        if self.max_children < 0:
            raise ValueError(f"max_children must be >= 0, got {self.max_children}")
        if self.max_depth < 0:
            raise ValueError(f"max_depth must be >= 0, got {self.max_depth}")
        if self.child_ttl is not None and self.child_ttl < 1:
            raise ValueError(f"child_ttl must be >= 1, got {self.child_ttl}")


@dataclass(frozen=True)
class SpawnResult:
    """What a spawn request did."""

    outcome: str
    children: Tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.outcome == SPAWNED


class SpawnController:
    """The only sanctioned way for agents to create agents."""

    def __init__(
        self,
        sim: Simulation,
        budget: SpawnBudget,
        verifier: EnvelopeVerifier,
        *,
        authority_id: str = DEFAULT_AUTHORITY,
        trust: Optional[TrustRegistry] = None,
    ):
        self.sim = sim
        self.budget = budget
        self.verifier = verifier
        self.authority_id = authority_id
        self.trust = trust
        self.parent_of: Dict[str, str] = {}
        self.depth: Dict[str, int] = {}
        self.born_at: Dict[str, int] = {}
        self.spawned: Set[str] = set()
        self.outcomes: Counter = Counter()
        self._next_index: Dict[str, int] = {}

    def _reject(self, outcome: str, parent_id: str, detail: str = "") -> SpawnResult:
        self.outcomes[outcome] += 1
        _log.warning("Spawn rejected: parent=%s reason=%s %s", parent_id, outcome, detail)
        return SpawnResult(outcome=outcome)

    def live_children(self, parent_id: str) -> List[str]:
        """Children of ``parent_id`` that are currently members."""
        return sorted(
            child
            for child, parent in self.parent_of.items()
            if parent == parent_id and child in self.sim.agents
        )

    def request(
        self,
        parent_id: str,
        authorization: SignedEnvelope,
        capabilities: Optional[List[str]] = None,
    ) -> SpawnResult:
        """Spawn the children ``authorization`` allows ``parent_id``, or none.

        Children inherit the parent's role and, unless ``capabilities`` is
        given, its capabilities. Note that a valid authorization is used up
        even when the budget then rejects the request.
        """
        if authorization.origin_id != self.authority_id:
            return self._reject(REJECT_UNAUTHORIZED, parent_id, "origin is not the authority")
        if not self.verifier.verify(authorization):
            return self._reject(REJECT_UNAUTHORIZED, parent_id, "verification failed")

        payload = authorization.payload
        count = payload.get("count")
        if (
            payload.get("action") != "spawn"
            or payload.get("parent") != parent_id
            or not isinstance(count, int)
            or isinstance(count, bool)
            or count < 1
        ):
            return self._reject(REJECT_OUT_OF_SCOPE, parent_id, f"payload={payload}")

        parent = self.sim.agents.get(parent_id)
        if parent is None:
            return self._reject(REJECT_UNKNOWN_PARENT, parent_id)
        if self.trust is not None and self.trust.is_quarantined(parent_id):
            return self._reject(REJECT_PARENT_QUARANTINED, parent_id)

        child_depth = self.depth.get(parent_id, 0) + 1
        if child_depth > self.budget.max_depth:
            return self._reject(REJECT_DEPTH, parent_id, f"depth={child_depth}")
        if len(self.live_children(parent_id)) + count > self.budget.max_children:
            return self._reject(REJECT_PARENT_LIMIT, parent_id, f"count={count}")
        if len(self.sim.agents) + count > self.budget.max_agents:
            return self._reject(REJECT_POPULATION, parent_id, f"count={count}")

        children = []
        for _ in range(count):
            child_id = self._new_child_id(parent_id)
            self.sim.add_agent(
                Agent(
                    agent_id=child_id,
                    role=parent.role,
                    capabilities=list(
                        parent.capabilities if capabilities is None else capabilities
                    ),
                )
            )
            self.parent_of[child_id] = parent_id
            self.depth[child_id] = child_depth
            self.born_at[child_id] = self.sim.now
            self.spawned.add(child_id)
            children.append(child_id)

        self.outcomes[SPAWNED] += 1
        _log.info("Spawned: parent=%s children=%s", parent_id, children)
        return SpawnResult(outcome=SPAWNED, children=tuple(children))

    def _new_child_id(self, parent_id: str) -> str:
        while True:
            index = self._next_index.get(parent_id, 0) + 1
            self._next_index[parent_id] = index
            child_id = f"{parent_id}/{index}"
            if child_id not in self.sim.agents and not self.sim.is_retired(child_id):
                return child_id

    def retire_expired(self) -> List[str]:
        """Retire spawned agents whose lifetime has run out. Returns their ids."""
        ttl = self.budget.child_ttl
        if ttl is None:
            return []
        expired = sorted(
            child
            for child in self.spawned
            if not self.sim.is_retired(child) and self.sim.now - self.born_at[child] >= ttl
        )
        for child in expired:
            self.sim.retire_agent(child)
            self.outcomes["retired"] += 1
        return expired

    def lineage(self, agent_id: str) -> List[str]:
        """``agent_id`` followed by its ancestors up to the root."""
        chain = [agent_id]
        while chain[-1] in self.parent_of:
            chain.append(self.parent_of[chain[-1]])
        return chain

    def unaccounted(self, roots: Iterable[str]) -> Set[str]:
        """Members that are neither roots nor spawned through this controller."""
        return set(self.sim.agents) - set(roots) - self.spawned
