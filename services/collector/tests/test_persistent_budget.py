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
