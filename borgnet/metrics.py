from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


@dataclass
class Metrics:
    completed_tasks: int = 0
    failed_tasks: int = 0
    reassigned_tasks: int = 0
    active_agents: int = 0
    total_tasks: int = 0
    notes: Dict[str, float] = field(default_factory=dict)

    def task_completed(self) -> None:
        self.completed_tasks += 1

    def task_failed(self) -> None:
        self.failed_tasks += 1

    def task_reassigned(self) -> None:
        self.reassigned_tasks += 1

    def snapshot(self) -> Dict[str, float]:
        return {
            "completed_tasks": float(self.completed_tasks),
            "failed_tasks": float(self.failed_tasks),
            "reassigned_tasks": float(self.reassigned_tasks),
            "active_agents": float(self.active_agents),
            "total_tasks": float(self.total_tasks),
            **self.notes,
        }
