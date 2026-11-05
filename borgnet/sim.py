"""Simulation engine for task leasing and agent coordination."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from borgnet.logging import get_logger
from borgnet.metrics import Metrics

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
    """

    def __init__(self, presence_ttl: Optional[int] = None) -> None:
        if presence_ttl is not None and presence_ttl < 0:
            raise ValueError(f"presence_ttl must be >= 0, got {presence_ttl}")
        self.tasks: Dict[str, Task] = {}
        self.agents: Dict[str, Agent] = {}
        self.metrics = Metrics()
        self.now = 0
        self.presence_ttl = presence_ttl
        self.last_seen: Dict[str, int] = {}
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
            orphaned = [
                t.task_id
                for t in self.tasks.values()
                if t.status == "running" and t.owner == agent_id
            ]
            _log.warning(
                "Agent missed heartbeats, dropping: id=%s last_seen=%d now=%d tasks=%s",
                agent_id,
                self.last_seen[agent_id],
                self.now,
                orphaned,
            )
            for task_id in orphaned:
                self.requeue_task(task_id, agent_id=agent_id)
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

    def assign_task(self, task_id: str, agent_id: str) -> None:
        if task_id not in self.tasks:
            _log.error("Cannot assign unknown task: task_id=%s", task_id)
            raise KeyError(f"Task not found: {task_id}")

        if agent_id not in self.agents:
            _log.warning(
                "Assigning task to unknown agent: task=%s agent=%s",
                task_id,
                agent_id,
            )

        task = self.tasks[task_id]
        task.status = "running"
        task.owner = agent_id
        task.lease_expires_at = self.now + task.lease_ttl

        _log.info(
            "Task assigned: task=%s agent=%s lease_expires_at=%d",
            task_id,
            agent_id,
            task.lease_expires_at,
        )

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
