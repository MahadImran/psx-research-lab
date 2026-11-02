import pytest
import os
import sys

# Ensure collector package is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from collector.adapters.fixture_adapter import FixtureAdapter
from collector.budget import RequestBudgetManager
from collector.cooldown import CooldownManager


def test_fixture_adapter_symbols():
    budget = RequestBudgetManager(daily_limit=250)
    cooldown = CooldownManager()
    adapter = FixtureAdapter(budget_manager=budget, cooldown_manager=cooldown)

    resp = adapter.get_symbols()
    assert resp.status_code == 200
    assert resp.endpoint == "symbols"
    assert resp.record_count >= 5
    assert len(resp.raw_sha256) == 64
    assert any(s["symbol"] == "OGDC" for s in resp.data)


def test_fixture_adapter_snapshot():
    budget = RequestBudgetManager(daily_limit=250)
    cooldown = CooldownManager()
    adapter = FixtureAdapter(budget_manager=budget, cooldown_manager=cooldown)

    resp = adapter.get_snapshot()
    assert resp.status_code == 200
    assert resp.endpoint == "snapshot"
    assert "observations" in resp.data
    assert len(resp.data["observations"]) >= 3


def test_fixture_adapter_eod():
    budget = RequestBudgetManager(daily_limit=250)
    cooldown = CooldownManager()
    adapter = FixtureAdapter(budget_manager=budget, cooldown_manager=cooldown)

    resp = adapter.get_eod("OGDC")
    assert resp.status_code == 200
    assert resp.endpoint == "eod/OGDC"
    # High/Low are null in eod bars, open/close/volume must exist
    for bar in resp.data:
        assert "open" in bar
        assert "close" in bar
        assert "volume" in bar
