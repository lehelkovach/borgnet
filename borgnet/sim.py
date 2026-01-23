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
    def __init__(self) -> None:
        self.tasks: Dict[str, Task] = {}
        self.agents: Dict[str, Agent] = {}
        self.metrics = Metrics()
        self.now = 0
        _log.debug("Simulation initialized at t=0")

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
            self.metrics.active_agents = len(self.agents)
            _log.info("Agent removed: id=%s", agent_id)
        else:
            _log.warning("Attempted to remove unknown agent: id=%s", agent_id)

    def tick(self, seconds: int = 1) -> None:
        self.now += seconds
        _log.debug("Tick: now=%d (+%d seconds)", self.now, seconds)

        expired_count = 0
        for task in self.tasks.values():
            if task.status == "running" and task.lease_expires_at:
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

    def complete_task(self, task_id: str, success: bool = True) -> None:
        if task_id not in self.tasks:
            _log.error("Cannot complete unknown task: task_id=%s", task_id)
            raise KeyError(f"Task not found: {task_id}")

        task = self.tasks[task_id]
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
