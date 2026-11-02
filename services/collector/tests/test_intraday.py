import pytest
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from collector.adapters.fixture_adapter import FixtureAdapter


def test_intraday_sequence_preservation():
    """
    Contract test: identical ticks (same timestamp, price, volume) must NOT be dropped
    by a naive (timestamp, price) unique constraint.
    SequenceId must distinguish them.
    """
    adapter = FixtureAdapter()
    resp = adapter.get_intraday("OGDC")
    assert resp.status_code == 200

    ticks = resp.data
    assert len(ticks) >= 3

    # Check that sequenceIds are strictly ordered
    seq_ids = [t["sequenceId"] for t in ticks]
    assert seq_ids == sorted(seq_ids)

    # In our fixture, tick 1 and 2 have identical timestamp, price, and volume
    tick1, tick2 = ticks[0], ticks[1]
    assert tick1["timestampUtc"] == tick2["timestampUtc"]
    assert tick1["price"] == tick2["price"]
    assert tick1["volume"] == tick2["volume"]
    assert tick1["sequenceId"] != tick2["sequenceId"]
