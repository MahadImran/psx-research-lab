import pytest
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from collector.reconciliation import EODReconciler


def test_reconciliation_exact_match():
    reconciler = EODReconciler()
    official = [
        {"symbol": "OGDC", "open": 135.0, "high": 138.0, "low": 134.0, "close": 136.5, "volume": 10000},
        {"symbol": "ENGROH", "open": 280.0, "high": 285.0, "low": 279.0, "close": 283.0, "volume": 5000},
    ]
    preliminary = [
        {"symbol": "OGDC", "current": 136.5, "volume": 10000},
        {"symbol": "ENGROH", "current": 283.0, "volume": 5000},
    ]

    res = reconciler.reconcile_trading_day("2026-11-02", official, preliminary)
    assert res["totalSymbols"] == 2
    assert res["revisionsCount"] == 0
    assert res["discrepanciesCount"] == 0
    assert len(res["bars"]) == 2
    assert res["bars"][0]["revision"] == 0
    assert res["bars"][0]["isQuarantined"] is False


def test_reconciliation_detects_price_and_volume_revisions():
    reconciler = EODReconciler()
    official = [
        # Close adjusted from 136.0 (preliminary) to 136.5 (official settlement)
        {"symbol": "OGDC", "open": 135.0, "high": 138.0, "low": 134.0, "close": 136.5, "volume": 10500},
        # Volume adjusted from 4800 to 5000
        {"symbol": "ENGROH", "open": 280.0, "high": 285.0, "low": 279.0, "close": 283.0, "volume": 5000},
    ]
    preliminary = [
        {"symbol": "OGDC", "current": 136.0, "volume": 10000},
        {"symbol": "ENGROH", "current": 283.0, "volume": 4800},
    ]

    res = reconciler.reconcile_trading_day("2026-11-02", official, preliminary)
    assert res["revisionsCount"] == 2
    assert res["discrepanciesCount"] == 2

    # Check OGDC discrepancy
    ogdc_disc = next(d for d in res["discrepancies"] if d["symbol"] == "OGDC")
    assert ogdc_disc["type"] == "SETTLEMENT_PRICE_ADJUSTMENT"
    assert ogdc_disc["diff_price"] == 0.5

    # Check ENGROH discrepancy
    engro_disc = next(d for d in res["discrepancies"] if d["symbol"] == "ENGROH")
    assert engro_disc["type"] == "VOLUME_RECONCILIATION"


def test_reconciliation_quarantines_defective_bars():
    reconciler = EODReconciler()
    official = [
        # Negative close price
        {"symbol": "DEFECT1", "open": 100.0, "high": 105.0, "low": 95.0, "close": -10.0, "volume": 500},
        # High lower than Low
        {"symbol": "DEFECT2", "open": 50.0, "high": 45.0, "low": 55.0, "close": 48.0, "volume": 500},
    ]

    res = reconciler.reconcile_trading_day("2026-11-02", official)
    assert res["totalSymbols"] == 2
    assert res["quarantinedCount"] == 2
    assert res["bars"][0]["isQuarantined"] is True
    assert res["bars"][1]["isQuarantined"] is True
