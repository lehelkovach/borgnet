"""Memetic strategy evolution for adaptive agent behavior."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
import uuid


@dataclass
class Strategy:
    """
    A meme representing a behavioral strategy.
    
    Strategies encode parameters for task selection, communication rate,
    verification depth, etc. Successful strategies spread; poor ones decay.
    """
    strategy_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    params: Dict[str, Any] = field(default_factory=dict)
    fitness: float = 0.0
    source_agent: Optional[str] = None
    generation: int = 0

    def clone(self, agent_id: str) -> "Strategy":
        """Clone this strategy for another agent."""
        return Strategy(
            strategy_id=uuid.uuid4().hex[:12],
            params=dict(self.params),
            fitness=0.0,
            source_agent=agent_id,
            generation=self.generation + 1,
        )

    def mutate(self, mutation_rate: float = 0.1) -> None:
        """Randomly mutate parameters."""
        for key in self.params:
            if random.random() < mutation_rate:
                val = self.params[key]
                if isinstance(val, float):
                    self.params[key] = val * random.uniform(0.8, 1.2)
                elif isinstance(val, int):
                    self.params[key] = max(0, val + random.randint(-1, 1))
                elif isinstance(val, bool):
                    self.params[key] = not val


class StrategyPool:
    """
    Pool of strategies with selection, propagation, and evolution.
    
    Agents report fitness; pool maintains diversity and evolves.
    """

    def __init__(
        self,
        max_strategies: int = 100,
        elite_fraction: float = 0.2,
        mutation_rate: float = 0.1,
    ):
        self.strategies: Dict[str, Strategy] = {}
        self.max_strategies = max_strategies
        self.elite_fraction = elite_fraction
        self.mutation_rate = mutation_rate

    def add_strategy(self, strategy: Strategy) -> None:
        """Add a strategy to the pool."""
        self.strategies[strategy.strategy_id] = strategy
        self._prune()

    def update_fitness(self, strategy_id: str, fitness: float) -> None:
        """Update fitness score for a strategy."""
        if strategy_id in self.strategies:
            # Exponential moving average
            old = self.strategies[strategy_id].fitness
            self.strategies[strategy_id].fitness = 0.7 * old + 0.3 * fitness

    def select(self, count: int = 1) -> List[Strategy]:
        """
        Select strategies weighted by fitness (roulette wheel).
        """
        if not self.strategies:
            return []

        strategies = list(self.strategies.values())
        # Shift fitness to positive
        min_fit = min(s.fitness for s in strategies)
        weights = [s.fitness - min_fit + 1.0 for s in strategies]
        total = sum(weights)
        probs = [w / total for w in weights]

        return random.choices(strategies, weights=probs, k=count)

    def evolve(self) -> List[Strategy]:
        """
        Evolve the pool: keep elites, mutate offspring, add diversity.
        Returns newly created strategies.
        """
        if len(self.strategies) < 2:
            return []

        sorted_strategies = sorted(
            self.strategies.values(), key=lambda s: s.fitness, reverse=True
        )
        elite_count = max(1, int(len(sorted_strategies) * self.elite_fraction))
        elites = sorted_strategies[:elite_count]

        new_strategies = []
        for elite in elites:
            child = elite.clone(agent_id="pool")
            child.mutate(self.mutation_rate)
            new_strategies.append(child)
            self.strategies[child.strategy_id] = child

        self._prune()
        return new_strategies

    def best(self) -> Optional[Strategy]:
        """Return the best strategy by fitness."""
        if not self.strategies:
            return None
        return max(self.strategies.values(), key=lambda s: s.fitness)

    def diversity(self) -> float:
        """Measure diversity (unique source agents)."""
        if not self.strategies:
            return 0.0
        sources = set(s.source_agent for s in self.strategies.values() if s.source_agent)
        return len(sources) / max(1, len(self.strategies))

    def _prune(self) -> None:
        """Remove worst strategies if over limit."""
        if len(self.strategies) > self.max_strategies:
            sorted_strategies = sorted(
                self.strategies.values(), key=lambda s: s.fitness
            )
            to_remove = len(self.strategies) - self.max_strategies
            for s in sorted_strategies[:to_remove]:
                del self.strategies[s.strategy_id]

    def snapshot(self) -> Dict[str, Any]:
        """Return pool state."""
        return {
            "count": len(self.strategies),
            "best_fitness": self.best().fitness if self.best() else 0.0,
            "diversity": self.diversity(),
        }
