"""
Persistent Cross-Runner Budget and Lease Coordinator.
Coordinates single-collector leases and enforces the 250 req/24h rolling budget
across ephemeral GitHub Actions runners using the private archive repository.
Fails closed in production/CI: never silently falls back to local storage when remote state fails.
"""

from datetime import datetime, timezone, timedelta
import json
import logging
import os
import time
import uuid
import urllib.request
import urllib.error
import base64
from typing import Any, Dict, List, Optional, Tuple

from .cooldown import CircuitBreakerTrippedError

logger = logging.getLogger(__name__)


class BudgetExceededError(Exception):
    """Raised when upstream rolling 24h request limit is met or exceeded."""
    pass


class LeaseConflictError(Exception):
    """Raised when another runner actively holds the collector lease or on commit conflict."""
    pass


class RemoteStateError(Exception):
    """Raised when remote state cannot be verified, fetched, or committed (fail closed)."""
    pass


class PersistentCoordinator:
    def __init__(
        self,
        repo_name: str = "MahadImran/psx-research-data",
        token: Optional[str] = None,
        daily_limit: int = 250,
        lease_ttl_seconds: int = 300,
        local_state_file: Optional[str] = None,
        require_remote: Optional[bool] = None,
    ):
        self.repo_name = repo_name
        self.token = token or os.environ.get("DATA_REPO_TOKEN")
        self.daily_limit = daily_limit
        self.lease_ttl_seconds = lease_ttl_seconds
        self.local_state_file = local_state_file or os.path.expanduser("~/.psx_persistent_state.json")
        self.require_remote = (
            require_remote
            if require_remote is not None
            else bool(os.environ.get("GITHUB_ACTIONS") or os.environ.get("CI") or os.environ.get("REQUIRE_REMOTE_STATE"))
        )
        self.runner_id = f"gha-{os.environ.get('GITHUB_RUN_ID', uuid.uuid4().hex[:8])}"
        self._file_sha: Optional[str] = None
        self.history: List[Dict[str, str]] = []
        self.active_lease: Optional[Dict[str, Any]] = None
        self.remote_lease: Optional[Dict[str, Any]] = None
        self.snapshot_hashes: Dict[str, str] = {}
        self.cooldown_until: Optional[str] = None

    def _get_headers(self) -> Dict[str, str]:
        if not self.token:
            raise RemoteStateError("DATA_REPO_TOKEN is required to communicate with remote repository.")
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "PSXResearchLabCollector/1.0",
        }

    def verify_repo_access(self) -> bool:
        """Confirms that the repository exists and our token has access."""
        url = f"https://api.github.com/repos/{self.repo_name}"
        try:
            req = urllib.request.Request(url, headers=self._get_headers())
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status == 200
        except urllib.error.HTTPError as e:
            logger.error("Repository %s access check failed (HTTP %d)", self.repo_name, e.code)
            raise RemoteStateError(f"Remote repository {self.repo_name} inaccessible: HTTP {e.code}")
        except Exception as e:
            logger.error("Repository %s network access error: %s", self.repo_name, e)
            raise RemoteStateError(f"Failed to connect to GitHub API for {self.repo_name}: {e}")

    def load_remote_state(self) -> Dict[str, Any]:
        """
        Fetch persistent state from private data repo.
        Fails closed if remote state cannot be verified in CI/production.
        """
        if not self.token:
            if self.require_remote:
                raise RemoteStateError("Production environment requires DATA_REPO_TOKEN for persistent coordination.")
            logger.info("Local dev mode: using local state file %s", self.local_state_file)
            return self._load_local_state()

        url = f"https://api.github.com/repos/{self.repo_name}/contents/state/budget_and_lease.json"
        try:
            req = urllib.request.Request(url, headers=self._get_headers())
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                self._file_sha = data.get("sha")
                content = base64.b64decode(data.get("content", "")).decode("utf-8")
                parsed = json.loads(content)
                self.history = parsed.get("history", [])
                self.snapshot_hashes = parsed.get("snapshot_hashes", {})
                self.remote_lease = parsed.get("lease")
                self.cooldown_until = parsed.get("cooldown_until")

                # Authoritative revalidation: NEVER set active_lease to another runner's lease
                now = datetime.now(timezone.utc)
                if self.remote_lease and self.remote_lease.get("owner") == self.runner_id:
                    try:
                        expires_at = datetime.fromisoformat(self.remote_lease["expires_at"])
                        if now < expires_at:
                            self.active_lease = self.remote_lease
                        else:
                            self.active_lease = None
                    except Exception:
                        self.active_lease = None
                else:
                    self.active_lease = None
                return parsed
        except urllib.error.HTTPError as e:
            if e.code == 404:
                # Do NOT blindly accept 404 without verifying repository access first
                self.verify_repo_access()
                # Repository exists, but state file not yet initialized
                logger.info("Repository exists; initializing fresh state/budget_and_lease.json")
                self._file_sha = None
                return {"history": [], "lease": None, "cooldown_until": None}
            if self.require_remote:
                raise RemoteStateError(f"Remote state read failed with HTTP {e.code}: {e.read().decode('utf-8', errors='ignore')}")
            logger.warning("Failed to fetch remote state (HTTP %s), falling back to local for dev", e.code)
            return self._load_local_state()
        except Exception as e:
            if self.require_remote:
                raise RemoteStateError(f"Remote state connection failed: {e}")
            logger.warning("Remote state fetch exception (%s), falling back to local for dev", e)
            return self._load_local_state()

    def save_remote_state(self, state: Dict[str, Any], max_retries: int = 3) -> bool:
        """
        Commit updated state to private data repo using optimistic concurrency.
        Fails closed in CI/production. Retries on HTTP 409 (Git commit conflict).
        """
        if not self.token:
            if self.require_remote:
                raise RemoteStateError("Production environment requires DATA_REPO_TOKEN to persist state.")
            return self._save_local_state(state)

        url = f"https://api.github.com/repos/{self.repo_name}/contents/state/budget_and_lease.json"

        for attempt in range(max_retries):
            content_bytes = json.dumps(state, indent=2).encode("utf-8")
            payload = {
                "message": f"chore(state): update budget & lease [{self.runner_id}] (attempt {attempt+1})",
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
                    resp_data = json.loads(resp.read().decode("utf-8"))
                    self._file_sha = resp_data.get("content", {}).get("sha")
                    self.history = state.get("history", [])
                    self.active_lease = state.get("lease")
                    self.cooldown_until = state.get("cooldown_until")
                    return True
            except urllib.error.HTTPError as e:
                err_body = e.read().decode("utf-8", errors="ignore")
                if e.code == 409 and attempt < max_retries - 1:
                    logger.warning("Concurrent commit conflict (HTTP 409). Reloading fresh state (attempt %d)...", attempt + 1)
                    time.sleep(0.5 * (2 ** attempt))
                    fresh_state = self.load_remote_state()
                    # Re-check lease validity against fresh authoritative state
                    existing_lease = fresh_state.get("lease")
                    now = datetime.now(timezone.utc)
                    if existing_lease and state.get("lease"):
                        expires_at = datetime.fromisoformat(existing_lease["expires_at"])
                        if now < expires_at and existing_lease.get("owner") != self.runner_id:
                            raise LeaseConflictError(f"Lease acquired by competitor {existing_lease.get('owner')} during commit conflict.")

                    # Merge history keyed by unique tuple
                    all_history_map = {
                        (h.get("timestamp", ""), h.get("endpoint", ""), h.get("runner_id", "")): h
                        for h in fresh_state.get("history", []) + state.get("history", [])
                    }
                    cutoff = (now - timedelta(hours=24)).isoformat()
                    merged_history = [h for h in all_history_map.values() if h.get("timestamp", "") >= cutoff]
                    merged_history.sort(key=lambda x: x.get("timestamp", ""))

                    # RECHECK the 250-request limit after merging concurrent state changes!
                    if len(merged_history) > self.daily_limit:
                        raise BudgetExceededError(
                            f"Rolling 24h budget limit ({self.daily_limit}) exceeded after merging concurrent runner requests "
                            f"({len(merged_history)} requests recorded)!"
                        )

                    # Merge snapshot hashes
                    merged_hashes = {**fresh_state.get("snapshot_hashes", {}), **state.get("snapshot_hashes", {})}
                    state["snapshot_hashes"] = merged_hashes
                    self.snapshot_hashes = merged_hashes

                    state["history"] = merged_history
                    continue

                if self.require_remote:
                    raise RemoteStateError(f"Failed to commit remote state (HTTP {e.code}): {err_body}")
                logger.warning("Failed to commit remote state: HTTP %d %s", e.code, err_body)
                return self._save_local_state(state)
            except (LeaseConflictError, BudgetExceededError):
                raise
            except Exception as e:
                if self.require_remote:
                    raise RemoteStateError(f"Remote state commit network exception: {e}")
                logger.warning("Remote state commit error: %s", e)
                return self._save_local_state(state)

        raise RemoteStateError(f"Failed to commit remote state after {max_retries} attempts.")

    def _load_local_state(self) -> Dict[str, Any]:
        if os.path.exists(self.local_state_file):
            try:
                with open(self.local_state_file, "r") as f:
                    data = json.load(f)
                    self.history = data.get("history", [])
                    self.snapshot_hashes = data.get("snapshot_hashes", {})
                    self.remote_lease = data.get("lease")
                    self.cooldown_until = data.get("cooldown_until")
                    now = datetime.now(timezone.utc)
                    if self.remote_lease and self.remote_lease.get("owner") == self.runner_id:
                        try:
                            if now < datetime.fromisoformat(self.remote_lease["expires_at"]):
                                self.active_lease = self.remote_lease
                            else:
                                self.active_lease = None
                        except Exception:
                            self.active_lease = None
                    else:
                        self.active_lease = None
                    return data
            except Exception as e:
                logger.warning("Error reading local state: %s", e)
        return {"history": [], "lease": None, "cooldown_until": None, "snapshot_hashes": {}}

    def _save_local_state(self, state: Dict[str, Any]) -> bool:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.local_state_file)), exist_ok=True)
            state["snapshot_hashes"] = self.snapshot_hashes
            with open(self.local_state_file, "w") as f:
                json.dump(state, f, indent=2)
            self.history = state.get("history", [])
            self.remote_lease = state.get("lease")
            self.cooldown_until = state.get("cooldown_until")
            now = datetime.now(timezone.utc)
            if self.remote_lease and self.remote_lease.get("owner") == self.runner_id:
                try:
                    if now < datetime.fromisoformat(self.remote_lease["expires_at"]):
                        self.active_lease = self.remote_lease
                    else:
                        self.active_lease = None
                except Exception:
                    self.active_lease = None
            else:
                self.active_lease = None
            return True
        except Exception as e:
            logger.error("Failed to write local state: %s", e)
            return False

    def get_last_snapshot_hash(self, source: str, trading_date: str) -> Optional[str]:
        """Returns the last known snapshot SHA-256 for a given source and trading date."""
        key = f"{source}:{trading_date}"
        return self.snapshot_hashes.get(key)

    def record_snapshot_hash(self, source: str, trading_date: str, sha256_hash: str) -> None:
        """Durably records the snapshot SHA-256 for a given source and trading date."""
        key = f"{source}:{trading_date}"
        self.snapshot_hashes[key] = sha256_hash
        if self.token or self.require_remote:
            state = self.load_remote_state()
            if "snapshot_hashes" not in state:
                state["snapshot_hashes"] = {}
            state["snapshot_hashes"][key] = sha256_hash
            self.save_remote_state(state)
        else:
            state = self._load_local_state()
            if "snapshot_hashes" not in state:
                state["snapshot_hashes"] = {}
            state["snapshot_hashes"][key] = sha256_hash
            self._save_local_state(state)

    def is_lease_active(self) -> bool:
        """Checks if this runner holds a valid, unexpired lease."""
        if not self.active_lease:
            return False
        if self.active_lease.get("owner") != self.runner_id:
            return False
        try:
            now = datetime.now(timezone.utc)
            expires_at = datetime.fromisoformat(self.active_lease["expires_at"])
            return now < expires_at
        except Exception:
            return False

    def renew_lease(self, extension_seconds: int = 300) -> None:
        """Extends lease expiration for active long-running collector jobs."""
        state = self.load_remote_state()
        current_lease = state.get("lease")
        if not current_lease or current_lease.get("owner") != self.runner_id:
            raise LeaseConflictError(f"Cannot renew lease: lease not held by {self.runner_id}")
        now = datetime.now(timezone.utc)
        expires_at = datetime.fromisoformat(current_lease["expires_at"])
        if now >= expires_at:
            raise LeaseConflictError(f"Cannot renew expired lease: expired at {current_lease['expires_at']}")
        new_expiry = (now + timedelta(seconds=extension_seconds)).isoformat()
        current_lease["expires_at"] = new_expiry
        state["lease"] = current_lease
        self.save_remote_state(state)
        self.active_lease = current_lease
        logger.info("Lease renewed for runner %s until %s", self.runner_id, new_expiry)

    def acquire_lease_and_sync(self) -> None:
        """
        Acquires single-collector lease, commits it remotely, and purges expired requests.
        Fails closed: if remote state cannot be verified and committed, throws exception.
        """
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
        new_lease = {
            "owner": self.runner_id,
            "acquired_at": now_iso,
            "expires_at": lease_expires,
        }
        state["lease"] = new_lease

        # Purge requests older than 24h
        cutoff = (now - timedelta(hours=24)).isoformat()
        self.history = [r for r in state.get("history", []) if r.get("timestamp", "") >= cutoff]
        state["history"] = self.history

        # Commit remotely and verify
        success = self.save_remote_state(state)
        if not success:
            raise RemoteStateError("Lease acquisition failed: unable to commit lease to remote repository.")
        self.active_lease = new_lease
        logger.info("Lease acquired successfully for runner %s until %s", self.runner_id, lease_expires)

    def release_lease(self) -> None:
        """Releases the collector lease and syncs merged history without overwriting competing runner state."""
        try:
            state = self.load_remote_state()
            current_lease = state.get("lease")
            if current_lease and current_lease.get("owner") == self.runner_id:
                state["lease"] = None
            else:
                logger.warning(
                    "Lease was no longer held by %s upon release (current owner: %s)",
                    self.runner_id,
                    current_lease.get("owner") if current_lease else "None",
                )

            # Merge history across runners (keyed by timestamp + endpoint + runner_id)
            existing_entries = {
                (h.get("timestamp", ""), h.get("endpoint", ""), h.get("runner_id", "")): h
                for h in state.get("history", [])
            }
            for h in self.history:
                key = (h.get("timestamp", ""), h.get("endpoint", ""), h.get("runner_id", ""))
                existing_entries[key] = h

            now = datetime.now(timezone.utc)
            cutoff = (now - timedelta(hours=24)).isoformat()
            merged_history = [
                h for h in existing_entries.values()
                if h.get("timestamp", "") >= cutoff
            ]
            merged_history.sort(key=lambda x: x.get("timestamp", ""))
            state["history"] = merged_history

            self.save_remote_state(state)
            self.history = merged_history
            self.active_lease = None
            logger.info("Lease cleanly released and history merged for runner %s", self.runner_id)
        except Exception as e:
            logger.warning("Error releasing lease: %s", e)
            self.active_lease = None

    def get_remaining_requests(self) -> int:
        now = datetime.now(timezone.utc)
        cutoff = (now - timedelta(hours=24)).isoformat()
        active = [r for r in self.history if r.get("timestamp", "") >= cutoff]
        return max(0, self.daily_limit - len(active))

    def is_in_cooldown(self) -> bool:
        """Checks if remote or local state records an active circuit breaker cooldown."""
        if not self.cooldown_until:
            try:
                state = self.load_remote_state() if (self.require_remote or self.token) else self._load_local_state()
                self.cooldown_until = state.get("cooldown_until")
            except Exception:
                pass
        if not self.cooldown_until:
            return False
        try:
            now = datetime.now(timezone.utc)
            return now < datetime.fromisoformat(self.cooldown_until)
        except Exception:
            return False

    def get_remaining_cooldown_seconds(self) -> float:
        """Returns seconds remaining in active cooldown, or 0.0 if expired."""
        if not self.is_in_cooldown() or not self.cooldown_until:
            return 0.0
        try:
            now = datetime.now(timezone.utc)
            return max(0.0, (datetime.fromisoformat(self.cooldown_until) - now).total_seconds())
        except Exception:
            return 0.0

    def record_cooldown(self, cooldown_seconds: int, reason: Optional[str] = None) -> None:
        """Persists cross-runner cooldown in remote state."""
        now = datetime.now(timezone.utc)
        cooldown_dt = now + timedelta(seconds=max(1, cooldown_seconds))
        self.cooldown_until = cooldown_dt.isoformat()
        logger.warning(
            "Upstream source entered cooldown until %s (duration %ds, reason: %s)",
            self.cooldown_until,
            cooldown_seconds,
            reason,
        )
        state = self.load_remote_state() if (self.require_remote or self.token) else self._load_local_state()
        state["cooldown_until"] = self.cooldown_until
        state["history"] = self.history
        state["lease"] = self.active_lease
        state["snapshot_hashes"] = self.snapshot_hashes
        if self.require_remote or self.token:
            self.save_remote_state(state)
        else:
            self._save_local_state(state)

    def reserve_request(self, endpoint: str) -> None:
        """
        Durably reserves an upstream request quota BEFORE the network socket request is made.
        Fails closed: if remote persistence cannot be committed, raises RemoteStateError or
        BudgetExceededError or LeaseConflictError or CircuitBreakerTrippedError, and the upstream request must NOT proceed.
        """
        now = datetime.now(timezone.utc)
        cutoff = (now - timedelta(hours=24)).isoformat()

        # 0. Check circuit breaker cooldown
        if self.is_in_cooldown():
            rem = self.get_remaining_cooldown_seconds()
            raise CircuitBreakerTrippedError(
                f"Source circuit breaker is active in persistent state! Cooldown remaining: {rem:.1f}s until {self.cooldown_until}. "
                f"Cannot issue upstream request for {endpoint}."
            )

        # 1. Authoritative lease verification from remote/authoritative state
        state = self.load_remote_state() if (self.require_remote or self.token) else self._load_local_state()
        current_lease = state.get("lease")
        if not current_lease or current_lease.get("owner") != self.runner_id:
            self.active_lease = None
            raise LeaseConflictError(
                f"Runner {self.runner_id} lost or does not hold lease ownership "
                f"(current: {current_lease.get('owner') if current_lease else 'None'}). "
                f"Cannot issue upstream request for {endpoint}."
            )
        if now >= datetime.fromisoformat(current_lease["expires_at"]):
            self.active_lease = None
            raise LeaseConflictError(
                f"Runner {self.runner_id} lease expired at {current_lease['expires_at']}. "
                f"Cannot issue request for {endpoint}."
            )
        self.active_lease = current_lease

        # 2. Check 24h budget against active history
        active = [r for r in state.get("history", []) if r.get("timestamp", "") >= cutoff]
        if len(active) >= self.daily_limit:
            raise BudgetExceededError(
                f"Rolling 24h upstream budget limit ({self.daily_limit}) reached ({len(active)} used)! "
                f"Pre-reservation rejected for {endpoint}."
            )

        # 3. Append reservation and commit before network socket call
        entry = {
            "timestamp": now.isoformat(),
            "endpoint": endpoint,
            "runner_id": self.runner_id,
            "status": "RESERVED",
        }
        active.append(entry)
        state["history"] = active
        state["snapshot_hashes"] = self.snapshot_hashes

        if self.require_remote or self.token:
            success = self.save_remote_state(state)
            if not success:
                raise RemoteStateError(f"Failed to durably commit request quota reservation for {endpoint}.")
            self.history = active
            logger.debug("Quota reserved and committed remotely for %s (%d/%d used)", endpoint, len(active), self.daily_limit)
        else:
            self._save_local_state(state)
            self.history = active

    def record_request(self, endpoint: str) -> None:
        """
        Records/reserves an upstream request against the rolling 24h budget.
        Enforces durable reservation before outbound network requests.
        """
        self.reserve_request(endpoint)

    def sync_budget_to_remote(self) -> None:
        """Flushes recorded requests to remote state."""
        state = {
            "history": self.history,
            "lease": self.active_lease,
            "cooldown_until": self.cooldown_until,
            "snapshot_hashes": self.snapshot_hashes,
        }
        self.save_remote_state(state)
