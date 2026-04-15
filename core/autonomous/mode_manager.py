"""
Autonomous Mode Manager

Thread-safe session-scoped flag that gates destructive lifecycle operations
(save/close/reopen). Cleared automatically when:
  - User calls exit_mode()
  - Idle timeout elapses (default 30 minutes)
  - Hard duration ceiling elapses (default 4 hours, max 4 hours enforced)
  - MCP server restarts (in-memory only, never persisted)

All gated tools call .check_active() and receive a structured failure dict
if the flag is off or expired.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# Defaults — overridable per enter_mode() call
DEFAULT_IDLE_TIMEOUT_MINUTES = 30
DEFAULT_MAX_DURATION_MINUTES = 240
HARD_CEILING_MINUTES = 240  # cannot exceed regardless of caller


@dataclass
class _ModeState:
    """Internal state snapshot. Lives only in process memory."""

    activated_at: float = 0.0
    last_activity_at: float = 0.0
    idle_timeout_seconds: int = DEFAULT_IDLE_TIMEOUT_MINUTES * 60
    max_duration_seconds: int = DEFAULT_MAX_DURATION_MINUTES * 60
    session_id: str = ""
    log_path: Optional[str] = None
    activation_reason: str = ""
    extras: Dict[str, Any] = field(default_factory=dict)


class AutonomousModeManager:
    """
    Singleton autonomous-mode flag.

    The flag is OFF by default. Call enter_mode() to turn it on; gated tools
    call check_active() before performing destructive ops. Every successful
    check_active() bumps the idle timer.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._active: bool = False
        self._state: Optional[_ModeState] = None

    # ------------------------------------------------------------------
    # Activation lifecycle
    # ------------------------------------------------------------------
    def enter_mode(
        self,
        idle_timeout_minutes: Optional[int] = None,
        max_duration_minutes: Optional[int] = None,
        log_path: Optional[str] = None,
        reason: str = "",
        extras: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Activate autonomous mode.

        Args:
            idle_timeout_minutes: Auto-deactivate after N minutes of no
                gated tool calls. Default 30.
            max_duration_minutes: Hard ceiling regardless of activity.
                Default 240, max 240 (4 hours).
            log_path: Optional override for the audit log directory.
            reason: Free text description of why mode was activated.
            extras: Caller-provided context recorded in the audit log.

        Returns:
            Status dict with `success`, current state, expiry timestamps.
        """
        idle_min = (
            idle_timeout_minutes
            if idle_timeout_minutes is not None
            else DEFAULT_IDLE_TIMEOUT_MINUTES
        )
        max_min = (
            max_duration_minutes
            if max_duration_minutes is not None
            else DEFAULT_MAX_DURATION_MINUTES
        )

        if idle_min <= 0 or max_min <= 0:
            return {
                "success": False,
                "error": "Timeouts must be positive",
                "error_type": "invalid_parameters",
            }
        if max_min > HARD_CEILING_MINUTES:
            max_min = HARD_CEILING_MINUTES
        if idle_min > max_min:
            idle_min = max_min

        now = time.time()
        session_id = f"autonomous-{int(now)}"

        with self._lock:
            self._active = True
            self._state = _ModeState(
                activated_at=now,
                last_activity_at=now,
                idle_timeout_seconds=idle_min * 60,
                max_duration_seconds=max_min * 60,
                session_id=session_id,
                log_path=log_path,
                activation_reason=reason or "",
                extras=dict(extras or {}),
            )

        logger.info(
            "Autonomous mode ACTIVATED: session=%s idle=%dmin max=%dmin",
            session_id,
            idle_min,
            max_min,
        )
        return {
            "success": True,
            "active": True,
            "session_id": session_id,
            "idle_timeout_minutes": idle_min,
            "max_duration_minutes": max_min,
            "expires_at_idle": now + idle_min * 60,
            "expires_at_hard": now + max_min * 60,
            "log_path": log_path,
        }

    def exit_mode(self, reason: str = "manual") -> Dict[str, Any]:
        """
        Deactivate autonomous mode. Idempotent.

        Returns:
            Status dict including the duration the session was active.
        """
        with self._lock:
            if not self._active or not self._state:
                return {
                    "success": True,
                    "active": False,
                    "message": "Already inactive",
                }
            session_id = self._state.session_id
            duration = time.time() - self._state.activated_at
            log_path = self._state.log_path
            self._active = False
            self._state = None

        logger.info(
            "Autonomous mode DEACTIVATED: session=%s reason=%s duration=%.1fs",
            session_id,
            reason,
            duration,
        )
        return {
            "success": True,
            "active": False,
            "session_id": session_id,
            "reason": reason,
            "duration_seconds": round(duration, 1),
            "log_path": log_path,
        }

    # ------------------------------------------------------------------
    # Activity tracking and gating
    # ------------------------------------------------------------------
    def check_active(self, bump: bool = True) -> Dict[str, Any]:
        """
        Validate the flag is set and not expired.

        Args:
            bump: When True (default), updates the idle timer on success.

        Returns:
            On active: `{"active": True, "session_id": ..., ...}`.
            On inactive/expired: `{"active": False, "error": ..., "error_type": ...}`.
        """
        with self._lock:
            if not self._active or not self._state:
                return {
                    "active": False,
                    "error": (
                        "Autonomous mode is not active. "
                        "Call 12_Autonomous_Workflow operation=enter_mode first."
                    ),
                    "error_type": "autonomous_mode_inactive",
                }

            now = time.time()
            state = self._state

            # Hard ceiling check
            hard_age = now - state.activated_at
            if hard_age > state.max_duration_seconds:
                logger.warning(
                    "Autonomous mode hard-ceiling reached: session=%s age=%.0fs",
                    state.session_id,
                    hard_age,
                )
                self._active = False
                self._state = None
                return {
                    "active": False,
                    "error": (
                        f"Autonomous mode expired (hard ceiling "
                        f"{state.max_duration_seconds // 60} min reached). "
                        "Re-enter mode to continue."
                    ),
                    "error_type": "autonomous_mode_expired_hard",
                    "expired_after_seconds": round(hard_age, 1),
                }

            # Idle timeout check
            idle_age = now - state.last_activity_at
            if idle_age > state.idle_timeout_seconds:
                logger.warning(
                    "Autonomous mode idle-timeout reached: session=%s idle=%.0fs",
                    state.session_id,
                    idle_age,
                )
                self._active = False
                self._state = None
                return {
                    "active": False,
                    "error": (
                        f"Autonomous mode expired (idle "
                        f"{state.idle_timeout_seconds // 60} min reached). "
                        "Re-enter mode to continue."
                    ),
                    "error_type": "autonomous_mode_expired_idle",
                    "idle_seconds": round(idle_age, 1),
                }

            if bump:
                state.last_activity_at = now

            return {
                "active": True,
                "session_id": state.session_id,
                "idle_remaining_seconds": round(state.idle_timeout_seconds - idle_age, 1),
                "hard_remaining_seconds": round(state.max_duration_seconds - hard_age, 1),
                "log_path": state.log_path,
            }

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------
    def status(self) -> Dict[str, Any]:
        """Return a non-mutating snapshot of mode state."""
        with self._lock:
            if not self._active or not self._state:
                return {"active": False}
            now = time.time()
            state = self._state
            return {
                "active": True,
                "session_id": state.session_id,
                "activated_at": state.activated_at,
                "last_activity_at": state.last_activity_at,
                "idle_timeout_seconds": state.idle_timeout_seconds,
                "max_duration_seconds": state.max_duration_seconds,
                "idle_remaining_seconds": round(
                    state.idle_timeout_seconds - (now - state.last_activity_at),
                    1,
                ),
                "hard_remaining_seconds": round(
                    state.max_duration_seconds - (now - state.activated_at),
                    1,
                ),
                "log_path": state.log_path,
                "reason": state.activation_reason,
                "extras": dict(state.extras),
            }

    def is_active(self) -> bool:
        """Cheap boolean check — does NOT bump the idle timer."""
        result = self.check_active(bump=False)
        return bool(result.get("active"))

    def session_id(self) -> Optional[str]:
        """Return current session id or None."""
        with self._lock:
            return self._state.session_id if self._state else None

    def log_path(self) -> Optional[str]:
        """Return configured log path override or None."""
        with self._lock:
            return self._state.log_path if self._state else None


# Module-level singleton
_mode_manager = AutonomousModeManager()


def get_mode_manager() -> AutonomousModeManager:
    """Return the process-wide AutonomousModeManager singleton."""
    return _mode_manager
