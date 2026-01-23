"""Memetic strategy evolution for adaptive agent behavior."""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from borgnet.logging import get_logger

_log = get_logger("memetic")


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
        child = Strategy(
            strategy_id=uuid.uuid4().hex[:12],
            params=dict(self.params),
            fitness=0.0,
            source_agent=agent_id,
            generation=self.generation + 1,
        )
        _log.debug(
            "Strategy cloned: parent=%s child=%s agent=%s gen=%d",
            self.strategy_id,
            child.strategy_id,
            agent_id,
            child.generation,
        )
        return child

    def mutate(self, mutation_rate: float = 0.1) -> None:
        """Randomly mutate parameters."""
        mutations = []
        for key in self.params:
            if random.random() < mutation_rate:
                old_val = self.params[key]
                if isinstance(old_val, float):
                    self.params[key] = old_val * random.uniform(0.8, 1.2)
                elif isinstance(old_val, int):
                    self.params[key] = max(0, old_val + random.randint(-1, 1))
                elif isinstance(old_val, bool):
                    self.params[key] = not old_val
                mutations.append((key, old_val, self.params[key]))

        if mutations:
            _log.debug(
                "Strategy mutated: id=%s mutations=%s",
                self.strategy_id,
                mutations,
            )


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
        _log.debug(
            "StrategyPool initialized: max=%d elite=%.2f mutation=%.2f",
            max_strategies,
            elite_fraction,
            mutation_rate,
        )

    def add_strategy(self, strategy: Strategy) -> None:
        """Add a strategy to the pool."""
        self.strategies[strategy.strategy_id] = strategy
        _log.info(
            "Strategy added: id=%s fitness=%.3f source=%s gen=%d",
            strategy.strategy_id,
            strategy.fitness,
            strategy.source_agent,
            strategy.generation,
        )
        self._prune()

    def update_fitness(self, strategy_id: str, fitness: float) -> None:
        """Update fitness score for a strategy."""
        if strategy_id in self.strategies:
            old_fitness = self.strategies[strategy_id].fitness
            # Exponential moving average
            self.strategies[strategy_id].fitness = 0.7 * old_fitness + 0.3 * fitness
            _log.debug(
                "Fitness updated: id=%s old=%.3f new=%.3f reported=%.3f",
                strategy_id,
                old_fitness,
                self.strategies[strategy_id].fitness,
                fitness,
            )
        else:
            _log.warning("Update fitness for unknown strategy: id=%s", strategy_id)

    def select(self, count: int = 1) -> List[Strategy]:
        """Select strategies weighted by fitness (roulette wheel)."""
        if not self.strategies:
            _log.debug("Select called on empty pool")
            return []

        strategies = list(self.strategies.values())
        # Shift fitness to positive
        min_fit = min(s.fitness for s in strategies)
        weights = [s.fitness - min_fit + 1.0 for s in strategies]
        total = sum(weights)
        probs = [w / total for w in weights]

        selected = random.choices(strategies, weights=probs, k=count)
        _log.debug(
            "Selected %d strategies: ids=%s",
            count,
            [s.strategy_id for s in selected],
        )
        return selected

    def evolve(self) -> List[Strategy]:
        """
        Evolve the pool: keep elites, mutate offspring, add diversity.
        Returns newly created strategies.
        """
        if len(self.strategies) < 2:
            _log.debug("Not enough strategies to evolve: count=%d", len(self.strategies))
            return []

        sorted_strategies = sorted(
            self.strategies.values(), key=lambda s: s.fitness, reverse=True
        )
        elite_count = max(1, int(len(sorted_strategies) * self.elite_fraction))
        elites = sorted_strategies[:elite_count]

        _log.info(
            "Evolving pool: total=%d elite_count=%d best_fitness=%.3f",
            len(self.strategies),
            elite_count,
            elites[0].fitness if elites else 0.0,
        )

        new_strategies = []
        for elite in elites:
            child = elite.clone(agent_id="pool")
            child.mutate(self.mutation_rate)
            new_strategies.append(child)
            self.strategies[child.strategy_id] = child

        _log.info("Evolution complete: %d new strategies created", len(new_strategies))
        self._prune()
        return new_strategies

    def best(self) -> Optional[Strategy]:
        """Return the best strategy by fitness."""
        if not self.strategies:
            return None
        best_s = max(self.strategies.values(), key=lambda s: s.fitness)
        _log.debug("Best strategy: id=%s fitness=%.3f", best_s.strategy_id, best_s.fitness)
        return best_s

    def diversity(self) -> float:
        """Measure diversity (unique source agents)."""
        if not self.strategies:
            return 0.0
        sources = set(
            s.source_agent for s in self.strategies.values() if s.source_agent
        )
        div = len(sources) / max(1, len(self.strategies))
        _log.debug("Pool diversity: %.3f (%d unique sources)", div, len(sources))
        return div

    def _prune(self) -> None:
        """Remove worst strategies if over limit."""
        if len(self.strategies) > self.max_strategies:
            sorted_strategies = sorted(
                self.strategies.values(), key=lambda s: s.fitness
            )
            to_remove = len(self.strategies) - self.max_strategies
            for s in sorted_strategies[:to_remove]:
                del self.strategies[s.strategy_id]
                _log.debug("Strategy pruned: id=%s fitness=%.3f", s.strategy_id, s.fitness)
            _log.info("Pool pruned: removed %d strategies", to_remove)

    def snapshot(self) -> Dict[str, Any]:
        """Return pool state."""
        best = self.best()
        return {
            "count": len(self.strategies),
            "best_fitness": best.fitness if best else 0.0,
            "diversity": self.diversity(),
        }
