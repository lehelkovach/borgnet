"""Unit tests for memetic strategy evolution."""

from borgnet.memetic import Strategy, StrategyPool


def test_strategy_clone():
    s = Strategy(params={"rate": 0.5, "depth": 3})
    s.fitness = 10.0
    child = s.clone("agent-1")
    
    assert child.strategy_id != s.strategy_id
    assert child.params == s.params
    assert child.fitness == 0.0
    assert child.source_agent == "agent-1"
    assert child.generation == s.generation + 1


def test_strategy_mutate():
    s = Strategy(params={"rate": 1.0, "depth": 5, "enabled": True})
    
    # Mutate multiple times to ensure at least one change
    original_params = dict(s.params)
    for _ in range(50):
        s.mutate(mutation_rate=1.0)
    
    # At least one param should have changed
    changed = any(s.params[k] != original_params[k] for k in s.params)
    assert changed


def test_strategy_pool_add():
    pool = StrategyPool(max_strategies=10)
    s = Strategy(params={"rate": 0.5})
    pool.add_strategy(s)
    
    assert s.strategy_id in pool.strategies
    assert len(pool.strategies) == 1


def test_strategy_pool_update_fitness():
    pool = StrategyPool()
    s = Strategy(params={"rate": 0.5})
    pool.add_strategy(s)
    
    pool.update_fitness(s.strategy_id, 10.0)
    assert pool.strategies[s.strategy_id].fitness > 0


def test_strategy_pool_select():
    pool = StrategyPool()
    for i in range(5):
        s = Strategy(params={"rate": i * 0.1})
        s.fitness = float(i)
        pool.add_strategy(s)
    
    selected = pool.select(count=3)
    assert len(selected) == 3


def test_strategy_pool_best():
    pool = StrategyPool()
    for i in range(5):
        s = Strategy(params={"rate": i * 0.1})
        s.fitness = float(i)
        pool.add_strategy(s)
    
    best = pool.best()
    assert best.fitness == 4.0


def test_strategy_pool_evolve():
    pool = StrategyPool(max_strategies=10, elite_fraction=0.5, mutation_rate=0.5)
    for i in range(5):
        s = Strategy(params={"rate": 0.5, "depth": 3})
        s.fitness = float(i)
        pool.add_strategy(s)
    
    new_strategies = pool.evolve()
    assert len(new_strategies) > 0


def test_strategy_pool_prune():
    pool = StrategyPool(max_strategies=5)
    for i in range(10):
        s = Strategy(params={"rate": 0.5})
        s.fitness = float(i)
        pool.add_strategy(s)
    
    assert len(pool.strategies) <= 5


def test_strategy_pool_diversity():
    pool = StrategyPool()
    for i in range(5):
        s = Strategy(params={"rate": 0.5})
        s.source_agent = f"agent-{i}"
        pool.add_strategy(s)
    
    assert pool.diversity() == 1.0  # All unique sources


def test_strategy_pool_snapshot():
    pool = StrategyPool()
    s = Strategy(params={"rate": 0.5})
    s.fitness = 5.0
    pool.add_strategy(s)
    
    snap = pool.snapshot()
    assert snap["count"] == 1
    assert snap["best_fitness"] == 5.0
