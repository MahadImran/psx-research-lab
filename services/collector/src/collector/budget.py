"""
Upstream Request Budget and Safety Fuse.
Enforces the strict contract: <= 250 source requests per rolling 24 hours.
Persistent and fail-closed: if the budget is exhausted, further network requests are prohibited.
"""

from datetime import datetime, timezone, timedelta
import json
import os
from typing import Dict, List, Optional


class BudgetExceededError(Exception):
    """Raised when the 24h upstream request limit is reached or exceeded."""
    pass


class RequestBudgetManager:
    """Manages persistent upstream request allocations across runs."""

    def __init__(
        self,
        daily_limit: int = 250,
        state_file: Optional[str] = None
    ):
        self.daily_limit = daily_limit
        self.state_file = state_file or os.path.expanduser("~/.psx_budget_state.json")
        self.history: List[Dict[str, str]] = []
        self._load_state()

    def _load_state(self) -> None:
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r") as f:
                    data = json.load(f)
                    self.history = data.get("history", [])
            except Exception:
                self.history = []

    def _save_state(self) -> None:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.state_file)), exist_ok=True)
            with open(self.state_file, "w") as f:
                json.dump({"history": self.history}, f, indent=2)
        except Exception:
            pass

    def _purge_old_records(self, now: datetime) -> None:
        cutoff = now - timedelta(hours=24)
        cutoff_iso = cutoff.isoformat()
        self.history = [r for r in self.history if r["timestamp"] >= cutoff_iso]

    def get_used_count(self) -> int:
        now = datetime.now(timezone.utc)
        self._purge_old_records(now)
        return len(self.history)

    def get_remaining_count(self) -> int:
        return max(0, self.daily_limit - self.get_used_count())

    def can_request(self, count: int = 1) -> bool:
        return self.get_remaining_count() >= count

    def record_request(self, endpoint: str) -> None:
        """Reserve a request slot. Fails closed if budget exceeded."""
        now = datetime.now(timezone.utc)
        self._purge_old_records(now)
        if len(self.history) >= self.daily_limit:
            raise BudgetExceededError(
                f"Rolling 24h upstream budget limit ({self.daily_limit}) reached! Refusing request to {endpoint}."
            )
        self.history.append({
            "timestamp": now.isoformat(),
            "endpoint": endpoint,
        })
        self._save_state()

    def reset_for_testing(self) -> None:
        """Helper for unit tests."""
        self.history = []
        if os.path.exists(self.state_file):
            try:
                os.remove(self.state_file)
            except Exception:
                pass
