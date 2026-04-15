"""
Autonomous Workflow Handler

Single MCP tool `12_Autonomous_Workflow` that exposes the autonomous
lifecycle primitives (mode gate, save/close/reopen/reload, wait_ready,
validate, audit_log) behind one operation dispatcher.

All destructive operations (save/close/reopen/reload) are gated on the
session-scoped mode flag. The flag starts OFF at MCP startup; the user must
explicitly call `enter_mode` before any destructive op will run.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from core.autonomous import (
    AuditLog,
    LifecycleManager,
    ReadinessLevel,
    get_mode_manager,
)
from core.infrastructure.connection_state import connection_state
from server.registry import ToolDefinition

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------
_VALID_OPS = {
    "enter_mode",
    "exit_mode",
    "status",
    "save",
    "close",
    "reopen",
    "reload",
    "wait_ready",
    "validate",
    "audit_log",
}


def handle_autonomous_workflow(args: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatch autonomous workflow operations."""
    op = str(args.get("operation") or "").strip().lower()
    if not op:
        return {
            "success": False,
            "error": "operation is required",
            "valid_operations": sorted(_VALID_OPS),
        }
    if op not in _VALID_OPS:
        return {
            "success": False,
            "error": f"Unknown operation '{op}'",
            "valid_operations": sorted(_VALID_OPS),
        }

    try:
        if op == "enter_mode":
            return _op_enter_mode(args)
        if op == "exit_mode":
            return _op_exit_mode(args)
        if op == "status":
            return _op_status(args)
        if op == "audit_log":
            return _op_audit_log(args)

        # All remaining ops require a LifecycleManager + live connection_state
        lcm = LifecycleManager(connection_state)
        if op == "save":
            return lcm.save(
                timeout_seconds=float(args.get("timeout_seconds", 60.0)),
            )
        if op == "close":
            return lcm.close(
                save_first=bool(args.get("save_first", True)),
                grace_seconds=float(args.get("grace_seconds", 8.0)),
            )
        if op == "reopen":
            return lcm.reopen(
                file_full_path=args.get("file_full_path"),
                wait_level=_parse_level(args.get("wait_level")),
                wait_timeout_seconds=float(args.get("wait_timeout_seconds", 180.0)),
                reconnect=bool(args.get("reconnect", True)),
            )
        if op == "reload":
            return lcm.reload(
                save_first=bool(args.get("save_first", True)),
                refresh_tables=args.get("refresh_tables") or None,
                validate=args.get("validate") or None,
                wait_level=_parse_level(args.get("wait_level")),
                wait_timeout_seconds=float(args.get("wait_timeout_seconds", 240.0)),
            )
        if op == "wait_ready":
            return lcm.wait_ready(
                file_full_path=args.get("file_full_path"),
                level=_parse_level(args.get("level")),
                timeout_seconds=float(args.get("timeout_seconds", 180.0)),
            )
        if op == "validate":
            return lcm.validate(
                assertions=args.get("assertions") or [],
                bypass_cache=bool(args.get("bypass_cache", True)),
            )
    except Exception as e:  # noqa: BLE001
        logger.exception("Autonomous op '%s' raised", op)
        return {
            "success": False,
            "error": f"{type(e).__name__}: {e}",
            "error_type": "handler_exception",
            "operation": op,
        }

    return {"success": False, "error": "unreachable", "operation": op}


# ---------------------------------------------------------------------------
# Individual ops (mode + audit — no lifecycle needed)
# ---------------------------------------------------------------------------
def _op_enter_mode(args: Dict[str, Any]) -> Dict[str, Any]:
    mgr = get_mode_manager()
    return mgr.enter_mode(
        idle_timeout_minutes=args.get("idle_timeout_minutes"),
        max_duration_minutes=args.get("max_duration_minutes"),
        log_path=args.get("log_path"),
        reason=str(args.get("reason") or ""),
        extras=args.get("extras") or None,
    )


def _op_exit_mode(args: Dict[str, Any]) -> Dict[str, Any]:
    mgr = get_mode_manager()
    reason = str(args.get("reason") or "manual")
    exit_result = mgr.exit_mode(reason=reason)

    # Emit markdown summary if we have an audit log for this session.
    summary_path: Optional[str] = None
    session_id = exit_result.get("session_id")
    if session_id:
        try:
            audit = AuditLog(session_id, log_path=exit_result.get("log_path"))
            summary_path = audit.emit_summary(exit_reason=reason)
        except Exception as e:  # noqa: BLE001
            logger.debug("Summary emit failed: %s", e)

    exit_result["summary_path"] = summary_path
    return exit_result


def _op_status(args: Dict[str, Any]) -> Dict[str, Any]:
    mgr = get_mode_manager()
    status = mgr.status()
    status["success"] = True
    return status


def _op_audit_log(args: Dict[str, Any]) -> Dict[str, Any]:
    action = str(args.get("action") or "read").lower()
    session_id = args.get("session_id") or get_mode_manager().session_id()
    if not session_id:
        return {
            "success": False,
            "error": "No active session_id — pass session_id explicitly",
            "error_type": "no_session",
        }
    log_path = args.get("log_path") or get_mode_manager().log_path()
    audit = AuditLog(session_id, log_path=log_path)

    if action == "read":
        limit = args.get("limit")
        try:
            limit = int(limit) if limit is not None else None
        except (TypeError, ValueError):
            limit = None
        entries = audit.read_entries(limit=limit)
        return {
            "success": True,
            "session_id": session_id,
            "jsonl_path": audit.jsonl_path,
            "entry_count": len(entries),
            "entries": entries,
        }
    if action == "summary":
        path = audit.emit_summary(
            exit_reason=str(args.get("reason") or "manual"),
        )
        return {
            "success": path is not None,
            "session_id": session_id,
            "summary_path": path,
            "error": None if path else "Summary emit failed",
        }
    return {
        "success": False,
        "error": f"Unknown audit_log action '{action}'",
        "valid_actions": ["read", "summary"],
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _parse_level(value: Any) -> ReadinessLevel:
    """Accept int (1-5) or name ('process'..'refresh_idle'). Default IDENTITY."""
    if value is None:
        return ReadinessLevel.IDENTITY
    if isinstance(value, int) or (isinstance(value, str) and value.isdigit()):
        ival = int(value)
        try:
            return ReadinessLevel(ival)
        except ValueError:
            return ReadinessLevel.IDENTITY
    if isinstance(value, str):
        name = value.strip().upper()
        for lvl in ReadinessLevel:
            if lvl.name == name:
                return lvl
    return ReadinessLevel.IDENTITY


# ---------------------------------------------------------------------------
# Tool schema + registration
# ---------------------------------------------------------------------------
AUTONOMOUS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "operation": {
            "type": "string",
            "enum": sorted(_VALID_OPS),
            "description": (
                "enter_mode/exit_mode/status toggle the session flag. "
                "save/close/reopen/reload/wait_ready/validate are gated on "
                "the flag being active. audit_log reads or summarizes the log."
            ),
        },
        # enter_mode
        "idle_timeout_minutes": {"type": "integer", "minimum": 1},
        "max_duration_minutes": {"type": "integer", "minimum": 1, "maximum": 240},
        "log_path": {"type": "string"},
        "reason": {"type": "string"},
        "extras": {"type": "object"},
        # save / close / reopen / wait_ready
        "timeout_seconds": {"type": "number", "minimum": 1},
        "save_first": {"type": "boolean"},
        "grace_seconds": {"type": "number", "minimum": 1},
        "file_full_path": {"type": "string"},
        "wait_level": {
            "oneOf": [
                {"type": "integer", "minimum": 1, "maximum": 5},
                {
                    "type": "string",
                    "enum": ["process", "port", "adomd", "identity", "refresh_idle"],
                },
            ]
        },
        "level": {
            "oneOf": [
                {"type": "integer", "minimum": 1, "maximum": 5},
                {
                    "type": "string",
                    "enum": ["process", "port", "adomd", "identity", "refresh_idle"],
                },
            ]
        },
        "wait_timeout_seconds": {"type": "number", "minimum": 1},
        "reconnect": {"type": "boolean"},
        # reload
        "refresh_tables": {"type": "array", "items": {"type": "string"}},
        # validate
        "assertions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "dax": {"type": "string"},
                    "op": {
                        "type": "string",
                        "enum": [
                            "eq",
                            "ne",
                            "lt",
                            "lte",
                            "gt",
                            "gte",
                            "in",
                            "not_null",
                            "truthy",
                        ],
                    },
                    "expected": {},
                },
                "required": ["dax"],
            },
        },
        "bypass_cache": {"type": "boolean"},
        # audit_log
        "action": {"type": "string", "enum": ["read", "summary"]},
        "session_id": {"type": "string"},
        "limit": {"type": "integer", "minimum": 1},
    },
    "required": ["operation"],
}


def register_autonomous_handler(registry):
    """Register the autonomous workflow tool."""
    registry.register(
        ToolDefinition(
            name="12_Autonomous_Workflow",
            description=(
                "Closed-loop Power BI Desktop lifecycle: save/close/reopen/reload "
                "gated on an explicit session flag. Operations: enter_mode, "
                "exit_mode, status, save, close, reopen, reload, wait_ready, "
                "validate, audit_log. Always call enter_mode before destructive ops."
            ),
            handler=handle_autonomous_workflow,
            input_schema=AUTONOMOUS_SCHEMA,
            category="autonomous",
            sort_order=1200,
            annotations={
                "readOnlyHint": False,
                "destructiveHint": True,
                "idempotentHint": False,
                "openWorldHint": True,
            },
        )
    )
