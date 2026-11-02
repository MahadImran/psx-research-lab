import pytest
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from collector.quarantine import QuarantineAuditor


def test_quarantine_rejects_negative_or_nan_prices():
    bad_bar = {
        "symbol": "OGDC",
        "open": -10.0,
        "high": None,
        "low": None,
        "close": 135.0,
        "volume": 1000,
    }
    is_valid, reason = QuarantineAuditor.audit_daily_bar(bad_bar)
    assert is_valid is False
    assert "Invalid open price" in reason


def test_quarantine_rejects_high_lower_than_low():
    bad_bar = {
        "symbol": "ENGRO",
        "open": 285.0,
        "high": 280.0,
        "low": 290.0, # low > high!
        "close": 282.0,
        "volume": 500,
    }
    is_valid, reason = QuarantineAuditor.audit_daily_bar(bad_bar)
    assert is_valid is False
    assert "High (280.0) is lower than Low (290.0)" in reason


def test_quarantine_accepts_valid_bar_with_nullable_high_low():
    valid_bar = {
        "symbol": "OGDC",
        "open": 135.0,
        "high": None, # Nullable for psx-dps eod()
        "low": None,
        "close": 136.2,
        "volume": 50000,
    }
    is_valid, reason = QuarantineAuditor.audit_daily_bar(valid_bar)
    assert is_valid is True
    assert reason is None


def test_sanitize_and_flag_tags_records():
    records = [
        {"symbol": "OGDC", "open": 135.0, "high": None, "low": None, "close": 136.0, "volume": 1000},
        {"symbol": "INVALID", "open": -5.0, "high": None, "low": None, "close": 10.0, "volume": 100},
    ]
    tagged = QuarantineAuditor.sanitize_and_flag(records, record_type="daily_bar")
    assert len(tagged) == 2
    assert tagged[0]["is_quarantined"] is False
    assert tagged[1]["is_quarantined"] is True
    assert tagged[1]["quarantine_reason"] is not None
