"""
Durable Market Data Archival Engine.
Persists immutable compressed responses (.json.gz) and integrity manifests
into the private GitHub archive repository (MahadImran/psx-research-data).
Includes automatic readback verification and idempotent recovery.
Fails closed: never accepts ephemeral local storage as proof of durable archive in CI/production.
"""

from datetime import datetime, timezone
import base64
import gzip
import hashlib
import json
import logging
import os
import time
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class ArchiveCommitError(Exception):
    """Raised when committing to or verifying from remote archive fails."""
    pass


class ArchiveCredentialsError(Exception):
    """Raised when DATA_REPO_TOKEN is missing in a production/CI environment."""
    pass


class DurableArchiveManager:
    def __init__(
        self,
        repo_name: str = "MahadImran/psx-research-data",
        token: Optional[str] = None,
        local_archive_dir: Optional[str] = None,
        require_remote: Optional[bool] = None,
    ):
        self.repo_name = repo_name
        self.token = token or os.environ.get("DATA_REPO_TOKEN")
        self.local_archive_dir = local_archive_dir or os.path.expanduser("~/.psx_local_archive")
        self.require_remote = (
            require_remote
            if require_remote is not None
            else bool(os.environ.get("GITHUB_ACTIONS") or os.environ.get("CI") or os.environ.get("REQUIRE_REMOTE_ARCHIVE"))
        )

    @staticmethod
    def compute_sha256(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def _get_headers(self) -> Dict[str, str]:
        if not self.token:
            raise ArchiveCredentialsError("DATA_REPO_TOKEN is required to communicate with archive repository.")
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

        # Write to local staging
        full_local = os.path.join(self.local_archive_dir, rel_path)
        os.makedirs(os.path.dirname(full_local), exist_ok=True)
        with open(full_local, "wb") as f:
            f.write(compressed)

        return rel_path, compressed, sha256_hash, len(raw_json)

    def read_remote_file(
        self,
        rel_path: str,
        retries: int = 0,
        retry_delay: float = 0.5,
    ) -> Tuple[Optional[bytes], Optional[str]]:
        """
        Reads a file back from the archive repository.
        Returns: (content_bytes, file_sha) or (None, None) if not found.
        Supports bounded retries to accommodate GitHub API edge replica propagation delay.
        """
        if not self.token:
            if self.require_remote:
                raise ArchiveCredentialsError("DATA_REPO_TOKEN required to read from remote archive.")
            full_local = os.path.join(self.local_archive_dir, rel_path)
            if os.path.exists(full_local):
                with open(full_local, "rb") as f:
                    return f.read(), "local-sha"
            return None, None

        url = f"https://api.github.com/repos/{self.repo_name}/contents/{rel_path}"
        headers = self._get_headers()
        headers["Cache-Control"] = "no-cache"
        headers["Pragma"] = "no-cache"

        for attempt in range(retries + 1):
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    file_sha = data.get("sha")
                    raw_bytes = base64.b64decode(data.get("content", ""))
                    return raw_bytes, file_sha
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    if attempt < retries:
                        time.sleep(retry_delay * (attempt + 1))
                        continue
                    return None, None
                raise ArchiveCommitError(f"Error reading back {rel_path} from archive (HTTP {e.code})")
            except Exception as e:
                if attempt < retries:
                    time.sleep(retry_delay)
                    continue
                raise ArchiveCommitError(f"Network error reading back {rel_path}: {e}")
        return None, None

    def commit_file_to_archive(self, rel_path: str, content_bytes: bytes, commit_message: str) -> bool:
        """
        Commits file to the private GitHub repository and verifies bit-for-bit readback integrity.
        Handles idempotent updates if the file already exists.
        Fails closed in CI/production if credentials are missing or commit/readback fails.
        """
        if not self.token:
            if self.require_remote:
                raise ArchiveCredentialsError(
                    f"DATA_REPO_TOKEN required in CI/production! Cannot commit {rel_path} to ephemeral storage only."
                )
            logger.info("Local dev mode: staged %s locally without remote push", rel_path)
            return True

        # Check existing remote file for idempotency
        existing_bytes, existing_sha = self.read_remote_file(rel_path)
        if existing_bytes is not None:
            if existing_bytes == content_bytes:
                logger.info("File already durably archived with identical content: %s", rel_path)
                return True
            # Enforce immutability for raw archive objects
            if rel_path.startswith("raw/"):
                raise ArchiveCommitError(
                    f"Immutability violation: raw archive object {rel_path} already exists with differing content "
                    f"({len(existing_bytes)} bytes existing vs {len(content_bytes)} bytes incoming). "
                    f"Raw archive objects are strictly immutable and cannot be overwritten."
                )
            logger.info("File exists with different content; updating: %s", rel_path)

        url = f"https://api.github.com/repos/{self.repo_name}/contents/{rel_path}"
        payload = {
            "message": commit_message,
            "content": base64.b64encode(content_bytes).decode("utf-8"),
        }
        if existing_sha:
            payload["sha"] = existing_sha

        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={**self._get_headers(), "Content-Type": "application/json"},
                method="PUT",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.status not in (200, 201):
                    raise ArchiveCommitError(f"GitHub returned HTTP {resp.status} for {rel_path}")
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            logger.error("Failed to commit %s to archive: HTTP %s %s", rel_path, e.code, err_body)
            raise ArchiveCommitError(f"Archive commit failed for {rel_path} (HTTP {e.code}): {err_body}")
        except Exception as e:
            logger.error("Network error committing %s to archive: %s", rel_path, e)
            raise ArchiveCommitError(f"Network error committing {rel_path}: {e}")

        # READBACK VERIFICATION (with retries for API edge propagation)
        readback_bytes, _ = self.read_remote_file(rel_path, retries=3, retry_delay=0.75)
        if readback_bytes is None:
            raise ArchiveCommitError(f"Readback verification failed: file {rel_path} not found after commit!")
        if readback_bytes != content_bytes:
            raise ArchiveCommitError(
                f"Readback verification hash mismatch for {rel_path}! (size committed: {len(content_bytes)}, size read: {len(readback_bytes)})"
            )

        logger.info("Durable archive committed and verified: %s (%d bytes)", rel_path, len(content_bytes))
        return True

    def commit_daily_manifest(
        self,
        trading_date: str,
        manifest_data: Dict[str, Any]
    ) -> str:
        """
        Commits daily SHA-256 integrity manifest to manifests/{trading_date}.json
        with readback verification.
        Preserves data durability: reads any existing manifest for this trading date and
        accumulates verifiedArchiveFiles and cycles without erasing earlier collections.
        """
        rel_path = f"manifests/{trading_date}.json"
        new_files = manifest_data.get("verifiedArchiveFiles", [])
        new_cycle = {
            "generatedAtUtc": manifest_data.get("generatedAtUtc"),
            "source": manifest_data.get("source"),
            "files": new_files,
            "totalBars": manifest_data.get("totalBars", 0),
            "totalSnapshots": manifest_data.get("totalSnapshots", 0),
            "totalIndices": manifest_data.get("totalIndices", 0),
            "payloadSha256": manifest_data.get("payloadSha256"),
        }

        # Read existing manifest if present to accumulate references across runs
        existing_bytes, _ = self.read_remote_file(rel_path, retries=1)
        if existing_bytes:
            try:
                existing_manifest = json.loads(existing_bytes.decode("utf-8"))
                if not isinstance(existing_manifest, dict):
                    raise ValueError("Existing manifest content is not a valid JSON dictionary")
                # Merge verified files
                existing_files = existing_manifest.get("verifiedArchiveFiles", [])
                if not isinstance(existing_files, list):
                    raise ValueError("Existing manifest has invalid verifiedArchiveFiles structure")
                manifest_data["verifiedArchiveFiles"] = sorted(list(set(existing_files + new_files)))
                # Preserve run cycle history
                existing_cycles = existing_manifest.get("cycles", [])
                if not isinstance(existing_cycles, list):
                    existing_cycles = []
                manifest_data["cycles"] = existing_cycles + [new_cycle]
            except Exception as e:
                # Corrupt manifest must FAIL CLOSED and preserve corrupted data
                corrupt_backup = f"manifests/corrupted_{trading_date}_{int(time.time())}.json"
                logger.error(
                    "Existing manifest %s is corrupt or unreadable: %s. Preserving corrupted state to %s and failing closed.",
                    rel_path,
                    e,
                    corrupt_backup,
                )
                try:
                    full_corrupt_local = os.path.join(self.local_archive_dir, corrupt_backup)
                    os.makedirs(os.path.dirname(full_corrupt_local), exist_ok=True)
                    with open(full_corrupt_local, "wb") as f:
                        f.write(existing_bytes)
                except Exception as backup_err:
                    logger.error("Failed to write local backup of corrupted manifest: %s", backup_err)

                if self.token or self.require_remote:
                    try:
                        self.commit_file_to_archive(
                            rel_path=corrupt_backup,
                            content_bytes=existing_bytes,
                            commit_message=f"alert(manifest): preserve corrupted manifest for {trading_date}",
                        )
                    except Exception as remote_backup_err:
                        logger.error("Failed to write remote backup of corrupted manifest: %s", remote_backup_err)

                raise ArchiveCommitError(
                    f"Corrupt or unreadable existing manifest at {rel_path}: {e}. "
                    f"Commit aborted to protect historical records from being discarded."
                )
        else:
            # First collection cycle for this trading date: ensure represented in cycles ledger
            manifest_data["verifiedArchiveFiles"] = sorted(list(set(new_files)))
            manifest_data["cycles"] = [new_cycle]

        manifest_bytes = json.dumps(manifest_data, indent=2, sort_keys=True).encode("utf-8")

        # Local save
        full_local = os.path.join(self.local_archive_dir, rel_path)
        os.makedirs(os.path.dirname(full_local), exist_ok=True)
        with open(full_local, "wb") as f:
            f.write(manifest_bytes)

        if self.token or self.require_remote:
            self.commit_file_to_archive(
                rel_path=rel_path,
                content_bytes=manifest_bytes,
                commit_message=f"chore(manifest): daily integrity manifest for {trading_date}",
            )

        return rel_path
