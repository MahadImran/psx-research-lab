"""
PSX End-Of-Day (EOD) Reconciliation Module.
Reconciles preliminary intraday observations with official PSX datewise settlement bars.
Flags price adjustments, revisions, and anomalies.
"""

from datetime import datetime, timezone
import hashlib
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from .quarantine import QuarantineAuditor
from .storage import StorageManager

logger = logging.getLogger(__name__)


class EODReconciler:
    def __init__(self, source_name: str = "psx-dps"):
        self.source_name = source_name

    def reconcile_trading_day(
        self,
        trading_date: str,
        official_records: List[Dict[str, Any]],
        preliminary_snapshots: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Reconciles official POST /historical records with preliminary snapshot observations.
        Returns a structured summary containing canonical daily bars, revisions, and discrepancies.
        """
        prelim_map: Dict[str, Dict[str, Any]] = {}
        if preliminary_snapshots:
            for obs in preliminary_snapshots:
                sym = obs.get("symbol", "").upper()
                if sym:
                    prelim_map[sym] = obs

        daily_bars: List[Dict[str, Any]] = []
        discrepancies: List[Dict[str, Any]] = []
        quarantined_count = 0
        revisions_count = 0
        now_utc = datetime.now(timezone.utc).isoformat()

        for raw_bar in official_records:
            symbol = str(raw_bar.get("symbol", "")).upper()
            if not symbol:
                continue

            open_val = float(raw_bar.get("open", 0.0) or 0.0)
            high_val = float(raw_bar.get("high")) if raw_bar.get("high") is not None else None
            low_val = float(raw_bar.get("low")) if raw_bar.get("low") is not None else None
            close_val = float(raw_bar.get("close", 0.0) or raw_bar.get("current", 0.0) or 0.0)
            vol_val = int(raw_bar.get("volume", 0) or 0)

            # Audit through quarantine rules
            bar_candidate = {
                "symbol": symbol,
                "open": open_val,
                "high": high_val,
                "low": low_val,
                "close": close_val,
                "volume": vol_val,
            }
            is_valid, failure_reason = QuarantineAuditor.audit_daily_bar(bar_candidate)
            if not is_valid:
                quarantined_count += 1

            # Check comparison against preliminary snapshot
            revision = 0
            quarantine_reason = failure_reason
            prelim = prelim_map.get(symbol)
            if prelim:
                prelim_close = float(prelim.get("current", 0.0) or prelim.get("close", 0.0) or 0.0)
                prelim_vol = int(prelim.get("volume", 0) or 0)

                diff_price = abs(close_val - prelim_close)
                diff_vol = abs(vol_val - prelim_vol)

                # If settlement price differs from preliminary by more than 0.01 or volume by > 0:
                if diff_price > 0.01 or diff_vol > 0:
                    revision = 1
                    revisions_count += 1
                    discrepancies.append({
                        "symbol": symbol,
                        "prelim_close": prelim_close,
                        "settlement_close": close_val,
                        "diff_price": round(diff_price, 4),
                        "prelim_volume": prelim_vol,
                        "settlement_volume": vol_val,
                        "type": "SETTLEMENT_PRICE_ADJUSTMENT" if diff_price > 0.01 else "VOLUME_RECONCILIATION",
                    })

            # Calculate content hash for deterministic deduplication
            bar_repr = f"{symbol}:{trading_date}:{open_val}:{high_val}:{low_val}:{close_val}:{vol_val}:{revision}"
            bar_hash = hashlib.sha256(bar_repr.encode("utf-8")).hexdigest()

            daily_bars.append({
                "source": self.source_name,
                "symbol": symbol,
                "tradingDate": trading_date,
                "open": open_val,
                "high": high_val,
                "low": low_val,
                "close": close_val,
                "volume": vol_val,
                "revision": revision,
                "dataGrade": QuarantineAuditor.classify_bar_grade(bar_candidate, is_valid),
                "isQuarantined": not is_valid,
                "quarantineReason": quarantine_reason,
                "hash": bar_hash,
                "fetchedAtUtc": now_utc,
            })

        payload_bytes = json.dumps(daily_bars, sort_keys=True).encode("utf-8")
        payload_sha256 = hashlib.sha256(payload_bytes).hexdigest()

        return {
            "tradingDate": trading_date,
            "source": self.source_name,
            "generatedAtUtc": now_utc,
            "totalSymbols": len(daily_bars),
            "revisionsCount": revisions_count,
            "quarantinedCount": quarantined_count,
            "discrepanciesCount": len(discrepancies),
            "discrepancies": discrepancies,
            "payloadSha256": payload_sha256,
            "bars": daily_bars,
        }
