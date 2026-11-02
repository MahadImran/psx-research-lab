"""
Offline Fixture Adapter.
Loads deterministic PSX responses from data/fixtures/ for testing without network requests.
Supports fault injection: 429 Retry-After, 503, duplicate responses, malformed records.
"""

from datetime import datetime, timezone
import json
import os
import time
from typing import Any, Dict, List, Optional
from .base import PSXSourceAdapter, UpstreamResponse
from ..budget import RequestBudgetManager
from ..cooldown import CooldownManager, CircuitBreakerTrippedError


class FixtureAdapter(PSXSourceAdapter):
    def __init__(
        self,
        fixtures_dir: Optional[str] = None,
        budget_manager: Optional[RequestBudgetManager] = None,
        cooldown_manager: Optional[CooldownManager] = None
    ):
        super().__init__(source_name="fixture-offline")
        if fixtures_dir:
            self.fixtures_dir = fixtures_dir
        else:
            # Default to monorepo data/fixtures
            base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../../data/fixtures"))
            self.fixtures_dir = base_dir

        self.budget_manager = budget_manager or RequestBudgetManager()
        self.cooldown_manager = cooldown_manager or CooldownManager()
        self.simulate_429: bool = False
        self.simulate_503: bool = False
        self.simulate_malformed: bool = False
        self.simulate_delay_ms: float = 0.0

    def _read_fixture(self, filename: str) -> Any:
        path = os.path.join(self.fixtures_dir, filename)
        if not os.path.exists(path):
            raise FileNotFoundError(f"Fixture file not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _execute_mock_call(self, endpoint: str, filename: str) -> UpstreamResponse:
        # 1. Preflight check circuit breaker cooldown
        self.cooldown_manager.check_preflight()

        # 2. Reserve upstream budget
        self.budget_manager.record_request(endpoint)

        start_time = time.time()
        if self.simulate_delay_ms > 0:
            time.sleep(self.simulate_delay_ms / 1000.0)

        # 3. Fault injection checks
        if self.simulate_429:
            self.cooldown_manager.record_error(status_code=429, retry_after=300, reason="Rate limit simulated")
            data = self._read_fixture("error_429.json")
            duration = (time.time() - start_time) * 1000
            return UpstreamResponse(
                source=self.source_name,
                endpoint=endpoint,
                data=data,
                raw_sha256=self.compute_sha256(data),
                record_count=0,
                duration_ms=duration,
                status_code=429,
                headers={"Retry-After": "300"},
            )

        if self.simulate_503:
            self.cooldown_manager.record_error(status_code=503, retry_after=120, reason="Service unavailable simulated")
            data = self._read_fixture("error_503.json")
            duration = (time.time() - start_time) * 1000
            return UpstreamResponse(
                source=self.source_name,
                endpoint=endpoint,
                data=data,
                raw_sha256=self.compute_sha256(data),
                record_count=0,
                duration_ms=duration,
                status_code=503,
            )

        if self.simulate_malformed:
            data = self._read_fixture("malformed.json")
            duration = (time.time() - start_time) * 1000
            return UpstreamResponse(
                source=self.source_name,
                endpoint=endpoint,
                data=data,
                raw_sha256=self.compute_sha256(data),
                record_count=len(data.get("observations", [])),
                duration_ms=duration,
                status_code=200,
            )

        # Normal successful read
        data = self._read_fixture(filename)
        self.cooldown_manager.record_success()
        duration = (time.time() - start_time) * 1000

        count = len(data) if isinstance(data, list) else len(data.get("observations", []))
        return UpstreamResponse(
            source=self.source_name,
            endpoint=endpoint,
            data=data,
            raw_sha256=self.compute_sha256(data),
            record_count=count,
            duration_ms=duration,
            status_code=200,
        )

    def get_symbols(self) -> UpstreamResponse:
        return self._execute_mock_call("symbols", "symbols.json")

    def get_snapshot(self) -> UpstreamResponse:
        return self._execute_mock_call("snapshot", "snapshot.json")

    def get_eod(self, symbol: str) -> UpstreamResponse:
        return self._execute_mock_call(f"eod/{symbol}", "eod_bars.json")

    def get_indices(self) -> UpstreamResponse:
        return self._execute_mock_call("indices", "indices.json")

    def get_intraday(self, symbol: str) -> UpstreamResponse:
        return self._execute_mock_call(f"intraday/{symbol}", "intraday_ticks.json")
