from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from borgnet.metrics import Metrics


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

    def add_task(self, task: Task) -> None:
        self.tasks[task.task_id] = task
        self.metrics.total_tasks += 1

    def add_agent(self, agent: Agent) -> None:
        self.agents[agent.agent_id] = agent
        self.metrics.active_agents = len(self.agents)

    def tick(self, seconds: int = 1) -> None:
        self.now += seconds
        for task in self.tasks.values():
            if task.status == "running" and task.lease_expires_at:
                if self.now >= task.lease_expires_at:
                    task.status = "queued"
                    task.owner = None
                    task.lease_expires_at = None
                    self.metrics.task_reassigned()

    def assign_task(self, task_id: str, agent_id: str) -> None:
        task = self.tasks[task_id]
        task.status = "running"
        task.owner = agent_id
        task.lease_expires_at = self.now + task.lease_ttl

    def complete_task(self, task_id: str, success: bool = True) -> None:
        task = self.tasks[task_id]
        task.status = "done" if success else "failed"
        task.owner = None
        task.lease_expires_at = None
        if success:
            self.metrics.task_completed()
        else:
            self.metrics.task_failed()
