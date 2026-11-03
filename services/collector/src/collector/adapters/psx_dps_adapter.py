"""
PSX DPS Source Adapter.
Wraps the pinned umairsandhu/psx-dps client with request budgeting,
session token extraction, circuit breaking, and SHA-256 raw hashing.
"""

from datetime import datetime, timezone
import os
import time
from typing import Any, Dict, List, Optional
from .base import PSXSourceAdapter, UpstreamResponse
from ..budget import RequestBudgetManager
from ..cooldown import CooldownManager, CircuitBreakerTrippedError
from ..session_token import PSXTokenProvider
from ..vendor.psx_dps.client import Client as DPSClient
from ..vendor.psx_dps.errors import NoData, UnknownSymbol, UpstreamError, RateLimited
from ..vendor.psx_dps import transport

# Ensure reliable health probe route across PSX infrastructure
transport.PROBE_PATH = os.environ.get("PSX_PROBE_PATH", "/indices")

# Canonical ticker aliases on PSX (e.g. corporate mergers/restructurings)
TICKER_ALIASES = {
    "ENGRO": "ENGROH",
}


class PSXDPSAdapter(PSXSourceAdapter):
    def __init__(
        self,
        cache_dir: Optional[str] = None,
        budget_manager: Optional[RequestBudgetManager] = None,
        cooldown_manager: Optional[CooldownManager] = None,
        token_provider: Optional[PSXTokenProvider] = None,
        min_interval_seconds: float = 1.0,
        timeout_seconds: float = 15.0,
    ):
        super().__init__(source_name="psx-dps")
        self.budget_manager = budget_manager or RequestBudgetManager()
        self.cooldown_manager = cooldown_manager or CooldownManager(coordinator=self.budget_manager)
        self.token_provider = token_provider or PSXTokenProvider(budget_recorder=self.budget_manager)
        self.min_interval_seconds = min_interval_seconds
        self.timeout_seconds = timeout_seconds

        # Initialize underlying DPS client with fair use settings
        self.client = DPSClient(
            cache_dir=cache_dir,
            min_interval=min_interval_seconds,
            daily_budget=250,
            timeout=timeout_seconds,
            retries=2,
            respect_cooldown=True,
        )
        self.client.transport.token_provider = self.token_provider
        self.client.transport.budget_recorder = self.budget_manager
        self.token_provider.budget_recorder = self.budget_manager

    def _execute_bounded_call(self, endpoint_name: str, call_fn) -> UpstreamResponse:
        # 1. Circuit breaker preflight
        self.cooldown_manager.check_preflight()

        # 2. Upstream persistent budget check & reservation
        self.budget_manager.record_request(endpoint_name)

        start_time = time.time()
        try:
            data = call_fn()
            duration_ms = (time.time() - start_time) * 1000

            # Record success on circuit breaker
            self.cooldown_manager.record_success()

            # Record count
            if isinstance(data, list):
                count = len(data)
            elif isinstance(data, dict):
                count = len(data.get("rows", data.get("observations", [data])))
            else:
                count = 1

            return UpstreamResponse(
                source=self.source_name,
                endpoint=endpoint_name,
                data=data,
                raw_sha256=self.compute_sha256(data),
                record_count=count,
                duration_ms=duration_ms,
                status_code=200,
            )

        except RateLimited as e:
            duration_ms = (time.time() - start_time) * 1000
            self.cooldown_manager.record_error(status_code=429, retry_after=300, reason=str(e))
            raise

        except UpstreamError as e:
            duration_ms = (time.time() - start_time) * 1000
            err_str = str(e)
            if "404" in err_str:
                self.cooldown_manager.record_error(status_code=404, reason=err_str)
            else:
                self.cooldown_manager.record_error(status_code=503, retry_after=120, reason=err_str)
            raise

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            self.cooldown_manager.record_error(status_code=500, reason=str(e))
            raise

    def get_symbols(self) -> UpstreamResponse:
        """Fetch symbols. If /symbols returns 404, fall back to /indices/ALLSHR."""
        def fetch():
            try:
                return self.client.symbols()
            except UpstreamError:
                constituents = self.client.index_constituents("ALLSHR")
                return [
                    {
                        "symbol": c.get("SYMBOL", ""),
                        "name": c.get("NAME", ""),
                        "sectorName": "ALLSHR",
                        "isETF": False,
                        "isDebt": False,
                    }
                    for c in constituents
                ]
        return self._execute_bounded_call("symbols", fetch)

    def get_snapshot(self) -> UpstreamResponse:
        """Fetch whole market snapshot. If /market-watch returns 404, fall back to ALLSHR."""
        def fetch():
            try:
                return self.client.snapshot()
            except UpstreamError:
                constituents = self.client.index_constituents("ALLSHR")
                rows = []
                for c in constituents:
                    try:
                        curr = float(c.get("CURRENT", 0))
                        chg = float(c.get("CHANGE", 0))
                        vol = int(float(c.get("VOLUME", 0)))
                    except (ValueError, TypeError):
                        curr, chg, vol = 0.0, 0.0, 0
                    rows.append({
                        "symbol": c.get("SYMBOL", ""),
                        "current": curr,
                        "change": chg,
                        "volume": vol,
                        "name": c.get("NAME", ""),
                    })
                return {
                    "source": "psx-dps-allshr",
                    "captured_at": datetime.now(timezone.utc).isoformat(),
                    "session": "ACTIVE_ALLSHR",
                    "rows": rows,
                }
        return self._execute_bounded_call("snapshot", fetch)

    def get_eod(self, symbol: str) -> UpstreamResponse:
        target_symbol = TICKER_ALIASES.get(symbol.upper(), symbol.upper())
        return self._execute_bounded_call(f"eod/{target_symbol}", lambda: self.client.eod(target_symbol))

    def get_indices(self) -> UpstreamResponse:
        return self._execute_bounded_call("indices", lambda: self.client.indices())

    def get_intraday(self, symbol: str) -> UpstreamResponse:
        target_symbol = TICKER_ALIASES.get(symbol.upper(), symbol.upper())
        return self._execute_bounded_call(f"intraday/{target_symbol}", lambda: self.client.intraday(target_symbol))

    def get_historical_date(self, trading_date: str) -> UpstreamResponse:
        """Fetch market-wide historical daily bars for a specific date (POST /historical)."""
        return self._execute_bounded_call(f"history_date/{trading_date}", lambda: self.client.history_by_date(trading_date))
