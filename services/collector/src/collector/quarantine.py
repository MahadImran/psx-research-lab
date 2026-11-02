"""
Data Validation and Quarantine Module.
Audits incoming records for data quality defects (negative prices, missing fields, invalid ranges).
Quarantined records are isolated and excluded from active serving.
"""

from typing import Any, Dict, List, Optional, Tuple
import math


class QuarantineAuditor:
    @staticmethod
    def audit_daily_bar(bar: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        Validate a daily bar. Returns (is_valid, failure_reason).
        Notice: High/Low are nullable in psx-dps eod() responses.
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
    def sanitize_and_flag(records: List[Dict[str, Any]], record_type: str = "daily_bar") -> List[Dict[str, Any]]:
        """Audit and tag records with is_quarantined and quarantine_reason."""
        result = []
        for rec in records:
            item = dict(rec)
            if record_type == "daily_bar":
                valid, reason = QuarantineAuditor.audit_daily_bar(item)
            elif record_type == "snapshot":
                valid, reason = QuarantineAuditor.audit_snapshot_observation(item)
            else:
                valid, reason = True, None

            item["is_quarantined"] = not valid
            item["quarantine_reason"] = reason
            result.append(item)
        return result
