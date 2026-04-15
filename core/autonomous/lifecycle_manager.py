"""
Lifecycle Manager

Orchestrates the autonomous save / close / reopen / reload macro. Every
destructive call is gated on `AutonomousModeManager.is_active()` — if the
mode flag is off the operation returns a structured error instead of acting.

This class holds no state of its own; it composes the other autonomous
primitives (mode gate, pending-changes detector, process manager, UI
automation, wait conditions) plus the shared `connection_state`.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional

from core.autonomous.audit_log import AuditLog
from core.autonomous.mode_manager import AutonomousModeManager, get_mode_manager
from core.autonomous.pending_changes import PendingChangesDetector
from core.autonomous.process_manager import PbiDesktopProcessManager
from core.autonomous.validation_runner import ValidationRunner
from core.autonomous.wait_conditions import ReadinessLevel, WaitConditions

logger = logging.getLogger(__name__)


class LifecycleManager:
    """Compose autonomous primitives into save/close/reopen/reload flows."""

    def __init__(
        self,
        connection_state,  # type: ignore[no-untyped-def]
        mode_manager: Optional[AutonomousModeManager] = None,
    ) -> None:
        self._cs = connection_state
        self._mode = mode_manager or get_mode_manager()
        self._processes = PbiDesktopProcessManager()
        self._pending = PendingChangesDetector(connection_state)
        self._waiter = WaitConditions(connection_state)
        self._audit: Optional[AuditLog] = None
        self._audit_session: Optional[str] = None

    # ------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------
    def _get_audit(self) -> Optional[AuditLog]:
        session_id = self._mode.session_id()
        if not session_id:
            return None
        if self._audit is None or self._audit_session != session_id:
            self._audit = AuditLog(session_id, log_path=self._mode.log_path())
            self._audit_session = session_id
        return self._audit

    # ------------------------------------------------------------------
    # Gate helper
    # ------------------------------------------------------------------
    def _guard(self, op: str) -> Optional[Dict[str, Any]]:
        check = self._mode.check_active(bump=True)
        if not check.get("active"):
            return {
                "success": False,
                "error": check.get("error", "Autonomous mode inactive"),
                "error_type": check.get("error_type", "autonomous_mode_inactive"),
                "op": op,
            }
        return None

    def _record(
        self,
        op: str,
        args: Dict[str, Any],
        result: Dict[str, Any],
        started_at: float,
        before: Optional[Dict[str, Any]] = None,
        after: Optional[Dict[str, Any]] = None,
    ) -> None:
        audit = self._get_audit()
        if not audit:
            return
        try:
            audit.append(
                op=op,
                args=args,
                result=result,
                before=before,
                after=after,
                duration_ms=(time.time() - started_at) * 1000,
            )
        except Exception as e:  # noqa: BLE001
            logger.debug("audit append failed for op=%s: %s", op, e)

    # ------------------------------------------------------------------
    # save
    # ------------------------------------------------------------------
    def save(self, timeout_seconds: float = 60.0) -> Dict[str, Any]:
        blocked = self._guard("save")
        if blocked:
            return blocked

        started = time.time()
        pending = self._pending.detect()
        file_path = pending.file_full_path
        file_type = pending.file_type or self._guess_file_type(file_path)

        before = {
            "file_full_path": file_path,
            "file_type": file_type,
            "pending_category": pending.category,
        }

        if pending.category == "no_changes":
            result = {
                "success": True,
                "action": "noop",
                "message": "No pending changes to save",
                "pending": pending.to_dict(),
            }
            self._record("save", {}, result, started, before=before)
            return result

        # PBIP live-changes: try TOM SaveChanges first (fast path, no UI).
        if file_type == "pbip" and pending.has_live_tom_changes:
            tom_result = self._tom_save_changes()
            if tom_result.get("success"):
                self._pending.mark_seen()
                result = {
                    "success": True,
                    "action": "tom_save_changes",
                    "pending": pending.to_dict(),
                    **{k: v for k, v in tom_result.items() if k != "success"},
                }
                self._record("save", {}, result, started, before=before)
                return result
            # Fall through to UI automation if TOM save failed.

        # PBIX or TOM-save-failed: UI automation.
        proc = self._processes.find_for_file(file_path) if file_path else None
        if not proc:
            result = {
                "success": False,
                "error": (
                    "Cannot locate PBIDesktop.exe for the current connection " "to drive a UI save."
                ),
                "error_type": "process_not_found",
                "pending": pending.to_dict(),
            }
            self._record("save", {}, result, started, before=before)
            return result

        from core.autonomous.ui_automation import PbiDesktopUIAutomation

        ui = PbiDesktopUIAutomation(save_timeout=timeout_seconds)
        ui_result = ui.save(proc.pid)
        if ui_result.get("success"):
            self._pending.mark_seen()

        result = {
            **ui_result,
            "action": "ui_save",
            "pid": proc.pid,
            "pending": pending.to_dict(),
        }
        self._record("save", {"timeout_seconds": timeout_seconds}, result, started, before=before)
        return result

    # ------------------------------------------------------------------
    # close
    # ------------------------------------------------------------------
    def close(
        self,
        save_first: bool = True,
        grace_seconds: float = 8.0,
    ) -> Dict[str, Any]:
        blocked = self._guard("close")
        if blocked:
            return blocked

        started = time.time()
        pending = self._pending.detect()
        file_path = pending.file_full_path

        before = {
            "file_full_path": file_path,
            "pending_category": pending.category,
        }

        if save_first and pending.category == "live_tom_changes":
            save_result = self.save()
            if not save_result.get("success"):
                out = {
                    "success": False,
                    "error": "Pre-close save failed",
                    "error_type": "pre_close_save_failed",
                    "save_result": save_result,
                }
                self._record("close", {"save_first": save_first}, out, started, before=before)
                return out

        proc = self._processes.find_for_file(file_path) if file_path else None
        if not proc:
            out = {
                "success": False,
                "error": "No PBIDesktop.exe process found to close",
                "error_type": "process_not_found",
                "file": file_path,
            }
            self._record("close", {"save_first": save_first}, out, started, before=before)
            return out

        # Detach our ADOMD connection before tearing down PBIDesktop
        try:
            cm = getattr(self._cs, "connection_manager", None)
            if cm and cm.is_connected():
                cm.disconnect()
        except Exception as e:  # noqa: BLE001
            logger.debug("disconnect before close failed: %s", e)

        kill_result = self._processes.kill(proc.pid, grace_seconds=grace_seconds)
        after = {"process_alive": self._processes.find_for_file(file_path) is not None}
        out = {
            **kill_result,
            "action": "close",
            "file": file_path,
            "pending": pending.to_dict(),
        }
        self._record(
            "close",
            {"save_first": save_first, "grace_seconds": grace_seconds},
            out,
            started,
            before=before,
            after=after,
        )
        return out

    # ------------------------------------------------------------------
    # reopen
    # ------------------------------------------------------------------
    def reopen(
        self,
        file_full_path: Optional[str] = None,
        wait_level: ReadinessLevel = ReadinessLevel.IDENTITY,
        wait_timeout_seconds: float = 180.0,
        reconnect: bool = True,
    ) -> Dict[str, Any]:
        blocked = self._guard("reopen")
        if blocked:
            return blocked

        started = time.time()
        target = file_full_path or self._current_file_path()
        if not target:
            out = {
                "success": False,
                "error": (
                    "No file path available. Pass file_full_path explicitly or "
                    "ensure connection_state knows the PBIP/PBIX path."
                ),
                "error_type": "no_file_path",
            }
            self._record("reopen", {}, out, started)
            return out

        launch = self._processes.launch(target)
        if not launch.get("success"):
            self._record("reopen", {"file": target}, launch, started)
            return launch

        wait_result = self._waiter.wait(
            target,
            target_level=wait_level,
            timeout_seconds=wait_timeout_seconds,
        ).to_dict()

        reconnect_result: Optional[Dict[str, Any]] = None
        if reconnect and wait_result.get("success"):
            reconnect_result = self._reconnect_to(wait_result)

        self._pending.mark_seen()

        out = {
            "success": wait_result.get("success", False)
            and (reconnect_result or {"success": True}).get("success", True),
            "action": "reopen",
            "file": target,
            "launch": launch,
            "wait": wait_result,
            "reconnect": reconnect_result,
        }
        self._record(
            "reopen",
            {
                "file": target,
                "wait_level": int(wait_level),
                "wait_timeout_seconds": wait_timeout_seconds,
                "reconnect": reconnect,
            },
            out,
            started,
        )
        return out

    # ------------------------------------------------------------------
    # wait_ready (standalone primitive)
    # ------------------------------------------------------------------
    def wait_ready(
        self,
        file_full_path: Optional[str] = None,
        level: ReadinessLevel = ReadinessLevel.IDENTITY,
        timeout_seconds: float = 180.0,
    ) -> Dict[str, Any]:
        blocked = self._guard("wait_ready")
        if blocked:
            return blocked

        started = time.time()
        target = file_full_path or self._current_file_path()
        if not target:
            out = {
                "success": False,
                "error": "No file path available",
                "error_type": "no_file_path",
            }
            self._record("wait_ready", {}, out, started)
            return out

        result = self._waiter.wait(
            target,
            target_level=level,
            timeout_seconds=timeout_seconds,
        ).to_dict()
        self._record(
            "wait_ready",
            {"level": int(level), "timeout_seconds": timeout_seconds},
            result,
            started,
        )
        return result

    # ------------------------------------------------------------------
    # validate
    # ------------------------------------------------------------------
    def validate(
        self,
        assertions: List[Dict[str, Any]],
        bypass_cache: bool = True,
    ) -> Dict[str, Any]:
        blocked = self._guard("validate")
        if blocked:
            return blocked

        started = time.time()
        runner = ValidationRunner(self._cs.query_executor)
        result = runner.run(assertions, bypass_cache=bypass_cache)
        self._record(
            "validate",
            {"assertion_count": len(assertions or []), "bypass_cache": bypass_cache},
            {"success": result["success"], "passed": result["passed"], "failed": result["failed"]},
            started,
        )
        return result

    # ------------------------------------------------------------------
    # reload macro
    # ------------------------------------------------------------------
    def reload(
        self,
        save_first: bool = True,
        refresh_tables: Optional[List[str]] = None,
        validate: Optional[List[Dict[str, Any]]] = None,
        wait_level: ReadinessLevel = ReadinessLevel.IDENTITY,
        wait_timeout_seconds: float = 240.0,
    ) -> Dict[str, Any]:
        blocked = self._guard("reload")
        if blocked:
            return blocked

        started = time.time()
        steps: Dict[str, Any] = {}
        file_path = self._current_file_path()

        if save_first:
            steps["save"] = self.save()
            if not steps["save"].get("success"):
                out = {
                    "success": False,
                    "error": "Reload aborted: save failed",
                    "error_type": "reload_save_failed",
                    "steps": steps,
                }
                self._record("reload", {}, out, started)
                return out

        steps["close"] = self.close(save_first=False)
        if not steps["close"].get("success"):
            out = {
                "success": False,
                "error": "Reload aborted: close failed",
                "error_type": "reload_close_failed",
                "steps": steps,
            }
            self._record("reload", {}, out, started)
            return out

        steps["reopen"] = self.reopen(
            file_full_path=file_path,
            wait_level=wait_level,
            wait_timeout_seconds=wait_timeout_seconds,
        )
        if not steps["reopen"].get("success"):
            out = {
                "success": False,
                "error": "Reload aborted: reopen failed",
                "error_type": "reload_reopen_failed",
                "steps": steps,
            }
            self._record("reload", {}, out, started)
            return out

        if refresh_tables:
            steps["refresh"] = self._refresh_tables(refresh_tables)

        if validate:
            steps["validate"] = self.validate(validate)

        all_ok = all((v or {}).get("success", True) for v in steps.values())
        out = {
            "success": all_ok,
            "action": "reload",
            "file": file_path,
            "steps": steps,
        }
        self._record(
            "reload",
            {
                "save_first": save_first,
                "refresh_tables": refresh_tables or [],
                "validate_count": len(validate or []),
                "wait_level": int(wait_level),
            },
            {"success": all_ok},
            started,
        )
        return out

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _current_file_path(self) -> Optional[str]:
        try:
            info = self._cs.get_pbip_info() or {}
        except Exception:
            info = {}
        if info.get("file_full_path"):
            return info["file_full_path"]
        try:
            cm = getattr(self._cs, "connection_manager", None)
            inst = cm.get_instance_info() if cm else None
            if inst:
                return inst.get("file_full_path")
        except Exception:
            pass
        return None

    @staticmethod
    def _guess_file_type(path: Optional[str]) -> Optional[str]:
        if not path:
            return None
        lo = path.lower()
        if lo.endswith(".pbix"):
            return "pbix"
        if lo.endswith(".pbip") or os.path.isdir(path):
            return "pbip"
        return None

    def _tom_save_changes(self) -> Dict[str, Any]:
        """Run Model.SaveChanges() on the current live TOM connection."""
        try:
            cm = getattr(self._cs, "connection_manager", None)
            if not cm or not cm.is_connected() or not cm.connection_string:
                return {
                    "success": False,
                    "error": "Not connected",
                    "error_type": "not_connected",
                }
            from core.infrastructure.dll_paths import load_amo_assemblies

            if not load_amo_assemblies():
                return {
                    "success": False,
                    "error": "AMO assemblies unavailable",
                    "error_type": "amo_unavailable",
                }
            from Microsoft.AnalysisServices.Tabular import Server  # type: ignore

            server = Server()
            try:
                server.Connect(cm.connection_string)
                if server.Databases.Count == 0:
                    return {
                        "success": False,
                        "error": "No databases on server",
                        "error_type": "no_database",
                    }
                db = server.Databases[0]
                model = db.Model
                model.SaveChanges()
                return {"success": True, "message": "TOM SaveChanges committed"}
            finally:
                try:
                    server.Disconnect()
                except Exception:
                    pass
        except Exception as e:  # noqa: BLE001
            return {
                "success": False,
                "error": f"TOM SaveChanges failed: {e}",
                "error_type": "tom_save_failed",
            }

    def _reconnect_to(self, wait_result: Dict[str, Any]) -> Dict[str, Any]:
        """Reconnect the shared ConnectionManager to the freshly-launched port."""
        cm = getattr(self._cs, "connection_manager", None)
        if not cm:
            return {
                "success": False,
                "error": "No connection manager",
                "error_type": "no_connection_manager",
            }
        port = wait_result.get("port")
        try:
            if port:
                return cm.connect_to_port(port)
            return cm.connect()
        except Exception as e:  # noqa: BLE001
            return {
                "success": False,
                "error": f"Reconnect failed: {e}",
                "error_type": "reconnect_failed",
            }

    def _refresh_tables(self, tables: List[str]) -> Dict[str, Any]:
        cs = self._cs
        results: List[Dict[str, Any]] = []
        mgr = getattr(cs, "table_crud_manager", None)
        if mgr is None:
            return {
                "success": False,
                "error": "table_crud_manager not initialized",
                "error_type": "no_table_manager",
            }
        for name in tables:
            try:
                results.append({"table": name, **(mgr.refresh_table(name) or {})})
            except Exception as e:  # noqa: BLE001
                results.append({"table": name, "success": False, "error": str(e)})
        return {
            "success": all(r.get("success", False) for r in results),
            "results": results,
        }
