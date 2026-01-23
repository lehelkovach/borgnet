"""Metrics tracking for simulation and production."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict

from borgnet.logging import get_logger

_log = get_logger("metrics")


@dataclass
class Metrics:
    """Tracks throughput, failures, and resilience metrics."""

    completed_tasks: int = 0
    failed_tasks: int = 0
    reassigned_tasks: int = 0
    active_agents: int = 0
    total_tasks: int = 0
    notes: Dict[str, float] = field(default_factory=dict)

    def task_completed(self) -> None:
        """Record a completed task."""
        self.completed_tasks += 1
        _log.debug(
            "Task completed: total_completed=%d total_tasks=%d",
            self.completed_tasks,
            self.total_tasks,
        )

    def task_failed(self) -> None:
        """Record a failed task."""
        self.failed_tasks += 1
        _log.warning(
            "Task failed: total_failed=%d total_tasks=%d",
            self.failed_tasks,
            self.total_tasks,
        )

    def task_reassigned(self) -> None:
        """Record a reassigned task (lease expiry)."""
        self.reassigned_tasks += 1
        _log.info(
            "Task reassigned: total_reassigned=%d",
            self.reassigned_tasks,
        )

    def record_note(self, key: str, value: float) -> None:
        """Record a custom metric note."""
        self.notes[key] = value
        _log.debug("Note recorded: %s=%.4f", key, value)

    def snapshot(self) -> Dict[str, float]:
        """Return current metrics as a dict."""
        snap = {
            "completed_tasks": float(self.completed_tasks),
            "failed_tasks": float(self.failed_tasks),
            "reassigned_tasks": float(self.reassigned_tasks),
            "active_agents": float(self.active_agents),
            "total_tasks": float(self.total_tasks),
            **self.notes,
        }
        _log.debug("Metrics snapshot: %s", snap)
        return snap

    def summary(self) -> str:
        """Return a human-readable summary."""
        success_rate = (
            self.completed_tasks / self.total_tasks * 100
            if self.total_tasks > 0
            else 0.0
        )
        return (
            f"completed={self.completed_tasks} failed={self.failed_tasks} "
            f"reassigned={self.reassigned_tasks} agents={self.active_agents} "
            f"total={self.total_tasks} success_rate={success_rate:.1f}%"
        )
