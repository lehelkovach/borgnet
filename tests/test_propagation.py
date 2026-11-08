"""Tests for trust-gated peer-to-peer strategy exchange."""

import random

import pytest

from borgnet.agent import AgentRunner
from borgnet.memetic import Strategy, StrategyPool
from borgnet.propagation import AdoptionPolicy, PeerExchange, StrategyOffer
from borgnet.security import TrustRegistry
from borgnet.sim import Agent, Simulation, Task
from borgnet.stigmergy import DemandMap


def _pool(*strategies):
    pool = StrategyPool()
    for params, fitness in strategies:
        pool.add_strategy(Strategy(params=dict(params), fitness=fitness))
    return pool


def _exchange(policy=None, **pools):
    trust = TrustRegistry()
    exchange = PeerExchange(trust, policy=policy, rng=random.Random(0))
    for agent_id, pool in pools.items():
        exchange.join(agent_id, pool)
    return exchange, trust


class TestAdoption:
    def test_adopts_better_strategy_from_trusted_peer(self):
        exchange, _ = _exchange(a=_pool(({"x": 1}, 2.0)), b=_pool(({"x": 0}, 0.5)))
        assert exchange.share("a") == ["b"]
        adopted = [s for s in exchange.pools["b"].strategies.values() if s.params == {"x": 1}]
        assert len(adopted) == 1
        # Discounted to 2.0 * 0.5 = 1.0, then capped at the receiver's best, 0.5.
        assert adopted[0].fitness == pytest.approx(0.5)
        assert adopted[0].source_agent == "a"
        assert adopted[0].generation == 1

    def test_uncapped_policy_keeps_discounted_fitness(self):
        policy = AdoptionPolicy(cap_at_receiver_best=False)
        exchange, _ = _exchange(policy, a=_pool(({"x": 1}, 2.0)), b=_pool(({"x": 0}, 0.5)))
        exchange.share("a")
        adopted = [s for s in exchange.pools["b"].strategies.values() if s.params == {"x": 1}]
        assert adopted[0].fitness == pytest.approx(1.0)

    def test_inflated_claim_is_not_laundered_to_other_peers(self):
        # "mallory" is still trusted and claims an inflated fitness. "b" adopts,
        # but the cap keeps the copy at b's own best, so b's next share is not
        # better than c's best and the claim stops at b.
        exchange, _ = _exchange(
            mallory=_pool(({"x": 9}, 100.0)),
            b=_pool(({"x": 0}, 0.8)),
            c=_pool(({"x": 1}, 0.8)),
        )
        exchange.offer("b", StrategyOffer("mallory", "s", {"x": 9}, 100.0, 0))
        assert exchange.share("b") == []

    def test_uncapped_policy_launders_inflated_claim(self):
        # The vulnerability the cap fixes, kept as a regression reference.
        policy = AdoptionPolicy(cap_at_receiver_best=False)
        exchange, _ = _exchange(
            policy,
            mallory=_pool(({"x": 9}, 100.0)),
            b=_pool(({"x": 0}, 0.8)),
            c=_pool(({"x": 1}, 0.8)),
        )
        exchange.offer("b", StrategyOffer("mallory", "s", {"x": 9}, 100.0, 0))
        assert "c" in exchange.share("b")

    def test_rejects_offer_that_is_not_better(self):
        exchange, _ = _exchange(a=_pool(({"x": 1}, 2.0)), b=_pool(({"x": 0}, 3.0)))
        assert exchange.share("a") == []
        assert exchange.outcomes["not_better"] == 1

    def test_fitness_margin(self):
        policy = AdoptionPolicy(fitness_margin=1.0)
        exchange, _ = _exchange(policy, a=_pool(({"x": 1}, 2.0)), b=_pool(({"x": 0}, 1.5)))
        assert exchange.share("a") == []

    def test_rejects_quarantined_sender(self):
        exchange, trust = _exchange(a=_pool(({"x": 1}, 9.0)), b=_pool(({"x": 0}, 0.0)))
        trust.record_anomaly("a")
        trust.record_anomaly("a")
        assert trust.is_quarantined("a")
        assert exchange.share("a") == []
        assert exchange.outcomes["sender_quarantined"] == 1

    def test_rejects_poorly_trusted_sender(self):
        exchange, trust = _exchange(a=_pool(({"x": 1}, 9.0)), b=_pool(({"x": 0}, 0.0)))
        trust.record_failure("a")
        trust.record_failure("a")  # 1.0 -> 0.6, below the 0.8 default
        assert not trust.is_quarantined("a")
        assert exchange.share("a") == []
        assert exchange.outcomes["sender_untrusted"] == 1

    def test_rejects_params_the_receiver_already_has(self):
        exchange, _ = _exchange(a=_pool(({"x": 1}, 9.0)), b=_pool(({"x": 1}, 0.0)))
        assert exchange.share("a") == []
        assert exchange.outcomes["already_known"] == 1

    def test_rejects_unknown_sender_and_self(self):
        exchange, _ = _exchange(b=_pool(({"x": 0}, 0.0)))
        outsider = StrategyOffer("mallory", "s1", {"x": 1}, 9.0, 0)
        assert exchange.offer("b", outsider) is False
        own = StrategyOffer("b", "s2", {"x": 2}, 9.0, 0)
        assert exchange.offer("b", own) is False
        assert exchange.outcomes["unknown_sender"] == 1
        assert exchange.outcomes["self"] == 1

    def test_empty_receiver_adopts_and_empty_sender_shares_nothing(self):
        exchange, _ = _exchange(a=_pool(({"x": 1}, 0.2)), b=StrategyPool())
        assert exchange.share("b") == []
        assert exchange.share("a") == ["b"]

    def test_fanout_limits_peers(self):
        pools = {"a": _pool(({"x": 1}, 5.0))}
        pools.update({f"p{i}": StrategyPool() for i in range(5)})
        trust = TrustRegistry()
        exchange = PeerExchange(trust, fanout=2, rng=random.Random(1))
        for agent_id, pool in pools.items():
            exchange.join(agent_id, pool)
        assert len(exchange.share("a")) == 2

    def test_gossip_round_spreads_to_every_peer(self):
        exchange, _ = _exchange(
            a=_pool(({"x": 1}, 4.0)), b=_pool(({"x": 0}, 0.1)), c=StrategyPool()
        )
        adopters = exchange.gossip_round()
        assert sorted(adopters["a"]) == ["b", "c"]
        for agent in ("b", "c"):
            assert any(s.params == {"x": 1} for s in exchange.pools[agent].strategies.values())

    def test_left_agent_no_longer_receives(self):
        exchange, _ = _exchange(a=_pool(({"x": 1}, 4.0)), b=StrategyPool())
        exchange.leave("b")
        assert exchange.share("a") == []

    def test_invalid_policy_raises(self):
        with pytest.raises(ValueError):
            AdoptionPolicy(prior_weight=1.5)
        with pytest.raises(ValueError):
            AdoptionPolicy(fitness_margin=-1.0)
        with pytest.raises(ValueError):
            PeerExchange(TrustRegistry(), fanout=0)


class SkillWorker:
    """Fitness is the strategy's skill parameter, so better strategies score higher."""

    def run(self, task, strategy):
        return strategy.params["skill"] if strategy else 0.0


def test_good_strategy_spreads_through_running_agents():
    random.seed(0)
    sim = Simulation()
    demand = DemandMap()
    trust = TrustRegistry()
    exchange = PeerExchange(trust, rng=random.Random(0))
    runners = {}
    for agent_id, skill in (("a", 1.0), ("b", 0.1)):
        agent = Agent(agent_id=agent_id)
        sim.add_agent(agent)
        pool = _pool(({"skill": skill}, 0.0))
        exchange.join(agent_id, pool)
        runners[agent_id] = AgentRunner(agent, sim, pool, demand, trust, SkillWorker())

    for i in range(40):
        sim.add_task(Task(task_id=f"t{i}", task_type="work", lease_ttl=30))

    for agent_id in ("a", "b"):
        assert runners[agent_id].step().outcome == "completed"
    assert exchange.gossip_round()["a"] == ["b"]

    for _ in range(30):
        runners["b"].step()

    best = exchange.pools["b"].best()
    assert best.params == {"skill": 1.0}
    assert best.source_agent == "a"
