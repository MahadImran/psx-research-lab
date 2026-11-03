"""
Abstract Base Adapter for PSX Data Sources.
Enforces typed output, raw payload hashing, and uniform error semantics.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import hashlib
import json


@dataclass
class UpstreamResponse:
    source: str
    endpoint: str
    data: Any
    raw_sha256: str
    record_count: int
    duration_ms: float
    is_cached: bool = False
    status_code: int = 200
    headers: Optional[Dict[str, str]] = None


class PSXSourceAdapter(ABC):
    """Abstract base class for all PSX market data adapters."""

    def __init__(self, source_name: str):
        self.source_name = source_name

    @staticmethod
    def compute_sha256(data: Any) -> str:
        """Compute SHA-256 hash of data representation."""
        if isinstance(data, (bytes, bytearray)):
            return hashlib.sha256(data).hexdigest()
        serialized = json.dumps(data, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(serialized).hexdigest()

    @abstractmethod
    def get_symbols(self) -> UpstreamResponse:
        """Fetch directory of trading symbols."""
        pass

    @abstractmethod
    def get_snapshot(self) -> UpstreamResponse:
        """Fetch complete market-wide board snapshot."""
        pass

    @abstractmethod
    def get_eod(self, symbol: str) -> UpstreamResponse:
        """Fetch end-of-day daily bars for a given symbol."""
        pass

    @abstractmethod
    def get_indices(self) -> UpstreamResponse:
        """Fetch current index values (KSE100, KSE30, etc.)."""
        pass

    @abstractmethod
    def get_intraday(self, symbol: str) -> UpstreamResponse:
        """Fetch current-session intraday ticks for a given symbol."""
        pass
