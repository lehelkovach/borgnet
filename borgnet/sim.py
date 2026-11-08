"""Simulation engine for task leasing and agent coordination."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from borgnet.logging import get_logger
from borgnet.metrics import Metrics
from borgnet.security import TrustRegistry

_log = get_logger("sim")


@dataclass
class Task:
    task_id: str
    task_type: str
    status: str = "queued"
    owner: Optional[str] = None
    lease_ttl: int = 60
    lease_expires_at: Optional[int] = None


@dataclass
class Agent:
    agent_id: str
    role: str = "worker"
    capabilities: List[str] = field(default_factory=list)


class Simulation:
    """Tasks, agents, leases, and presence on a simulated clock.

    With ``presence_ttl`` set, every agent must call :meth:`heartbeat` at
    least once every ``presence_ttl`` seconds. An agent that stays silent for
    longer is dropped on the next :meth:`tick`, and its running tasks go
    straight back to the queue instead of waiting for their leases to expire.

    The simulation is the lease authority, so it enforces who may hold a
    lease no matter how a caller behaves. :meth:`assign_task` grants a lease
    only on a queued task, and only to a current member that has not been
    retired. With ``trust`` attached, quarantined agents are refused too.
    """

    def __init__(
        self,
        presence_ttl: Optional[int] = None,
        trust: Optional[TrustRegistry] = None,
    ) -> None:
        if presence_ttl is not None and presence_ttl < 0:
            raise ValueError(f"presence_ttl must be >= 0, got {presence_ttl}")
        self.tasks: Dict[str, Task] = {}
        self.agents: Dict[str, Agent] = {}
        self.metrics = Metrics()
        self.now = 0
        self.presence_ttl = presence_ttl
        self.trust = trust
        self.last_seen: Dict[str, int] = {}
        self.retired: Set[str] = set()
        _log.debug("Simulation initialized at t=0 presence_ttl=%s", presence_ttl)

    def add_task(self, task: Task) -> None:
        self.tasks[task.task_id] = task
        self.metrics.total_tasks += 1
        _log.info(
            "Task added: id=%s type=%s ttl=%d",
            task.task_id,
            task.task_type,
            task.lease_ttl,
        )

    def add_agent(self, agent: Agent) -> None:
        """Add ``agent`` as a member. Raises ValueError for a retired agent."""
        if agent.agent_id in self.retired:
            raise ValueError(f"Agent was retired and cannot rejoin: {agent.agent_id}")
        self.agents[agent.agent_id] = agent
        self.last_seen[agent.agent_id] = self.now
        self.metrics.active_agents = len(self.agents)
        _log.info(
            "Agent added: id=%s role=%s capabilities=%s",
            agent.agent_id,
            agent.role,
            agent.capabilities,
        )

    def remove_agent(self, agent_id: str) -> None:
        if agent_id in self.agents:
            del self.agents[agent_id]
            self.last_seen.pop(agent_id, None)
            self.metrics.active_agents = len(self.agents)
            _log.info("Agent removed: id=%s", agent_id)
        else:
            _log.warning("Attempted to remove unknown agent: id=%s", agent_id)

    def is_retired(self, agent_id: str) -> bool:
        """True if ``agent_id`` was retired and may never rejoin."""
        return agent_id in self.retired

    def retire_agent(self, agent_id: str) -> List[str]:
        """Remove ``agent_id`` for good and requeue its running tasks.

        Unlike :meth:`remove_agent`, a retired agent cannot be added again, so
        an agent whose lifetime ran out cannot come back on its own. Returns
        the ids of the requeued tasks.
        """
        requeued = self._release_tasks(agent_id)
        if agent_id in self.agents:
            self.remove_agent(agent_id)
        self.retired.add(agent_id)
        _log.info("Agent retired: id=%s requeued=%s", agent_id, requeued)
        return requeued

    def _release_tasks(self, agent_id: str) -> List[str]:
        """Requeue every running task leased to ``agent_id``."""
        owned = [
            t.task_id
            for t in self.tasks.values()
            if t.status == "running" and t.owner == agent_id
        ]
        for task_id in owned:
            self.requeue_task(task_id, agent_id=agent_id)
        return owned

    def heartbeat(self, agent_id: str) -> bool:
        """Record that ``agent_id`` is alive now. False if it is not a member.

        An agent dropped for silence is no longer a member; it must be added
        again with :meth:`add_agent`.
        """
        if agent_id not in self.agents:
            _log.warning("Heartbeat from unknown agent: id=%s", agent_id)
            return False
        self.last_seen[agent_id] = self.now
        return True

    def _drop_silent_agents(self) -> None:
        assert self.presence_ttl is not None
        silent = sorted(
            agent_id
            for agent_id, seen in self.last_seen.items()
            if self.now - seen > self.presence_ttl
        )
        for agent_id in silent:
            _log.warning(
                "Agent missed heartbeats, dropping: id=%s last_seen=%d now=%d",
                agent_id,
                self.last_seen[agent_id],
                self.now,
            )
            self._release_tasks(agent_id)
            self.remove_agent(agent_id)
            self.metrics.agent_lost()

    def tick(self, seconds: int = 1) -> None:
        self.now += seconds
        _log.debug("Tick: now=%d (+%d seconds)", self.now, seconds)

        if self.presence_ttl is not None:
            self._drop_silent_agents()

        expired_count = 0
        for task in self.tasks.values():
            if task.status == "running" and task.lease_expires_at is not None:
                if self.now >= task.lease_expires_at:
                    _log.warning(
                        "Lease expired: task=%s owner=%s expires_at=%d now=%d",
                        task.task_id,
                        task.owner,
                        task.lease_expires_at,
                        self.now,
                    )
                    task.status = "queued"
                    task.owner = None
                    task.lease_expires_at = None
                    self.metrics.task_reassigned()
                    expired_count += 1

        if expired_count > 0:
            _log.info("Tick complete: %d leases expired and requeued", expired_count)

    def assign_task(self, task_id: str, agent_id: str) -> bool:
        """Grant ``agent_id`` a lease on a queued task. False if refused.

        Refused when the task is not queued (so a running task's lease cannot
        be taken over), when the agent is not a member or was retired, and,
        with ``trust`` attached, when the agent is quarantined.
        """
        if task_id not in self.tasks:
            _log.error("Cannot assign unknown task: task_id=%s", task_id)
            raise KeyError(f"Task not found: {task_id}")

        task = self.tasks[task_id]
        reason = None
        if task.status != "queued":
            reason = f"task is {task.status}"
        elif agent_id not in self.agents:
            reason = "agent is retired" if agent_id in self.retired else "agent is not a member"
        elif self.trust is not None and self.trust.is_quarantined(agent_id):
            reason = "agent is quarantined"
        if reason is not None:
            _log.warning(
                "Lease refused: task=%s agent=%s reason=%s", task_id, agent_id, reason
            )
            return False

        task.status = "running"
        task.owner = agent_id
        task.lease_expires_at = self.now + task.lease_ttl

        _log.info(
            "Task assigned: task=%s agent=%s lease_expires_at=%d",
            task_id,
            agent_id,
            task.lease_expires_at,
        )
        return True

    def _check_lease(self, task: Task, action: str, agent_id: Optional[str]) -> bool:
        """Return True if ``task`` holds a live lease that ``agent_id`` may act on.

        Only a running task can be completed or requeued. When ``agent_id`` is
        given it must be the current lease owner, so a worker whose lease
        expired and was re-assigned cannot complete or drop the new owner's task.
        """
        if task.status != "running":
            _log.warning(
                "Cannot %s task not running: task=%s status=%s",
                action,
                task.task_id,
                task.status,
            )
            return False
        if agent_id is not None and agent_id != task.owner:
            _log.warning(
                "Cannot %s task leased to another agent: task=%s owner=%s caller=%s",
                action,
                task.task_id,
                task.owner,
                agent_id,
            )
            return False
        return True

    def complete_task(
        self, task_id: str, success: bool = True, agent_id: Optional[str] = None
    ) -> bool:
        """Finish a running task. Returns False if the completion was rejected.

        A task that is not running (already done, failed, or back in the queue
        after lease expiry) is left unchanged, so it is never counted twice.
        """
        if task_id not in self.tasks:
            _log.error("Cannot complete unknown task: task_id=%s", task_id)
            raise KeyError(f"Task not found: {task_id}")

        task = self.tasks[task_id]
        if not self._check_lease(task, "complete", agent_id):
            return False
        old_status = task.status
        old_owner = task.owner

        task.status = "done" if success else "failed"
        task.owner = None
        task.lease_expires_at = None

        if success:
            self.metrics.task_completed()
            _log.info(
                "Task completed: task=%s owner=%s old_status=%s",
                task_id,
                old_owner,
                old_status,
            )
        else:
            self.metrics.task_failed()
            _log.warning(
                "Task failed: task=%s owner=%s old_status=%s",
                task_id,
                old_owner,
                old_status,
            )
        return True

    def requeue_task(self, task_id: str, agent_id: Optional[str] = None) -> bool:
        """Return an owned/running task to the queue (self-healing requeue).

        Used when a worker dies mid-task: the lease is dropped and the task
        becomes available for a healthy peer, the same outcome lease expiry
        produces in :meth:`tick`, but without waiting for the lease to lapse.
        Returns False, leaving the task unchanged, if it is not running or
        ``agent_id`` is given and is not the lease owner.
        """
        if task_id not in self.tasks:
            _log.error("Cannot requeue unknown task: task_id=%s", task_id)
            raise KeyError(f"Task not found: {task_id}")

        task = self.tasks[task_id]
        if not self._check_lease(task, "requeue", agent_id):
            return False
        old_owner = task.owner
        task.status = "queued"
        task.owner = None
        task.lease_expires_at = None
        self.metrics.task_reassigned()
        _log.info("Task requeued: task=%s old_owner=%s", task_id, old_owner)
        return True

    def get_queued_tasks(self) -> List[Task]:
        """Return all tasks in queued status."""
        queued = [t for t in self.tasks.values() if t.status == "queued"]
        _log.debug("Queued tasks: count=%d", len(queued))
        return queued

    def get_running_tasks(self) -> List[Task]:
        """Return all tasks in running status."""
        running = [t for t in self.tasks.values() if t.status == "running"]
        _log.debug("Running tasks: count=%d", len(running))
        return running
