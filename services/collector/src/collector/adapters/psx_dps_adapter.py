"""
PSX DPS Source Adapter.
Wraps the pinned umairsandhu/psx-dps client with request budgeting,
circuit breaking, timeout controls, and SHA-256 raw response hashing.
"""

from datetime import datetime, timezone
import time
from typing import Any, Dict, List, Optional
from .base import PSXSourceAdapter, UpstreamResponse
from ..budget import RequestBudgetManager
from ..cooldown import CooldownManager, CircuitBreakerTrippedError
from ..vendor.psx_dps.client import Client as DPSClient
from ..vendor.psx_dps.errors import NoData, UnknownSymbol, UpstreamError, RateLimited


class PSXDPSAdapter(PSXSourceAdapter):
    def __init__(
        self,
        cache_dir: Optional[str] = None,
        budget_manager: Optional[RequestBudgetManager] = None,
        cooldown_manager: Optional[CooldownManager] = None,
        min_interval_seconds: float = 1.0,
        timeout_seconds: float = 15.0,
    ):
        super().__init__(source_name="psx-dps")
        self.budget_manager = budget_manager or RequestBudgetManager()
        self.cooldown_manager = cooldown_manager or CooldownManager()
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
            self.cooldown_manager.record_error(status_code=503, retry_after=120, reason=str(e))
            raise

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            self.cooldown_manager.record_error(status_code=500, reason=str(e))
            raise

    def get_symbols(self) -> UpstreamResponse:
        return self._execute_bounded_call("symbols", lambda: self.client.symbols())

    def get_snapshot(self) -> UpstreamResponse:
        return self._execute_bounded_call("snapshot", lambda: self.client.snapshot())

    def get_eod(self, symbol: str) -> UpstreamResponse:
        return self._execute_bounded_call(f"eod/{symbol}", lambda: self.client.eod(symbol))

    def get_indices(self) -> UpstreamResponse:
        return self._execute_bounded_call("indices", lambda: self.client.indices())

    def get_intraday(self, symbol: str) -> UpstreamResponse:
        return self._execute_bounded_call(f"intraday/{symbol}", lambda: self.client.intraday(symbol))
