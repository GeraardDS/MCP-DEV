"""Unit tests for core.autonomous.mode_manager."""

import time

from core.autonomous.mode_manager import (
    AutonomousModeManager,
    HARD_CEILING_MINUTES,
)


def test_starts_inactive():
    mgr = AutonomousModeManager()
    assert mgr.is_active() is False
    status = mgr.status()
    assert status == {"active": False}


def test_enter_exit_roundtrip():
    mgr = AutonomousModeManager()
    result = mgr.enter_mode(reason="unit test")
    assert result["success"] is True
    assert result["active"] is True
    assert mgr.is_active()

    check = mgr.check_active()
    assert check["active"] is True
    assert check["session_id"] == result["session_id"]

    exit_result = mgr.exit_mode(reason="done")
    assert exit_result["success"] is True
    assert exit_result["active"] is False
    assert mgr.is_active() is False


def test_exit_is_idempotent():
    mgr = AutonomousModeManager()
    mgr.enter_mode()
    assert mgr.exit_mode()["active"] is False
    # Second call — already inactive
    again = mgr.exit_mode()
    assert again["active"] is False
    assert again["success"] is True


def test_invalid_timeouts_rejected():
    mgr = AutonomousModeManager()
    result = mgr.enter_mode(idle_timeout_minutes=0)
    assert result["success"] is False
    assert result["error_type"] == "invalid_parameters"
    assert mgr.is_active() is False


def test_hard_ceiling_clamped():
    mgr = AutonomousModeManager()
    result = mgr.enter_mode(max_duration_minutes=9999)
    assert result["max_duration_minutes"] == HARD_CEILING_MINUTES


def test_idle_caps_max():
    """idle_timeout > max_duration is clamped to max."""
    mgr = AutonomousModeManager()
    result = mgr.enter_mode(idle_timeout_minutes=600, max_duration_minutes=60)
    assert result["idle_timeout_minutes"] <= result["max_duration_minutes"]


def test_idle_expiry_deactivates():
    mgr = AutonomousModeManager()
    mgr.enter_mode(idle_timeout_minutes=1)
    # Force the last-activity timestamp into the past
    assert mgr._state is not None  # noqa: SLF001
    mgr._state.last_activity_at = time.time() - 120  # noqa: SLF001

    check = mgr.check_active()
    assert check["active"] is False
    assert check["error_type"] == "autonomous_mode_expired_idle"
    assert mgr.is_active() is False


def test_hard_expiry_deactivates():
    mgr = AutonomousModeManager()
    mgr.enter_mode(idle_timeout_minutes=60, max_duration_minutes=1)
    assert mgr._state is not None  # noqa: SLF001
    mgr._state.activated_at = time.time() - 120  # noqa: SLF001

    check = mgr.check_active()
    assert check["active"] is False
    assert check["error_type"] == "autonomous_mode_expired_hard"


def test_bump_updates_last_activity():
    mgr = AutonomousModeManager()
    mgr.enter_mode()
    assert mgr._state is not None  # noqa: SLF001
    original = mgr._state.last_activity_at  # noqa: SLF001
    time.sleep(0.01)
    mgr.check_active(bump=True)
    assert mgr._state.last_activity_at > original  # noqa: SLF001


def test_bump_false_preserves_last_activity():
    mgr = AutonomousModeManager()
    mgr.enter_mode()
    assert mgr._state is not None  # noqa: SLF001
    original = mgr._state.last_activity_at  # noqa: SLF001
    time.sleep(0.01)
    mgr.check_active(bump=False)
    assert mgr._state.last_activity_at == original  # noqa: SLF001
