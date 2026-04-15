"""
PBI Desktop UI Automation

Used only when we need PBIDesktop itself to write the file (PBIX path, or
PBIP with live TOM changes still in memory). pywinauto is the preferred
backend because it can locate the Power BI window by PID and dispatch
keystrokes without stealing global focus for long.

Optional dependency: import is lazy so the rest of the autonomous package
works even on systems where pywinauto is not installed.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class UIAutomationUnavailable(RuntimeError):
    """Raised when pywinauto / pywin32 are not importable."""


def _try_import_pywinauto():
    try:
        from pywinauto import Application  # type: ignore

        return Application
    except ImportError as e:
        raise UIAutomationUnavailable(
            "pywinauto is not installed. Install with `pip install pywinauto`."
        ) from e


class PbiDesktopUIAutomation:
    """
    Save / close a PBIDesktop window via UI automation.

    Window discovery is by PID. Operations are best-effort: the methods return
    structured success/failure dicts rather than raising.
    """

    SAVE_TIMEOUT_DEFAULT = 30.0  # seconds to wait for the file write to settle

    def __init__(self, save_timeout: float = SAVE_TIMEOUT_DEFAULT) -> None:
        self.save_timeout = save_timeout

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------
    def save(self, pid: int) -> Dict[str, Any]:
        """
        Send Ctrl+S to the PBIDesktop main window for the given PID and wait
        for the title to lose its dirty marker (an asterisk).
        """
        try:
            Application = _try_import_pywinauto()
        except UIAutomationUnavailable as e:
            return {
                "success": False,
                "error": str(e),
                "error_type": "ui_automation_unavailable",
            }

        try:
            app = Application(backend="uia").connect(process=pid, timeout=10)
        except Exception as e:  # noqa: BLE001
            return {
                "success": False,
                "error": f"Could not attach to PID {pid}: {e}",
                "error_type": "attach_failed",
            }

        windows = self._main_windows(app)
        if not windows:
            return {
                "success": False,
                "error": f"No top-level windows found for PID {pid}",
                "error_type": "window_not_found",
            }

        target = windows[0]
        title_before = self._safe_title(target)
        try:
            target.set_focus()
        except Exception:
            # Not fatal — we can still try sending keys
            pass

        try:
            target.type_keys("^s", set_foreground=False)
        except Exception as e:  # noqa: BLE001
            return {
                "success": False,
                "error": f"Send keys failed: {e}",
                "error_type": "send_keys_failed",
                "title_before": title_before,
            }

        # Wait for the dirty marker to disappear from the title
        deadline = time.time() + self.save_timeout
        last_title = title_before
        while time.time() < deadline:
            time.sleep(0.5)
            try:
                last_title = self._safe_title(target)
            except Exception:
                continue
            if not self._is_dirty(last_title):
                return {
                    "success": True,
                    "title_before": title_before,
                    "title_after": last_title,
                    "elapsed_seconds": round(self.save_timeout - (deadline - time.time()), 2),
                }

        return {
            "success": False,
            "error": (
                "Save timeout: title still shows unsaved marker after "
                f"{self.save_timeout}s. The save may have shown a dialog "
                "(e.g. file picker for new file)."
            ),
            "error_type": "save_timeout",
            "title_before": title_before,
            "title_after": last_title,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _main_windows(self, app) -> List[Any]:
        """Return top-level visible windows likely to be the PBI main window."""
        out: List[Any] = []
        try:
            for w in app.windows():
                try:
                    if w.is_visible() and w.is_enabled():
                        title = self._safe_title(w)
                        if title and "Power BI" in title:
                            out.append(w)
                except Exception:
                    continue
        except Exception as e:  # noqa: BLE001
            logger.debug("window enum failed: %s", e)
        return out

    @staticmethod
    def _safe_title(window) -> str:
        try:
            return window.window_text() or ""
        except Exception:
            return ""

    @staticmethod
    def _is_dirty(title: str) -> bool:
        """PBIDesktop appends an asterisk after the filename when dirty."""
        if not title:
            return False
        # Examples:
        #   "*MyReport - Power BI Desktop"
        #   "MyReport.pbix - Power BI Desktop"
        before_dash = title.split(" - ")[0].strip()
        return before_dash.startswith("*") or before_dash.endswith("*")

    @classmethod
    def availability(cls) -> Dict[str, Any]:
        """Quick capability check used by the handler."""
        try:
            _try_import_pywinauto()
            return {"available": True}
        except UIAutomationUnavailable as e:
            return {"available": False, "reason": str(e)}
