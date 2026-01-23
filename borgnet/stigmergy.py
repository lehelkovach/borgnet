"""Stigmergic demand map for decentralized task selection."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, Optional

from borgnet.logging import get_logger

_log = get_logger("stigmergy")


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
        _log.debug(
            "DemandMap initialized: decay_rate=%.3f min_intensity=%.4f",
            decay_rate,
            min_intensity,
        )

    def deposit(self, task_type: str, amount: float = 1.0) -> None:
        """Deposit demand signal (reinforce pheromone)."""
        if task_type in self.signals:
            old_intensity = self.signals[task_type].intensity
            self.signals[task_type].intensity += amount
            _log.debug(
                "Demand reinforced: type=%s amount=%.3f old=%.3f new=%.3f",
                task_type,
                amount,
                old_intensity,
                self.signals[task_type].intensity,
            )
        else:
            self.signals[task_type] = DemandSignal(
                task_type=task_type,
                intensity=amount,
                decay_rate=self.decay_rate,
            )
            _log.info(
                "New demand signal: type=%s intensity=%.3f",
                task_type,
                amount,
            )

    def evaporate(self, elapsed: Optional[float] = None) -> None:
        """Decay all signals based on elapsed time."""
        now = time.time()
        if elapsed is None:
            elapsed = now - self._last_update
        self._last_update = now

        _log.debug("Evaporating signals: elapsed=%.3f seconds", elapsed)

        to_remove = []
        for task_type, signal in self.signals.items():
            old_intensity = signal.intensity
            signal.intensity *= (1 - signal.decay_rate) ** elapsed
            if signal.intensity < self.min_intensity:
                to_remove.append(task_type)
                _log.debug(
                    "Signal below threshold: type=%s intensity=%.6f (removing)",
                    task_type,
                    signal.intensity,
                )
            else:
                _log.debug(
                    "Signal decayed: type=%s old=%.4f new=%.4f",
                    task_type,
                    old_intensity,
                    signal.intensity,
                )

        for task_type in to_remove:
            del self.signals[task_type]
            _log.info("Signal evaporated: type=%s", task_type)

    def get_intensity(self, task_type: str) -> float:
        """Get current intensity for a task type."""
        signal = self.signals.get(task_type)
        intensity = signal.intensity if signal else 0.0
        _log.debug("Get intensity: type=%s intensity=%.4f", task_type, intensity)
        return intensity

    def highest_demand(self) -> Optional[str]:
        """Return the task type with highest demand."""
        if not self.signals:
            _log.debug("No demand signals present")
            return None
        highest = max(self.signals, key=lambda t: self.signals[t].intensity)
        _log.debug(
            "Highest demand: type=%s intensity=%.4f",
            highest,
            self.signals[highest].intensity,
        )
        return highest

    def ranked_demand(self) -> list[tuple[str, float]]:
        """Return task types ranked by demand (descending)."""
        ranked = sorted(
            [(t, s.intensity) for t, s in self.signals.items()],
            key=lambda x: x[1],
            reverse=True,
        )
        _log.debug("Ranked demand: %s", ranked)
        return ranked

    def snapshot(self) -> Dict[str, float]:
        """Return current demand map as dict."""
        snap = {t: s.intensity for t, s in self.signals.items()}
        _log.debug("Demand snapshot: %d signals", len(snap))
        return snap
