import pytest
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from collector.cooldown import CooldownManager, CircuitBreakerTrippedError


def test_cooldown_on_429_retry_after(tmp_path):
    state_file = str(tmp_path / "cooldown_test.json")
    manager = CooldownManager(default_cooldown_seconds=300, state_file=state_file)

    assert manager.is_in_cooldown() is False

    # Simulate 429 with Retry-After: 120 seconds
    manager.record_error(status_code=429, retry_after=120, reason="Too Many Requests")

    assert manager.is_in_cooldown() is True
    assert 110 <= manager.remaining_cooldown_seconds() <= 120

    # Next attempt must raise CircuitBreakerTrippedError
    with pytest.raises(CircuitBreakerTrippedError) as exc:
        manager.check_preflight()

    assert "circuit breaker is active" in str(exc.value)


def test_cooldown_on_consecutive_errors(tmp_path):
    state_file = str(tmp_path / "cooldown_test.json")
    manager = CooldownManager(max_consecutive_errors=3, default_cooldown_seconds=60, state_file=state_file)

    # 1st error - not in cooldown yet
    manager.record_error(status_code=500, reason="Internal error")
    assert manager.is_in_cooldown() is False

    # 2nd error
    manager.record_error(status_code=500, reason="Internal error")
    assert manager.is_in_cooldown() is False

    # 3rd error - trips circuit breaker
    manager.record_error(status_code=500, reason="Internal error")
    assert manager.is_in_cooldown() is True
    assert manager.remaining_cooldown_seconds() > 0


def test_cooldown_clears_on_success(tmp_path):
    state_file = str(tmp_path / "cooldown_test.json")
    manager = CooldownManager(state_file=state_file)

    manager.record_error(status_code=429, retry_after=10)
    assert manager.is_in_cooldown() is True

    # After success (e.g. following cooldown), error count resets
    manager.record_success()
    assert manager.is_in_cooldown() is False
    assert manager.consecutive_errors == 0


def test_cross_runner_cooldown_sync(tmp_path):
    from collector.persistent_budget import PersistentCoordinator
    state_file = str(tmp_path / "budget_state.json")
    coord1 = PersistentCoordinator(local_state_file=state_file, require_remote=False)
    cd_manager1 = CooldownManager(coordinator=coord1, state_file=str(tmp_path / "cd_state.json"))

    # Runner 1 triggers a 429
    cd_manager1.record_error(status_code=429, retry_after=180, reason="Upstream rate limit")
    assert coord1.is_in_cooldown() is True

    # Runner 2 starts in a new runner context reading shared persistent state
    coord2 = PersistentCoordinator(local_state_file=state_file, require_remote=False)
    assert coord2.is_in_cooldown() is True
    assert 170 <= coord2.get_remaining_cooldown_seconds() <= 180

    # Runner 2 attempts reserve_request - must fail closed with CircuitBreakerTrippedError before socket call
    with pytest.raises(CircuitBreakerTrippedError) as exc:
        coord2.reserve_request("/stocks")
    assert "circuit breaker is active" in str(exc.value)
