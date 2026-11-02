import pytest
from datetime import datetime, timezone, timedelta
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from collector.persistent_budget import (
    PersistentCoordinator,
    BudgetExceededError,
    LeaseConflictError,
)


def test_persistent_coordinator_lease_lifecycle(tmp_path):
    state_file = str(tmp_path / "budget_state.json")
    coord1 = PersistentCoordinator(token=None, local_state_file=state_file, lease_ttl_seconds=10)
    coord1.runner_id = "runner-1"

    # 1. Acquire lease
    coord1.acquire_lease_and_sync()
    assert coord1.active_lease is not None
    assert coord1.active_lease["owner"] == "runner-1"

    # 2. Competing runner cannot acquire while lease is active
    coord2 = PersistentCoordinator(token=None, local_state_file=state_file, lease_ttl_seconds=10)
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
        daily_limit=5,  # small limit for testing
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


def test_persistent_coordinator_purges_expired_history(tmp_path):
    state_file = str(tmp_path / "budget_purge.json")
    coord = PersistentCoordinator(token=None, local_state_file=state_file, daily_limit=10)

    now = datetime.now(timezone.utc)
    old_time = (now - timedelta(hours=25)).isoformat()
    recent_time = (now - timedelta(hours=2)).isoformat()

    # Seed state with one old request and one recent request
    seed_state = {
        "history": [
            {"timestamp": old_time, "endpoint": "old_call", "runner_id": "gha-old"},
            {"timestamp": recent_time, "endpoint": "recent_call", "runner_id": "gha-new"},
        ],
        "lease": None,
        "cooldown_until": None,
    }
    coord._save_local_state(seed_state)

    coord.acquire_lease_and_sync()
    # The 25h old request must be purged
    assert len(coord.history) == 1
    assert coord.history[0]["endpoint"] == "recent_call"
    assert coord.get_remaining_requests() == 9
    coord.release_lease()
