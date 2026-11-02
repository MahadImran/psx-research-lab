"""
Durable Market Data Archival Engine.
Persists immutable compressed responses (.json.gz) and integrity manifests
into the private GitHub archive repository (MahadImran/psx-research-data).
"""

from datetime import datetime, timezone
import base64
import gzip
import hashlib
import json
import logging
import os
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class ArchiveCommitError(Exception):
    pass


class DurableArchiveManager:
    def __init__(
        self,
        repo_name: str = "MahadImran/psx-research-data",
        token: Optional[str] = None,
        local_archive_dir: Optional[str] = None,
    ):
        self.repo_name = repo_name
        self.token = token or os.environ.get("DATA_REPO_TOKEN")
        self.local_archive_dir = local_archive_dir or os.path.expanduser("~/.psx_local_archive")

    @staticmethod
    def compute_sha256(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "PSXResearchLabCollector/1.0",
        }

    def stage_locally(
        self,
        source: str,
        endpoint: str,
        trading_date: str,
        data: Any
    ) -> Tuple[str, bytes, str, int]:
        """
        Gzips payload and prepares relative path:
        raw/YYYY/MM/DD/{source}_{endpoint}_{timestamp}_{hash8}.json.gz
        Returns: (relative_path, compressed_bytes, sha256_hash, uncompressed_bytes_count)
        """
        raw_json = json.dumps(data, indent=2, sort_keys=True, default=str).encode("utf-8")
        sha256_hash = self.compute_sha256(raw_json)
        compressed = gzip.compress(raw_json, compresslevel=9)

        parts = trading_date.split("-")
        year, month, day = (parts[0], parts[1], parts[2]) if len(parts) == 3 else ("2026", "11", "02")
        timestamp_slug = datetime.now(timezone.utc).strftime("%H%M%SZ")
        safe_endpoint = endpoint.replace("/", "_")
        filename = f"{source}_{safe_endpoint}_{timestamp_slug}_{sha256_hash[:8]}.json.gz"
        rel_path = f"raw/{year}/{month}/{day}/{filename}"

        # Write to local staging if local dir enabled
        full_local = os.path.join(self.local_archive_dir, rel_path)
        os.makedirs(os.path.dirname(full_local), exist_ok=True)
        with open(full_local, "wb") as f:
            f.write(compressed)

        return rel_path, compressed, sha256_hash, len(raw_json)

    def commit_file_to_archive(self, rel_path: str, content_bytes: bytes, commit_message: str) -> bool:
        """Commits file to the private GitHub repository via GitHub REST API."""
        if not self.token:
            logger.info("DATA_REPO_TOKEN not present; file persisted to local staging: %s", rel_path)
            return True

        url = f"https://api.github.com/repos/{self.repo_name}/contents/{rel_path}"
        payload = {
            "message": commit_message,
            "content": base64.b64encode(content_bytes).decode("utf-8"),
        }

        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={**self._get_headers(), "Content-Type": "application/json"},
                method="PUT",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.status in (200, 201):
                    logger.info("Successfully persisted to archive repo: %s", rel_path)
                    return True
                raise ArchiveCommitError(f"GitHub returned HTTP {resp.status} for {rel_path}")
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            logger.error("Failed to commit %s to archive: %s %s", rel_path, e.code, err_body)
            raise ArchiveCommitError(f"Archive commit failed (HTTP {e.code}): {err_body}")

    def commit_daily_manifest(
        self,
        trading_date: str,
        manifest_data: Dict[str, Any]
    ) -> str:
        """Commits the daily SHA-256 integrity manifest to manifests/{trading_date}.json."""
        manifest_bytes = json.dumps(manifest_data, indent=2, sort_keys=True).encode("utf-8")
        rel_path = f"manifests/{trading_date}.json"

        # Local save
        full_local = os.path.join(self.local_archive_dir, rel_path)
        os.makedirs(os.path.dirname(full_local), exist_ok=True)
        with open(full_local, "wb") as f:
            f.write(manifest_bytes)

        if self.token:
            self.commit_file_to_archive(
                rel_path=rel_path,
                content_bytes=manifest_bytes,
                commit_message=f"chore(manifest): daily integrity manifest for {trading_date}",
            )
        return rel_path
