import pytest
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from collector.budget import RequestBudgetManager, BudgetExceededError


def test_budget_exhaustion_and_fail_closed(tmp_path):
    state_file = str(tmp_path / "budget_test.json")
    # Set tiny limit of 3 requests
    manager = RequestBudgetManager(daily_limit=3, state_file=state_file)

    assert manager.get_remaining_count() == 3
    assert manager.can_request(1) is True

    manager.record_request("/symbols")
    manager.record_request("/snapshot")
    manager.record_request("/indices")

    assert manager.get_used_count() == 3
    assert manager.get_remaining_count() == 0
    assert manager.can_request(1) is False

    # 4th request must raise BudgetExceededError
    with pytest.raises(BudgetExceededError) as exc_info:
        manager.record_request("/eod/OGDC")

    assert "Rolling 24h upstream budget limit (3) reached" in str(exc_info.value)
