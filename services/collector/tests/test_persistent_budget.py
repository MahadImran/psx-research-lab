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


def test_reservation_near_exhaustion_249_and_250(tmp_path):
    """
    Proves Item 4: Tests boundary condition at exactly 249/250 and 250/250.
    The 250th request succeeds (hitting the cap). The 251st request must be rejected.
    """
    state_file = str(tmp_path / "budget_exhaustion.json")
    coordinator = PersistentCoordinator(token=None, local_state_file=state_file, daily_limit=250, require_remote=False)
    coordinator.runner_id = "runner-exhaustion-test"
    coordinator.acquire_lease_and_sync()

    # Pre-populate history with 249 requests
    now = datetime.now(timezone.utc)
    coordinator.history = [
        {"timestamp": (now - timedelta(minutes=i)).isoformat(), "endpoint": f"req-{i}", "runner_id": "prior-runner", "status": "RESERVED"}
        for i in range(249)
    ]
    coordinator._save_local_state({
        "history": coordinator.history,
        "lease": coordinator.active_lease,
        "cooldown_until": None,
        "snapshot_hashes": {},
    })

    assert coordinator.get_remaining_requests() == 1

    # 250th request: Must SUCCEED (249 -> 250)
    coordinator.reserve_request("endpoint-250")
    assert coordinator.get_remaining_requests() == 0

    # 251st request: Must FAIL CLOSED with BudgetExceededError
    with pytest.raises(BudgetExceededError) as exc_info:
        coordinator.reserve_request("endpoint-251")
    assert "limit (250) reached" in str(exc_info.value)


def test_quota_rechecked_after_concurrency_conflict_merge_exceeds_cap():
    """
    Proves Item 4: When an HTTP 409 conflict occurs and merged history pushes
    the total rolling count above the cap, save_remote_state must recheck and raise BudgetExceededError.
    """
    coord = PersistentCoordinator(token="test-token", repo_name="test/repo", daily_limit=250, require_remote=True)
    coord.runner_id = "runner-merge-test"
    now = datetime.now(timezone.utc)

    # Local attempt has 130 requests
    local_history = [
        {"timestamp": (now - timedelta(minutes=i)).isoformat(), "endpoint": f"local-{i}", "runner_id": "runner-merge-test", "status": "RESERVED"}
        for i in range(130)
    ]
    local_state = {
        "history": local_history,
        "lease": {"owner": "runner-merge-test", "acquired_at": now.isoformat(), "expires_at": (now + timedelta(seconds=300)).isoformat()},
        "cooldown_until": None,
        "snapshot_hashes": {},
    }

    # Fresh remote state committed by another runner in parallel has 125 distinct requests (130 + 125 = 255 > 250)
    remote_history = [
        {"timestamp": (now - timedelta(hours=1, minutes=i)).isoformat(), "endpoint": f"remote-{i}", "runner_id": "runner-parallel", "status": "RESERVED"}
        for i in range(125)
    ]
    fresh_remote_state = {
        "history": remote_history,
        "lease": {"owner": "runner-merge-test", "acquired_at": now.isoformat(), "expires_at": (now + timedelta(seconds=300)).isoformat()},
        "cooldown_until": None,
        "snapshot_hashes": {},
    }
    b64_fresh = base64.b64encode(json.dumps(fresh_remote_state).encode("utf-8")).decode("utf-8")

    with patch("urllib.request.urlopen") as mock_urlopen:
        # 1st PUT -> 409 Conflict
        mock_conflict = urllib.error.HTTPError("url", 409, "Conflict", {}, None)

        # Reload GET -> returns fresh state
        mock_reload = MagicMock(status=200)
        mock_reload.read.return_value = json.dumps({"sha": "sha-fresh", "content": b64_fresh}).encode("utf-8")
        mock_reload.__enter__.return_value = mock_reload

        mock_urlopen.side_effect = [mock_conflict, mock_reload]

        # Must raise BudgetExceededError after merging history because 255 > 250
        with pytest.raises(BudgetExceededError) as exc_info:
            coord.save_remote_state(local_state, max_retries=2)
        assert "exceeded after merging concurrent runner requests" in str(exc_info.value)


def test_authoritative_lease_verification_blocks_stale_or_hijacked_runner(tmp_path):
    """
    Proves Item 4: Loading state never replaces active_lease with another runner's lease.
    If another runner took over the lease, reserve_request detects lack of ownership and fails closed.
    """
    state_file = str(tmp_path / "budget_state.json")
    runner_orig = PersistentCoordinator(token=None, local_state_file=state_file, lease_ttl_seconds=10, require_remote=False)
    runner_orig.runner_id = "runner-orig"
    runner_orig.acquire_lease_and_sync()

    # Another runner claims lease (simulating takeover after expiration)
    runner_new = PersistentCoordinator(token=None, local_state_file=state_file, lease_ttl_seconds=300, require_remote=False)
    runner_new.runner_id = "runner-new"

    with patch("collector.persistent_budget.datetime") as mock_dt:
        future_time = datetime.now(timezone.utc) + timedelta(seconds=20)
        mock_dt.now.return_value = future_time
        mock_dt.fromisoformat = datetime.fromisoformat

        runner_new.acquire_lease_and_sync()
        assert runner_new.is_lease_active() is True

    # Now runner_orig tries to reserve a request: must fail closed because lease belongs to runner-new
    with pytest.raises(LeaseConflictError) as exc_info:
        runner_orig.reserve_request("market-watch")
    assert "lost or does not hold lease ownership" in str(exc_info.value)
    assert runner_orig.active_lease is None


def test_deterministic_multi_client_concurrency_without_mocks(tmp_path):
    """
    Proves Item 4: Deterministic concurrency test with independent coordinator clients
    operating on shared state without using mocks.
    """
    state_file = str(tmp_path / "shared_persistent_state.json")

    client_a = PersistentCoordinator(token=None, local_state_file=state_file, lease_ttl_seconds=300, require_remote=False)
    client_a.runner_id = "client-alpha"

    client_b = PersistentCoordinator(token=None, local_state_file=state_file, lease_ttl_seconds=300, require_remote=False)
    client_b.runner_id = "client-beta"

    # Client A acquires lease cleanly
    client_a.acquire_lease_and_sync()
    assert client_a.is_lease_active() is True

    # Client B attempts to acquire lease simultaneously -> rejected
    with pytest.raises(LeaseConflictError) as exc_info:
        client_b.acquire_lease_and_sync()
    assert "currently held by client-alpha" in str(exc_info.value)
    assert client_b.is_lease_active() is False

    # Client A pre-reserves requests
    client_a.reserve_request("indices")
    client_a.reserve_request("snapshot")

    # Client A releases lease cleanly
    client_a.release_lease()
    assert client_a.is_lease_active() is False

    # Now Client B can acquire the lease and see the 2 requests preserved in shared state
    client_b.acquire_lease_and_sync()
    assert client_b.is_lease_active() is True
    assert client_b.get_remaining_requests() == 248  # 250 - 2
    client_b.release_lease()

