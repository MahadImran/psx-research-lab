"""
Raw Storage and Deduplication Manager.
Computes SHA-256, compresses responses, and detects duplicate polls.
"""

from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from typing import Any, Dict, Optional, Tuple


class StorageManager:
    @staticmethod
    def hash_payload(data: Any) -> str:
        if isinstance(data, (bytes, bytearray)):
            return hashlib.sha256(data).hexdigest()
        serialized = json.dumps(data, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(serialized).hexdigest()

    @staticmethod
    def compress_bytes(raw_bytes: bytes) -> bytes:
        return gzip.compress(raw_bytes, compresslevel=9)

    @staticmethod
    def decompress_bytes(compressed_bytes: bytes) -> bytes:
        return gzip.decompress(compressed_bytes)

    @staticmethod
    def stage_response(
        output_dir: str,
        source: str,
        endpoint: str,
        trading_date: str,
        data: Any
    ) -> Tuple[str, str, int]:
        """
        Stage raw response as compressed .json.gz file.
        Returns: (file_path, sha256_hash, compressed_byte_size)
        """
        os.makedirs(output_dir, exist_ok=True)
        raw_json = json.dumps(data, indent=2, default=str).encode("utf-8")
        sha256_hash = hashlib.sha256(raw_json).hexdigest()
        compressed = gzip.compress(raw_json, compresslevel=9)

        timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        filename = f"{source}_{endpoint}_{trading_date}_{timestamp_str}_{sha256_hash[:8]}.json.gz"
        file_path = os.path.join(output_dir, filename)

        with open(file_path, "wb") as f:
            f.write(compressed)

        return file_path, sha256_hash, len(compressed)

    @staticmethod
    def is_duplicate_poll(current_hash: str, last_known_hash: Optional[str]) -> bool:
        """Returns True if the current response hash matches the last known hash."""
        if not last_known_hash:
            return False
        return current_hash.lower() == last_known_hash.lower()
