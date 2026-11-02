"""
Persistent Cross-Runner Budget and Lease Coordinator.
Coordinates single-collector leases and enforces the 250 req/24h rolling budget
across ephemeral GitHub Actions runners using the private archive repository.
"""

from datetime import datetime, timezone, timedelta
import json
import logging
import os
import uuid
import urllib.request
import base64
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class BudgetExceededError(Exception):
    pass


class LeaseConflictError(Exception):
    pass


class PersistentCoordinator:
    def __init__(
        self,
        repo_name: str = "MahadImran/psx-research-data",
        token: Optional[str] = None,
        daily_limit: int = 250,
        lease_ttl_seconds: int = 300,
        local_state_file: Optional[str] = None,
    ):
        self.repo_name = repo_name
        self.token = token or os.environ.get("DATA_REPO_TOKEN")
        self.daily_limit = daily_limit
        self.lease_ttl_seconds = lease_ttl_seconds
        self.local_state_file = local_state_file or os.path.expanduser("~/.psx_persistent_state.json")
        self.runner_id = f"gha-{os.environ.get('GITHUB_RUN_ID', uuid.uuid4().hex[:8])}"
        self._file_sha: Optional[str] = None
        self.history: List[Dict[str, str]] = []
        self.active_lease: Optional[Dict[str, str]] = None
        self.cooldown_until: Optional[str] = None

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "PSXResearchLabCollector/1.0",
        }

    def load_remote_state(self) -> Dict:
        """Fetch persistent state from private data repo or local fallback."""
        if not self.token:
            return self._load_local_state()

        url = f"https://api.github.com/repos/{self.repo_name}/contents/state/budget_and_lease.json"
        try:
            req = urllib.request.Request(url, headers=self._get_headers())
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                self._file_sha = data.get("sha")
                content = base64.b64decode(data.get("content", "")).decode("utf-8")
                return json.loads(content)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                # File doesn't exist yet in archive repo
                self._file_sha = None
                return {"history": [], "lease": None, "cooldown_until": None}
            logger.warning("Failed to fetch remote state (%s), falling back to local", e)
            return self._load_local_state()
        except Exception as e:
            logger.warning("Remote state fetch exception: %s", e)
            return self._load_local_state()

    def save_remote_state(self, state: Dict) -> bool:
        """Commit updated state to private data repo or local fallback."""
        if not self.token:
            return self._save_local_state(state)

        url = f"https://api.github.com/repos/{self.repo_name}/contents/state/budget_and_lease.json"
        content_bytes = json.dumps(state, indent=2).encode("utf-8")
        payload = {
            "message": f"chore(state): update budget & lease [{self.runner_id}]",
            "content": base64.b64encode(content_bytes).decode("utf-8"),
        }
        if self._file_sha:
            payload["sha"] = self._file_sha

        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={**self._get_headers(), "Content-Type": "application/json"},
                method="PUT",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                self._file_sha = data.get("content", {}).get("sha")
                return True
        except Exception as e:
            logger.warning("Failed to commit remote state: %s. Using local state.", e)
            return self._save_local_state(state)

    def _load_local_state(self) -> Dict:
        if os.path.exists(self.local_state_file):
            try:
                with open(self.local_state_file, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"history": [], "lease": None, "cooldown_until": None}

    def _save_local_state(self, state: Dict) -> bool:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.local_state_file)), exist_ok=True)
            with open(self.local_state_file, "w") as f:
                json.dump(state, f, indent=2)
            return True
        except Exception:
            return False

    def acquire_lease_and_sync(self) -> None:
        """Acquires single-collector lease and loads 24h request history."""
        state = self.load_remote_state()
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()

        # Check existing lease
        lease = state.get("lease")
        if lease:
            expires_at = datetime.fromisoformat(lease["expires_at"])
            owner = lease.get("owner")
            if now < expires_at and owner != self.runner_id:
                raise LeaseConflictError(
                    f"Collector lease currently held by {owner} until {lease['expires_at']}."
                )

        # Acquire new lease
        lease_expires = (now + timedelta(seconds=self.lease_ttl_seconds)).isoformat()
        self.active_lease = {
            "owner": self.runner_id,
            "acquired_at": now_iso,
            "expires_at": lease_expires,
        }
        state["lease"] = self.active_lease

        # Purge requests older than 24h
        cutoff = (now - timedelta(hours=24)).isoformat()
        self.history = [r for r in state.get("history", []) if r["timestamp"] >= cutoff]
        state["history"] = self.history

        self.save_remote_state(state)

    def release_lease(self) -> None:
        """Releases the collector lease on clean termination."""
        state = self.load_remote_state()
        if state.get("lease", {}).get("owner") == self.runner_id:
            state["lease"] = None
        state["history"] = self.history
        self.save_remote_state(state)
        self.active_lease = None

    def get_remaining_requests(self) -> int:
        now = datetime.now(timezone.utc)
        cutoff = (now - timedelta(hours=24)).isoformat()
        active = [r for r in self.history if r["timestamp"] >= cutoff]
        return max(0, self.daily_limit - len(active))

    def record_request(self, endpoint: str) -> None:
        """Enforces the 250 req/24h limit. Raises BudgetExceededError if limit met."""
        now = datetime.now(timezone.utc)
        cutoff = (now - timedelta(hours=24)).isoformat()
        self.history = [r for r in self.history if r["timestamp"] >= cutoff]

        if len(self.history) >= self.daily_limit:
            raise BudgetExceededError(
                f"Rolling 24h upstream budget limit ({self.daily_limit}) reached! Cannot request {endpoint}."
            )

        self.history.append({
            "timestamp": now.isoformat(),
            "endpoint": endpoint,
            "runner_id": self.runner_id,
        })
