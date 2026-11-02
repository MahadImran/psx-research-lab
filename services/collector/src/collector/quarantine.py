"""
Data Validation and Quarantine Module.
Audits incoming records for data quality defects (negative prices, missing fields, invalid ranges).
Defines explicit DataQualityGrade (GRADE_A, GRADE_B, GRADE_C, QUARANTINE).
Quarantined records are isolated and excluded from active serving.
"""

from typing import Any, Dict, List, Optional, Tuple
import math


class DataQualityGrade:
    GRADE_A = "GRADE_A"  # Complete official settlement bar: Symbol, Date, Open, High, Low, Close, Volume. High >= max(Open, Close) and Low <= min(Open, Close).
    GRADE_B = "GRADE_B"  # Intraday regular observation: Open, Close (current), Volume. High/Low nullable or partial (psx-dps eod ticker route).
    GRADE_C = "GRADE_C"  # Unverified historical seed or alternate source with missing depth.
    QUARANTINE = "QUARANTINE"  # Defective: negative price, NaN, High < Low, or corrupt timestamps.


class QuarantineAuditor:
    @staticmethod
    def audit_daily_bar(bar: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        Validate a daily bar. Returns (is_valid, failure_reason).
        Notice: High/Low are nullable in psx-dps eod() responses.
        When present, High must be >= max(open, close) and Low must be <= min(open, close).
        """
        symbol = bar.get("symbol")
        if not symbol or not isinstance(symbol, str) or len(symbol) > 20:
            return False, "Missing or invalid symbol format"

        close = bar.get("close")
        if close is None or not isinstance(close, (int, float)) or math.isnan(close) or close <= 0:
            return False, f"Invalid close price: {close}"

        open_val = bar.get("open")
        if open_val is None or not isinstance(open_val, (int, float)) or math.isnan(open_val) or open_val <= 0:
            return False, f"Invalid open price: {open_val}"

        volume = bar.get("volume")
        if volume is None or not isinstance(volume, int) or volume < 0:
            return False, f"Invalid volume: {volume}"

        high = bar.get("high")
        low = bar.get("low")
        if high is not None and low is not None:
            if math.isnan(high) or math.isnan(low) or high < low:
                return False, f"High ({high}) is lower than Low ({low})"
            if high < open_val or high < close:
                return False, f"High ({high}) is lower than Open ({open_val}) or Close ({close})"
            if low > open_val or low > close:
                return False, f"Low ({low}) is higher than Open ({open_val}) or Close ({close})"

        return True, None

    @staticmethod
    def audit_snapshot_observation(obs: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        symbol = obs.get("symbol")
        if not symbol or not isinstance(symbol, str) or len(symbol) > 20:
            return False, "Missing or invalid symbol"

        current = obs.get("current")
        if current is None or not isinstance(current, (int, float)) or math.isnan(current) or current <= 0:
            return False, f"Invalid current price: {current}"

        volume = obs.get("volume")
        if volume is None or not isinstance(volume, int) or volume < 0:
            return False, f"Invalid volume: {volume}"

        return True, None

    @staticmethod
    def classify_bar_grade(bar: Dict[str, Any], is_valid: bool) -> str:
        """Classify bar into explicit research data quality grade."""
        if not is_valid:
            return DataQualityGrade.QUARANTINE
        source = str(bar.get("source", "")).lower()
        if "seed" in source or "unverified" in source:
            return DataQualityGrade.GRADE_C
        high = bar.get("high")
        low = bar.get("low")
        if high is not None and low is not None:
            return DataQualityGrade.GRADE_A
        return DataQualityGrade.GRADE_B

    @staticmethod
    def sanitize_and_flag(records: List[Dict[str, Any]], record_type: str = "daily_bar") -> List[Dict[str, Any]]:
        """Audit and tag records with is_quarantined, quarantine_reason, and data_grade."""
        result = []
        for rec in records:
            item = dict(rec)
            if record_type == "daily_bar":
                valid, reason = QuarantineAuditor.audit_daily_bar(item)
                item["data_grade"] = QuarantineAuditor.classify_bar_grade(item, valid)
            elif record_type == "snapshot":
                valid, reason = QuarantineAuditor.audit_snapshot_observation(item)
                item["data_grade"] = DataQualityGrade.GRADE_B if valid else DataQualityGrade.QUARANTINE
            else:
                valid, reason = True, None
                item["data_grade"] = DataQualityGrade.GRADE_B

            item["is_quarantined"] = not valid
            item["quarantine_reason"] = reason
            result.append(item)
        return result
