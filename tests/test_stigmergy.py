"""Unit tests for stigmergy demand map."""

import time

from borgnet.stigmergy import DemandMap, DemandSignal


def test_deposit_new_signal():
    dm = DemandMap()
    dm.deposit("deploy", 1.0)
    assert dm.get_intensity("deploy") == 1.0


def test_deposit_reinforces_existing():
    dm = DemandMap()
    dm.deposit("deploy", 1.0)
    dm.deposit("deploy", 2.0)
    assert dm.get_intensity("deploy") == 3.0


def test_get_intensity_missing_returns_zero():
    dm = DemandMap()
    assert dm.get_intensity("nonexistent") == 0.0


def test_highest_demand():
    dm = DemandMap()
    dm.deposit("deploy", 1.0)
    dm.deposit("test", 3.0)
    dm.deposit("build", 2.0)
    assert dm.highest_demand() == "test"


def test_ranked_demand():
    dm = DemandMap()
    dm.deposit("deploy", 1.0)
    dm.deposit("test", 3.0)
    dm.deposit("build", 2.0)
    ranked = dm.ranked_demand()
    assert ranked[0][0] == "test"
    assert ranked[1][0] == "build"
    assert ranked[2][0] == "deploy"


def test_evaporate_reduces_intensity():
    dm = DemandMap(decay_rate=0.5)
    dm.deposit("deploy", 1.0)
    dm.evaporate(elapsed=1.0)
    assert dm.get_intensity("deploy") < 1.0


def test_evaporate_removes_below_threshold():
    dm = DemandMap(decay_rate=0.9, min_intensity=0.1)
    dm.deposit("deploy", 0.5)
    dm.evaporate(elapsed=2.0)
    assert dm.get_intensity("deploy") == 0.0
    assert "deploy" not in dm.signals


def test_snapshot():
    dm = DemandMap()
    dm.deposit("deploy", 1.0)
    dm.deposit("test", 2.0)
    snap = dm.snapshot()
    assert snap["deploy"] == 1.0
    assert snap["test"] == 2.0


def test_empty_highest_demand():
    dm = DemandMap()
    assert dm.highest_demand() is None
