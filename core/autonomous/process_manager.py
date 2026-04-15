"""
PBIDesktop.exe Process Manager

Find, kill, and launch Power BI Desktop processes for a specific PBIX/PBIP file.

Strategy:
- Find: walk psutil for PBIDesktop.exe processes, match by command-line args
  (the .pbix/.pbip path appears as an argument).
- Kill: psutil.terminate() with grace period, then kill() if needed.
- Launch: subprocess.Popen(["PBIDesktop.exe", "<file>"]) — locates exe via
  HKLM/HKCU registry (App Paths), Program Files, or PATH.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class PbiDesktopProcess:
    """Snapshot of a running PBIDesktop.exe."""

    pid: int
    cmdline: List[str]
    file_path: Optional[str]
    started_at: float
    msmdsrv_pid: Optional[int] = None


class PbiDesktopProcessManager:
    """Find / kill / launch PBIDesktop.exe instances."""

    GRACE_SECONDS_DEFAULT = 8.0

    EXE_CANDIDATES = (
        r"C:\Program Files\Microsoft Power BI Desktop\bin\PBIDesktop.exe",
        r"C:\Program Files (x86)\Microsoft Power BI Desktop\bin\PBIDesktop.exe",
        r"C:\Program Files\WindowsApps\Microsoft.MicrosoftPowerBIDesktop" r"\bin\PBIDesktop.exe",
    )

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------
    def find_for_file(
        self,
        file_full_path: str,
        prefer_pid: Optional[int] = None,
    ) -> Optional[PbiDesktopProcess]:
        """
        Return the PBIDesktop.exe whose command-line references the given file.

        When multiple processes match (e.g. a PBIDesktop launcher plus a
        user-facing instance, or stale instances from a prior run), prefer:
          1. The exact `prefer_pid` if given and still alive with a match.
          2. The process that has a live msmdsrv child (indicates the real AS
             instance — launcher processes do not spawn msmdsrv).
          3. Otherwise the most recently started matching process.
        """
        if not file_full_path:
            return None
        norm = self._normalize(file_full_path)
        matches = [
            p for p in self.find_all()
            if p.file_path and self._normalize(p.file_path) == norm
        ]
        if not matches:
            return None

        if prefer_pid is not None:
            for p in matches:
                if p.pid == prefer_pid:
                    return p

        # Prefer processes with a live msmdsrv child (the real AS host).
        with_msmdsrv = [p for p in matches if self._has_msmdsrv_child(p.pid)]
        if with_msmdsrv:
            with_msmdsrv.sort(key=lambda p: p.started_at, reverse=True)
            return with_msmdsrv[0]

        # Fallback: newest matching process.
        matches.sort(key=lambda p: p.started_at, reverse=True)
        return matches[0]

    @staticmethod
    def _has_msmdsrv_child(pid: int) -> bool:
        """Return True if the given PBIDesktop PID has a running msmdsrv child."""
        try:
            import psutil  # type: ignore

            parent = psutil.Process(pid)
            for child in parent.children(recursive=False):
                try:
                    name = (child.name() or "").lower()
                    if "msmdsrv" in name:
                        return True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception:  # noqa: BLE001
            return False
        return False

    def find_all(self) -> List[PbiDesktopProcess]:
        """List all running PBIDesktop.exe processes with their file paths."""
        try:
            import psutil  # type: ignore
        except ImportError:
            logger.warning("psutil not available — cannot enumerate PBIDesktop")
            return []

        out: List[PbiDesktopProcess] = []
        for proc in psutil.process_iter(["pid", "name", "create_time"]):
            try:
                if not proc.info.get("name"):
                    continue
                if "PBIDesktop" not in proc.info["name"]:
                    continue
                cmdline = proc.cmdline()
                file_path = self._extract_file(cmdline)
                out.append(
                    PbiDesktopProcess(
                        pid=proc.info["pid"],
                        cmdline=cmdline,
                        file_path=file_path,
                        started_at=proc.info.get("create_time", 0.0) or 0.0,
                    )
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            except Exception as e:  # noqa: BLE001
                logger.debug("PBIDesktop enum skip pid=%s: %s", proc.pid, e)
        return out

    # ------------------------------------------------------------------
    # Kill
    # ------------------------------------------------------------------
    def kill(
        self,
        pid: int,
        grace_seconds: float = GRACE_SECONDS_DEFAULT,
        kill_children: bool = True,
    ) -> Dict[str, Any]:
        """
        Terminate the given PID, then kill if it does not exit within
        grace_seconds. Optionally kills child processes too (msmdsrv etc).
        """
        try:
            import psutil  # type: ignore
        except ImportError:
            return {
                "success": False,
                "error": "psutil unavailable",
                "error_type": "psutil_unavailable",
            }

        try:
            proc = psutil.Process(pid)
        except psutil.NoSuchProcess:
            return {
                "success": True,
                "message": f"Process {pid} already gone",
                "pid": pid,
                "force_killed": False,
            }

        children: List[Any] = []
        try:
            if kill_children:
                children = proc.children(recursive=True)
        except psutil.Error:
            children = []

        targets = [proc] + children
        for p in targets:
            try:
                p.terminate()
            except psutil.NoSuchProcess:
                continue
            except psutil.AccessDenied:
                pass

        gone, alive = psutil.wait_procs(targets, timeout=grace_seconds)
        force_killed = False
        for p in alive:
            try:
                p.kill()
                force_killed = True
            except psutil.NoSuchProcess:
                continue
            except psutil.AccessDenied:
                pass

        if alive:
            psutil.wait_procs(alive, timeout=3.0)

        return {
            "success": True,
            "pid": pid,
            "force_killed": force_killed,
            "children_killed": len(children),
            "message": (
                f"Killed PID {pid}"
                + (" (forced)" if force_killed else "")
                + (f" plus {len(children)} children" if children else "")
            ),
        }

    # ------------------------------------------------------------------
    # Launch
    # ------------------------------------------------------------------
    def launch(
        self,
        file_full_path: str,
        exe_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Launch PBIDesktop.exe with the given file. Uses creationflags=DETACHED
        on Windows so the process keeps running after the MCP exits.
        """
        if not file_full_path or not os.path.exists(file_full_path):
            return {
                "success": False,
                "error": f"File not found: {file_full_path}",
                "error_type": "file_not_found",
            }

        exe = exe_path or self._locate_exe()
        if not exe:
            return {
                "success": False,
                "error": (
                    "PBIDesktop.exe not found. Pass exe_path explicitly or "
                    "ensure it is installed in Program Files."
                ),
                "error_type": "pbidesktop_not_found",
            }

        try:
            creationflags = 0
            if os.name == "nt":
                # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP — survive MCP exit
                creationflags = 0x00000008 | 0x00000200
            popen = subprocess.Popen(
                [exe, file_full_path],
                creationflags=creationflags,
                close_fds=True,
            )
            logger.info(
                "Launched PBIDesktop pid=%s exe=%s file=%s",
                popen.pid,
                exe,
                file_full_path,
            )
            return {
                "success": True,
                "pid": popen.pid,
                "exe": exe,
                "file": file_full_path,
                "started_at": time.time(),
            }
        except OSError as e:
            return {
                "success": False,
                "error": f"Launch failed: {e}",
                "error_type": "launch_failed",
                "exe": exe,
            }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _locate_exe(self) -> Optional[str]:
        for candidate in self.EXE_CANDIDATES:
            if os.path.isfile(candidate):
                return candidate
        # Registry App Paths
        try:
            import winreg  # type: ignore

            for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                for key in (r"Software\Microsoft\Windows\CurrentVersion\App Paths\PBIDesktop.exe",):
                    try:
                        with winreg.OpenKey(hive, key) as k:
                            value, _ = winreg.QueryValueEx(k, None)
                            if value and os.path.isfile(value):
                                return value
                    except FileNotFoundError:
                        continue
        except ImportError:
            pass
        # PATH lookup (rare)
        for path_dir in os.environ.get("PATH", "").split(os.pathsep):
            candidate = os.path.join(path_dir, "PBIDesktop.exe")
            if os.path.isfile(candidate):
                return candidate
        return None

    @staticmethod
    def _extract_file(cmdline: List[str]) -> Optional[str]:
        """Return the .pbix or .pbip path argument, if present."""
        for arg in cmdline or []:
            lo = arg.lower()
            if lo.endswith(".pbix") or lo.endswith(".pbip"):
                return arg
            if ".pbix" in lo or ".pbip" in lo:
                # Quoted path; strip quotes
                return arg.strip('"')
        return None

    @staticmethod
    def _normalize(path: str) -> str:
        try:
            return os.path.normcase(os.path.normpath(path))
        except Exception:
            return path
