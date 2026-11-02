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


def test_quarantine_rejects_high_lower_than_close_or_open():
    bad_bar = {
        "symbol": "SYS",
        "open": 450.0,
        "high": 440.0, # high < open!
        "low": 430.0,
        "close": 435.0,
        "volume": 200,
    }
    is_valid, reason = QuarantineAuditor.audit_daily_bar(bad_bar)
    assert is_valid is False
    assert "High (440.0) is lower than Open (450.0)" in reason


def test_quarantine_rejects_low_higher_than_close_or_open():
    bad_bar = {
        "symbol": "SYS",
        "open": 450.0,
        "high": 460.0,
        "low": 455.0, # low > close!
        "close": 440.0,
        "volume": 200,
    }
    is_valid, reason = QuarantineAuditor.audit_daily_bar(bad_bar)
    assert is_valid is False
    assert "Low (455.0) is higher than Open" in reason or "Close" in reason


def test_quarantine_classifies_data_grades():
    complete_bar = {"symbol": "OGDC", "open": 135.0, "high": 137.0, "low": 134.0, "close": 136.0, "volume": 1000}
    intraday_bar = {"symbol": "OGDC", "open": 135.0, "high": None, "low": None, "close": 136.0, "volume": 1000}
    seed_bar = {"source": "unverified-seed", "symbol": "OGDC", "open": 135.0, "high": None, "low": None, "close": 136.0, "volume": 1000}
    bad_bar = {"symbol": "OGDC", "open": -1.0, "high": None, "low": None, "close": 136.0, "volume": 1000}

    tagged = QuarantineAuditor.sanitize_and_flag([complete_bar, intraday_bar, seed_bar, bad_bar], record_type="daily_bar")
    assert tagged[0]["data_grade"] == "GRADE_A"
    assert tagged[1]["data_grade"] == "GRADE_B"
    assert tagged[2]["data_grade"] == "GRADE_C"
    assert tagged[3]["data_grade"] == "QUARANTINE"


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
