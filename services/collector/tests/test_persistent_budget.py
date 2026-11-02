import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta
import base64
import json
import urllib.error
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from collector.persistent_budget import (
    PersistentCoordinator,
    BudgetExceededError,
    LeaseConflictError,
    RemoteStateError,
)


def test_persistent_coordinator_lease_lifecycle(tmp_path):
    state_file = str(tmp_path / "budget_state.json")
    coord1 = PersistentCoordinator(token=None, local_state_file=state_file, lease_ttl_seconds=10, require_remote=False)
    coord1.runner_id = "runner-1"

    # 1. Acquire lease
    coord1.acquire_lease_and_sync()
    assert coord1.active_lease is not None
    assert coord1.active_lease["owner"] == "runner-1"

    # 2. Competing runner cannot acquire while lease is active
    coord2 = PersistentCoordinator(token=None, local_state_file=state_file, lease_ttl_seconds=10, require_remote=False)
    coord2.runner_id = "runner-2"
    with pytest.raises(LeaseConflictError):
        coord2.acquire_lease_and_sync()

    # 3. Release lease
    coord1.release_lease()
    assert coord1.active_lease is None

    # 4. Runner 2 can now acquire lease
    coord2.acquire_lease_and_sync()
    assert coord2.active_lease["owner"] == "runner-2"
    coord2.release_lease()


def test_persistent_coordinator_budget_fuse_enforcement(tmp_path):
    state_file = str(tmp_path / "budget_fuse.json")
    coord = PersistentCoordinator(
        token=None,
        local_state_file=state_file,
        daily_limit=5,
        require_remote=False,
    )
    coord.acquire_lease_and_sync()

    assert coord.get_remaining_requests() == 5

    coord.record_request("snapshot")
    coord.record_request("indices")
    coord.record_request("eod/OGDC")
    assert coord.get_remaining_requests() == 2

    coord.record_request("eod/ENGROH")
    coord.record_request("eod/HUBC")
    assert coord.get_remaining_requests() == 0

    # 6th request must trip the budget fuse
    with pytest.raises(BudgetExceededError) as exc_info:
        coord.record_request("eod/SYS")
    assert "limit (5) reached" in str(exc_info.value)

    coord.release_lease()


def test_persistent_coordinator_fails_closed_in_ci_without_token():
    coord = PersistentCoordinator(token=None, require_remote=True)
    with pytest.raises(RemoteStateError) as exc_info:
        coord.load_remote_state()
    assert "DATA_REPO_TOKEN" in str(exc_info.value)


def test_persistent_coordinator_fails_closed_when_repo_inaccessible():
    coord = PersistentCoordinator(token="test-token", repo_name="private/nonexistent", require_remote=True)

    with patch("urllib.request.urlopen") as mock_urlopen:
        # File GET returns 404
        mock_file_err = urllib.error.HTTPError("url", 404, "Not Found", {}, None)
        # Repo GET also returns 404 (repo does not exist or token has no access)
        mock_repo_err = urllib.error.HTTPError("url", 404, "Not Found", {}, None)

        mock_urlopen.side_effect = [mock_file_err, mock_repo_err]

        with pytest.raises(RemoteStateError) as exc_info:
            coord.load_remote_state()
        assert "inaccessible" in str(exc_info.value)


def test_persistent_coordinator_optimistic_concurrency_retry():
    coord = PersistentCoordinator(token="test-token", repo_name="test/repo", require_remote=True)
    coord._file_sha = "sha-old-123"

    initial_state = {"history": [], "lease": None, "cooldown_until": None}
    b64_fresh = base64.b64encode(json.dumps(initial_state).encode("utf-8")).decode("utf-8")

    with patch("urllib.request.urlopen") as mock_urlopen:
        # 1st PUT attempt -> 409 Conflict
        mock_conflict = urllib.error.HTTPError("url", 409, "Conflict", {}, None)

        # Reload GET -> returns fresh state with new SHA
        mock_reload = MagicMock(status=200)
        mock_reload.read.return_value = json.dumps({"sha": "sha-fresh-456", "content": b64_fresh}).encode("utf-8")
        mock_reload.__enter__.return_value = mock_reload

        # 2nd PUT attempt -> 200 OK
        mock_success = MagicMock(status=200)
        mock_success.read.return_value = json.dumps({"content": {"sha": "sha-final-789"}}).encode("utf-8")
        mock_success.__enter__.return_value = mock_success

        mock_urlopen.side_effect = [mock_conflict, mock_reload, mock_success]

        ok = coord.save_remote_state(initial_state, max_retries=2)
        assert ok is True
        assert coord._file_sha == "sha-final-789"


def test_pre_reservation_commits_before_request_and_survives_crash(tmp_path):
    """
    Proves Critical Issue A: Quota reservation is committed durably to storage
    BEFORE any socket request can proceed. If the runner crashes mid-run,
    the reserved request remains recorded and cannot be bypassed.
    """
    state_file = str(tmp_path / "budget_state.json")
    runner1 = PersistentCoordinator(token=None, local_state_file=state_file, daily_limit=3, require_remote=False)
    runner1.runner_id = "runner-crash-1"
    runner1.acquire_lease_and_sync()

    # Pre-reserve request 1
    runner1.reserve_request("snapshot")
    # Simulate abrupt process crash / termination without calling release_lease()!
    del runner1

    # Runner 2 starts later (simulating new runner instance inspecting state)
    runner2 = PersistentCoordinator(token=None, local_state_file=state_file, daily_limit=3, require_remote=False)
    runner2.runner_id = "runner-recovery-2"
    
    # State file must already contain runner 1's reserved request!
    state = runner2._load_local_state()
    assert len(state["history"]) == 1
    assert state["history"][0]["endpoint"] == "snapshot"
    assert state["history"][0]["runner_id"] == "runner-crash-1"

    # Advance time to allow runner 1's lease to expire
    with patch("collector.persistent_budget.datetime") as mock_dt:
        future_time = datetime.now(timezone.utc) + timedelta(seconds=350)
        mock_dt.now.return_value = future_time
        mock_dt.fromisoformat = datetime.fromisoformat

        runner2.acquire_lease_and_sync()
        assert runner2.get_remaining_requests() == 2

        runner2.reserve_request("indices")
        runner2.reserve_request("eod/OGDC")
        assert runner2.get_remaining_requests() == 0

        # 4th request must trip fuse because runner 1's crashed request is accounted for!
        with pytest.raises(BudgetExceededError):
            runner2.reserve_request("eod/SYS")


def test_reserve_request_fails_closed_when_lease_expired(tmp_path):
    """
    Proves Critical Issue B: A runner whose lease expires mid-run is blocked
    from making outbound upstream requests.
    """
    state_file = str(tmp_path / "budget_state.json")
    runner = PersistentCoordinator(token=None, local_state_file=state_file, lease_ttl_seconds=10, require_remote=False)
    runner.acquire_lease_and_sync()

    # Fast forward time beyond lease TTL
    with patch("collector.persistent_budget.datetime") as mock_dt:
        future_time = datetime.now(timezone.utc) + timedelta(seconds=20)
        mock_dt.now.return_value = future_time
        mock_dt.fromisoformat = datetime.fromisoformat

        # Outbound request must be blocked because lease expired
        with pytest.raises(LeaseConflictError) as exc_info:
            runner.reserve_request("snapshot")
        assert "lease expired" in str(exc_info.value).lower()


def test_lease_release_does_not_clobber_competitor_lease_or_requests(tmp_path):
    """
    Proves Critical Issue B: When runner A's lease expires and runner B takes over,
    runner A's delayed release_lease() call does NOT delete runner B's lease or requests.
    """
    state_file = str(tmp_path / "budget_state.json")
    runner_a = PersistentCoordinator(token=None, local_state_file=state_file, lease_ttl_seconds=10, require_remote=False)
    runner_a.runner_id = "runner-A"
    runner_a.acquire_lease_and_sync()
    runner_a.reserve_request("snapshot-A")

    # Runner B acquires lease after Runner A's lease expired
    runner_b = PersistentCoordinator(token=None, local_state_file=state_file, lease_ttl_seconds=10, require_remote=False)
    runner_b.runner_id = "runner-B"

    with patch("collector.persistent_budget.datetime") as mock_dt:
        future_time = datetime.now(timezone.utc) + timedelta(seconds=15)
        mock_dt.now.return_value = future_time
        mock_dt.fromisoformat = datetime.fromisoformat

        runner_b.acquire_lease_and_sync()
        runner_b.reserve_request("snapshot-B")

    # Now Runner A executes its finally block and calls release_lease()
    runner_a.release_lease()

    # Inspect persistent state: Runner B's lease and both requests must survive!
    final_state = runner_b._load_local_state()
    assert final_state["lease"]["owner"] == "runner-B"
    endpoints = [h["endpoint"] for h in final_state["history"]]
    assert "snapshot-A" in endpoints
    assert "snapshot-B" in endpoints


def test_lease_renewal_lifecycle(tmp_path):
    """Tests lease extension for active jobs."""
    state_file = str(tmp_path / "budget_state.json")
    runner = PersistentCoordinator(token=None, local_state_file=state_file, lease_ttl_seconds=60, require_remote=False)
    runner.acquire_lease_and_sync()
    initial_expiry = runner.active_lease["expires_at"]

    # Renew lease by 300s
    runner.renew_lease(extension_seconds=300)
    renewed_expiry = runner.active_lease["expires_at"]

    assert renewed_expiry > initial_expiry
    assert runner.is_lease_active() is True
    runner.release_lease()

