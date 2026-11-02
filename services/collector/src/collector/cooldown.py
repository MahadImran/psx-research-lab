"""
Circuit Breaker and Cooldown Manager.
Respects 429 Too Many Requests, 503 Service Unavailable, and Retry-After headers.
Never rotates proxies or bypasses blocks.
"""

from datetime import datetime, timezone, timedelta
import json
import os
from typing import Optional


class CircuitBreakerTrippedError(Exception):
    """Raised when an upstream request is attempted while the source is in cooldown."""
    pass


class CooldownManager:
    def __init__(
        self,
        default_cooldown_seconds: int = 300,
        max_consecutive_errors: int = 3,
        state_file: Optional[str] = None
    ):
        self.default_cooldown_seconds = default_cooldown_seconds
        self.max_consecutive_errors = max_consecutive_errors
        self.state_file = state_file or os.path.expanduser("~/.psx_cooldown_state.json")
        self.consecutive_errors = 0
        self.cooldown_until: Optional[datetime] = None
        self._load_state()

    def _load_state(self) -> None:
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r") as f:
                    data = json.load(f)
                    self.consecutive_errors = data.get("consecutive_errors", 0)
                    cu = data.get("cooldown_until")
                    if cu:
                        self.cooldown_until = datetime.fromisoformat(cu)
            except Exception:
                pass

    def _save_state(self) -> None:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.state_file)), exist_ok=True)
            with open(self.state_file, "w") as f:
                json.dump({
                    "consecutive_errors": self.consecutive_errors,
                    "cooldown_until": self.cooldown_until.isoformat() if self.cooldown_until else None,
                }, f, indent=2)
        except Exception:
            pass

    def is_in_cooldown(self) -> bool:
        if not self.cooldown_until:
            return False
        now = datetime.now(timezone.utc)
        if now < self.cooldown_until:
            return True
        # Cooldown expired
        self.cooldown_until = None
        self._save_state()
        return False

    def remaining_cooldown_seconds(self) -> float:
        if not self.is_in_cooldown() or not self.cooldown_until:
            return 0.0
        now = datetime.now(timezone.utc)
        diff = (self.cooldown_until - now).total_seconds()
        return max(0.0, diff)

    def check_preflight(self) -> None:
        """Call before attempting an upstream request. Raises if cooled down."""
        if self.is_in_cooldown():
            raise CircuitBreakerTrippedError(
                f"Source circuit breaker is active! Cooldown remaining: {self.remaining_cooldown_seconds():.1f}s"
            )

    def record_success(self) -> None:
        """Reset consecutive error count on successful upstream response."""
        self.consecutive_errors = 0
        self.cooldown_until = None
        self._save_state()

    def record_error(
        self,
        status_code: int,
        retry_after: Optional[int] = None,
        reason: Optional[str] = None
    ) -> None:
        """Record upstream error and calculate cooldown."""
        self.consecutive_errors += 1
        now = datetime.now(timezone.utc)

        if status_code == 429:
            # Respect Retry-After if provided, else use default
            cooldown_sec = retry_after if (retry_after and retry_after > 0) else self.default_cooldown_seconds
            self.cooldown_until = now + timedelta(seconds=cooldown_sec)
        elif status_code == 503:
            cooldown_sec = retry_after if (retry_after and retry_after > 0) else self.default_cooldown_seconds
            self.cooldown_until = now + timedelta(seconds=cooldown_sec)
        elif status_code == 404:
            # Missing resource / endpoint does not indicate server-wide outage
            self.consecutive_errors = max(0, self.consecutive_errors - 1)
        elif self.consecutive_errors >= self.max_consecutive_errors:
            # Exponential backoff for generic errors
            backoff_sec = min(3600, self.default_cooldown_seconds * (2 ** (self.consecutive_errors - self.max_consecutive_errors)))
            self.cooldown_until = now + timedelta(seconds=backoff_sec)

        self._save_state()
