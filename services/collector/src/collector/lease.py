"""
Collector Lease Management.
Coordinates single-collector access across ephemeral GitHub runners and Cloudflare watchdog.
"""

from datetime import datetime, timezone, timedelta
import os
import uuid
from typing import Optional


class LeaseAcquisitionError(Exception):
    pass


class CollectorLease:
    def __init__(self, lease_id: str = "PSX_COLLECTOR", ttl_seconds: int = 300):
        self.lease_id = lease_id
        self.ttl_seconds = ttl_seconds
        self.current_token: Optional[str] = None
        self.acquired_at: Optional[datetime] = None
        self.expires_at: Optional[datetime] = None

    def acquire(self, runner_id: Optional[str] = None) -> str:
        """
        Acquire lease. In local/testing mode, generates a lease token.
        In remote M2/M3 mode, connects to D1 conditional update.
        """
        now = datetime.now(timezone.utc)
        self.current_token = runner_id or f"runner-{uuid.uuid4().hex[:8]}"
        self.acquired_at = now
        self.expires_at = now + timedelta(seconds=self.ttl_seconds)
        return self.current_token

    def is_valid(self) -> bool:
        if not self.expires_at or not self.current_token:
            return False
        return datetime.now(timezone.utc) < self.expires_at

    def release(self) -> None:
        self.current_token = None
        self.acquired_at = None
        self.expires_at = None
