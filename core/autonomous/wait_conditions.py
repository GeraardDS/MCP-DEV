"""
Wait-for-Readiness

Escalating readiness levels after launching or reconnecting to PBIDesktop.
Each higher level subsumes the ones below it:

    1. PROCESS          — PBIDesktop.exe is running
    2. PORT             — msmdsrv child is listening on a TCP port
    3. ADOMD            — we can open an ADOMD connection to that port
    4. IDENTITY         — the connection's database matches the expected file
    5. REFRESH_IDLE     — no running TMSCHEDULER/REFRESH commands

Default target level is IDENTITY. REFRESH_IDLE is opt-in because refresh can
run for many minutes on large models.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ReadinessLevel(IntEnum):
    PROCESS = 1
    PORT = 2
    ADOMD = 3
    IDENTITY = 4
    REFRESH_IDLE = 5


LEVEL_NAMES = {lvl.value: lvl.name.lower() for lvl in ReadinessLevel}


@dataclass
class WaitResult:
    success: bool
    reached_level: int
    target_level: int
    elapsed_seconds: float
    port: Optional[int] = None
    pid: Optional[int] = None
    database_name: Optional[str] = None
    file_full_path: Optional[str] = None
    error: Optional[str] = None
    error_type: Optional[str] = None
    attempts: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "reached_level": self.reached_level,
            "reached_level_name": LEVEL_NAMES.get(self.reached_level, "none"),
            "target_level": self.target_level,
            "target_level_name": LEVEL_NAMES.get(self.target_level, "unknown"),
            "elapsed_seconds": round(self.elapsed_seconds, 2),
            "port": self.port,
            "pid": self.pid,
            "database_name": self.database_name,
            "file_full_path": self.file_full_path,
            "attempts": self.attempts,
            "error": self.error,
            "error_type": self.error_type,
        }


class WaitConditions:
    """
    Poll for PBIDesktop readiness up to the requested level.

    Uses the existing `PowerBIDesktopDetector` for port discovery and
    `ConnectionManager` / ADOMD for deeper probes.
    """

    DEFAULT_TIMEOUT = 180.0
    POLL_INITIAL = 0.5
    POLL_MAX = 3.0

    def __init__(self, connection_state) -> None:  # type: ignore[no-untyped-def]
        self._connection_state = connection_state

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def wait(
        self,
        file_full_path: str,
        target_level: ReadinessLevel = ReadinessLevel.IDENTITY,
        timeout_seconds: float = DEFAULT_TIMEOUT,
    ) -> WaitResult:
        """
        Poll until `target_level` is reached or timeout elapses.

        Args:
            file_full_path: Expected .pbix or .pbip path (used for IDENTITY
                match; may be ignored at lower levels).
            target_level: Highest level to verify.
            timeout_seconds: Max wall time to wait.

        Returns:
            WaitResult describing the deepest level that was reached.
        """
        start = time.time()
        deadline = start + max(timeout_seconds, 1.0)
        interval = self.POLL_INITIAL
        attempts = 0
        last_result: Optional[Dict[str, Any]] = None

        while time.time() < deadline:
            attempts += 1
            last_result = self._probe(file_full_path, target_level)
            if last_result["reached_level"] >= int(target_level):
                return WaitResult(
                    success=True,
                    reached_level=last_result["reached_level"],
                    target_level=int(target_level),
                    elapsed_seconds=time.time() - start,
                    port=last_result.get("port"),
                    pid=last_result.get("pid"),
                    database_name=last_result.get("database_name"),
                    file_full_path=last_result.get("file_full_path"),
                    attempts=attempts,
                )
            time.sleep(interval)
            interval = min(interval * 1.5, self.POLL_MAX)

        reached = (last_result or {}).get("reached_level", 0)
        err = (last_result or {}).get("error") or (
            f"Timed out after {timeout_seconds:.0f}s at level "
            f"{LEVEL_NAMES.get(reached, 'none')}"
        )
        return WaitResult(
            success=False,
            reached_level=reached,
            target_level=int(target_level),
            elapsed_seconds=time.time() - start,
            port=(last_result or {}).get("port"),
            pid=(last_result or {}).get("pid"),
            database_name=(last_result or {}).get("database_name"),
            file_full_path=(last_result or {}).get("file_full_path"),
            error=err,
            error_type=(last_result or {}).get("error_type") or "wait_timeout",
            attempts=attempts,
        )

    # ------------------------------------------------------------------
    # Internal: single probe walking up the levels
    # ------------------------------------------------------------------
    def _probe(
        self,
        file_full_path: str,
        target_level: ReadinessLevel,
    ) -> Dict[str, Any]:
        out: Dict[str, Any] = {"reached_level": 0}

        # Level 1: PROCESS
        process = self._find_process(file_full_path)
        if not process:
            return {
                **out,
                "error": "PBIDesktop.exe not found for file",
                "error_type": "process_not_found",
            }
        out["pid"] = process.pid
        out["file_full_path"] = process.file_path
        out["reached_level"] = int(ReadinessLevel.PROCESS)
        if target_level == ReadinessLevel.PROCESS:
            return out

        # Level 2: PORT
        instances = self._detect_instances()
        match = self._match_instance(instances, file_full_path)
        if not match:
            return {
                **out,
                "error": "msmdsrv port not yet listening",
                "error_type": "port_not_ready",
            }
        out["port"] = match.get("port")
        out["database_name"] = match.get("database_name") or match.get("name")
        out["reached_level"] = int(ReadinessLevel.PORT)
        if target_level == ReadinessLevel.PORT:
            return out

        # Level 3: ADOMD
        conn_str = match.get("connection_string") or (
            f"Data Source=localhost:{out['port']}" if out.get("port") else None
        )
        if not conn_str or not self._adomd_probe(conn_str):
            return {
                **out,
                "error": "ADOMD probe failed",
                "error_type": "adomd_not_ready",
            }
        out["reached_level"] = int(ReadinessLevel.ADOMD)
        if target_level == ReadinessLevel.ADOMD:
            return out

        # Level 4: IDENTITY
        if not self._identity_match(match, file_full_path):
            return {
                **out,
                "error": (
                    "Database identity does not yet match expected file "
                    f"{os.path.basename(file_full_path)}"
                ),
                "error_type": "identity_mismatch",
            }
        out["reached_level"] = int(ReadinessLevel.IDENTITY)
        if target_level == ReadinessLevel.IDENTITY:
            return out

        # Level 5: REFRESH_IDLE
        if not self._refresh_idle(conn_str):
            return {
                **out,
                "error": "Refresh/processing still in progress",
                "error_type": "refresh_busy",
            }
        out["reached_level"] = int(ReadinessLevel.REFRESH_IDLE)
        return out

    # ------------------------------------------------------------------
    # Level helpers
    # ------------------------------------------------------------------
    def _find_process(self, file_full_path: str):
        from core.autonomous.process_manager import PbiDesktopProcessManager

        return PbiDesktopProcessManager().find_for_file(file_full_path)

    def _detect_instances(self) -> List[Dict[str, Any]]:
        try:
            from core.infrastructure.connection_manager import PowerBIDesktopDetector

            detector = PowerBIDesktopDetector()
            return detector.detect_instances() or []
        except Exception as e:  # noqa: BLE001
            logger.debug("detect_instances failed: %s", e)
            return []

    @staticmethod
    def _match_instance(
        instances: List[Dict[str, Any]],
        file_full_path: str,
    ) -> Optional[Dict[str, Any]]:
        if not instances:
            return None
        norm = os.path.normcase(os.path.normpath(file_full_path or ""))
        for inst in instances:
            cand = inst.get("file_full_path") or inst.get("pbip_folder_path") or ""
            if cand and os.path.normcase(os.path.normpath(cand)) == norm:
                return inst
        # Fallback: basename match (covers pbip→pbix differences)
        base = os.path.basename(file_full_path or "").lower()
        for inst in instances:
            cand = (inst.get("file_full_path") or "").lower()
            if base and base in cand:
                return inst
        # Last resort: return first instance so the caller can still probe
        return instances[0]

    def _adomd_probe(self, connection_string: str) -> bool:
        """Open+close an ADOMD connection. Returns True on success."""
        try:
            from core.infrastructure.dll_paths import load_adomd_assembly

            if not load_adomd_assembly():
                return False
            from Microsoft.AnalysisServices.AdomdClient import (  # type: ignore
                AdomdConnection,
            )

            conn = AdomdConnection(connection_string)
            try:
                conn.Open()
                return True
            finally:
                try:
                    conn.Close()
                except Exception:
                    pass
        except Exception as e:  # noqa: BLE001
            logger.debug("adomd probe failed: %s", e)
            return False

    def _identity_match(
        self,
        instance: Dict[str, Any],
        file_full_path: str,
    ) -> bool:
        if not file_full_path:
            return True
        cand = instance.get("file_full_path") or ""
        if not cand:
            return False
        return os.path.normcase(os.path.normpath(cand)) == os.path.normcase(
            os.path.normpath(file_full_path)
        )

    def _refresh_idle(self, connection_string: str) -> bool:
        """
        Query $SYSTEM.DISCOVER_COMMANDS for running REFRESH/PROCESS commands.
        Returns True when nothing matching is in-flight.
        """
        try:
            from core.infrastructure.dll_paths import load_adomd_assembly

            if not load_adomd_assembly():
                return True  # cannot probe — assume idle
            from Microsoft.AnalysisServices.AdomdClient import (  # type: ignore
                AdomdConnection,
                AdomdCommand,
            )

            conn = AdomdConnection(connection_string)
            try:
                conn.Open()
                cmd = AdomdCommand(
                    "SELECT COMMAND_TEXT FROM $SYSTEM.DISCOVER_COMMANDS",
                    conn,
                )
                reader = cmd.ExecuteReader()
                try:
                    keywords = ("REFRESH", "PROCESS", "TMSCHEDULER")
                    while reader.Read():
                        text = reader.GetValue(0)
                        if not text:
                            continue
                        upper = str(text).upper()
                        if any(k in upper for k in keywords):
                            return False
                    return True
                finally:
                    try:
                        reader.Close()
                    except Exception:
                        pass
            finally:
                try:
                    conn.Close()
                except Exception:
                    pass
        except Exception as e:  # noqa: BLE001
            logger.debug("refresh_idle probe failed: %s", e)
            return True  # best-effort — don't block readiness
