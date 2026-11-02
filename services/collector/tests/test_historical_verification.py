import pytest
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from collector.quarantine import QuarantineAuditor
from collector.reconciliation import EODReconciler


def test_historical_eod_timeseries_normalization():
    # PSX /timeseries/eod/<SYMBOL> format: array of [date_str, open, close, volume]
    raw_eod_response = [
        ["2026-10-26", 132.5, 134.0, 1500000],
        ["2026-10-27", 134.0, 133.8, 1200000],
        ["2026-10-28", 133.8, 135.2, 1800000],
        ["2026-10-29", 135.0, 136.0, 2100000],
        ["2026-10-30", 135.0, 136.2, 2450800],
    ]

    normalized_bars = []
    for item in raw_eod_response:
        trading_date, open_val, close_val, volume_val = item
        bar = {
            "symbol": "OGDC",
            "tradingDate": trading_date,
            "open": float(open_val),
            "high": None,  # High is null in eod() timeseries; must not be fabricated
            "low": None,   # Low is null in eod() timeseries; must not be fabricated
            "close": float(close_val),
            "volume": int(volume_val),
            "revision": 0,
            "is_unadjusted": True,  # Critical limitation: raw settlement close, not split/dividend-adjusted
        }
        valid, failure = QuarantineAuditor.audit_daily_bar(bar)
        assert valid is True
        assert failure is None
        normalized_bars.append(bar)

    assert len(normalized_bars) == 5
    assert normalized_bars[4]["close"] == 136.2
    assert normalized_bars[4]["high"] is None


def test_historical_intraday_tick_sequence_preservation():
    # PSX intraday ticks often report identical prices & volumes in the same second
    raw_ticks = [
        {"time": "09:30:15", "price": 135.5, "volume": 500},
        {"time": "09:30:15", "price": 135.5, "volume": 500},  # Identical tick
        {"time": "09:30:16", "price": 135.6, "volume": 1000},
    ]

    preserved_ticks = []
    for seq_id, tick in enumerate(raw_ticks):
        preserved_ticks.append({
            "symbol": "OGDC",
            "sequenceId": seq_id,  # Monotonic key prevents dropping identical trades
            "marketTimeKarachi": tick["time"],
            "price": tick["price"],
            "volume": tick["volume"],
        })

    assert len(preserved_ticks) == 3
    assert preserved_ticks[0]["sequenceId"] != preserved_ticks[1]["sequenceId"]
    assert preserved_ticks[0]["price"] == preserved_ticks[1]["price"]


def test_market_wide_datewise_historical_reconciliation():
    reconciler = EODReconciler()
    # POST /historical sample representing full-market settlement (subset of 712 symbols)
    official_market = [
        {"symbol": "OGDC", "open": 135.0, "high": 137.5, "low": 134.2, "close": 136.2, "volume": 2450800},
        {"symbol": "ENGROH", "open": 286.0, "high": 290.0, "low": 284.0, "close": 288.5, "volume": 850000},
        {"symbol": "HUBC", "open": 118.0, "high": 120.5, "low": 117.8, "close": 119.4, "volume": 1200000},
    ]
    preliminary_snapshot = [
        {"symbol": "OGDC", "current": 136.0, "volume": 2400000},  # Price & vol revised at settlement
        {"symbol": "ENGROH", "current": 288.5, "volume": 850000}, # Exact match
        {"symbol": "HUBC", "current": 119.4, "volume": 1190000},   # Vol revised
    ]

    res = reconciler.reconcile_trading_day("2026-10-30", official_market, preliminary_snapshot)
    assert res["totalSymbols"] == 3
    assert res["revisionsCount"] == 2
    assert res["quarantinedCount"] == 0

    ogdc_bar = next(b for b in res["bars"] if b["symbol"] == "OGDC")
    assert ogdc_bar["revision"] == 1
    assert ogdc_bar["high"] == 137.5
    assert ogdc_bar["low"] == 134.2

    engro_bar = next(b for b in res["bars"] if b["symbol"] == "ENGROH")
    assert engro_bar["revision"] == 0
