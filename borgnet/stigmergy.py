"""Stigmergic demand map for decentralized task selection."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional
import time


@dataclass
class DemandSignal:
    """A pheromone-like signal for a task type or resource."""
    task_type: str
    intensity: float = 1.0
    created_at: float = field(default_factory=time.time)
    decay_rate: float = 0.1  # per second


class DemandMap:
    """
    Shared demand map that agents read and reinforce.
    
    Agents deposit signals when they observe unmet demand (queued tasks).
    Agents evaporate signals over time.
    Agents select tasks based on highest local demand.
    """

    def __init__(self, decay_rate: float = 0.1, min_intensity: float = 0.01):
        self.signals: Dict[str, DemandSignal] = {}
        self.decay_rate = decay_rate
        self.min_intensity = min_intensity
        self._last_update = time.time()

    def deposit(self, task_type: str, amount: float = 1.0) -> None:
        """Deposit demand signal (reinforce pheromone)."""
        if task_type in self.signals:
            self.signals[task_type].intensity += amount
        else:
            self.signals[task_type] = DemandSignal(
                task_type=task_type,
                intensity=amount,
                decay_rate=self.decay_rate,
            )

    def evaporate(self, elapsed: Optional[float] = None) -> None:
        """Decay all signals based on elapsed time."""
        now = time.time()
        if elapsed is None:
            elapsed = now - self._last_update
        self._last_update = now

        to_remove = []
        for task_type, signal in self.signals.items():
            signal.intensity *= (1 - signal.decay_rate) ** elapsed
            if signal.intensity < self.min_intensity:
                to_remove.append(task_type)

        for task_type in to_remove:
            del self.signals[task_type]

    def get_intensity(self, task_type: str) -> float:
        """Get current intensity for a task type."""
        signal = self.signals.get(task_type)
        return signal.intensity if signal else 0.0

    def highest_demand(self) -> Optional[str]:
        """Return the task type with highest demand."""
        if not self.signals:
            return None
        return max(self.signals, key=lambda t: self.signals[t].intensity)

    def ranked_demand(self) -> list[tuple[str, float]]:
        """Return task types ranked by demand (descending)."""
        return sorted(
            [(t, s.intensity) for t, s in self.signals.items()],
            key=lambda x: x[1],
            reverse=True,
        )

    def snapshot(self) -> Dict[str, float]:
        """Return current demand map as dict."""
        return {t: s.intensity for t, s in self.signals.items()}
