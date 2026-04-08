"""
Report Operations Handler
Consolidated tool for report-level operations.

Operations:
- info: Get report structure (pages, visuals, filters) — from original report_info_handler
- measure_usage: Find measures used per page — from original report_info_handler
- rename: Rename report folder and .platform file
- rebind: Rebind to different semantic model
- backup: Create timestamped backup
- restore: Restore from backup
- discover_schema: Discover visual type properties and data roles
- manage_extension_measures: CRUD for report-level extension measures
"""
from typing import Dict, Any
import logging
from pathlib import Path

from server.registry import ToolDefinition
from core.utilities.pbip_utils import find_definition_folder

logger = logging.getLogger(__name__)


def handle_report_operations(args: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatch report-level operations."""
    operation = args.get("operation", "info")
    pbip_path = args.get("pbip_path")

    if not pbip_path:
        return {"success": False, "error": "pbip_path is required"}

    ops = {
        "info": _op_info,
        "measure_usage": _op_measure_usage,
        "rename": _op_rename,
        "rebind": _op_rebind,
        "backup": _op_backup,
        "restore": _op_restore,
        "discover_schema": _op_discover_schema,
        "manage_extension_measures": _op_manage_extension_measures,
    }

    handler = ops.get(operation)
    if not handler:
        return {
            "success": False,
            "error": f"Unknown operation: '{operation}'. Valid: {', '.join(sorted(ops.keys()))}",
        }

    return handler(args)


# --- Delegated operations (reuse existing logic) ---


def _op_info(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get report structure — delegates to existing report_info_handler."""
    from server.handlers.report_info_handler import handle_report_info

    return handle_report_info(args)


def _op_measure_usage(args: Dict[str, Any]) -> Dict[str, Any]:
    """Find measures used per page — delegates to existing report_info_handler."""
    from server.handlers.report_info_handler import handle_report_measure_usage

    return handle_report_measure_usage(args)


# --- New operations (dispatch to domain engines) ---


def _op_rename(args: Dict[str, Any]) -> Dict[str, Any]:
    """Rename report folder and .platform file."""
    from core.pbip.report_operations_engine import rename_report

    new_name = args.get("new_name")
    if not new_name:
        return {"success": False, "error": "new_name is required for rename"}

    return rename_report(
        pbip_path=args["pbip_path"],
        new_name=new_name,
    )


def _op_rebind(args: Dict[str, Any]) -> Dict[str, Any]:
    """Rebind report to a different semantic model."""
    from core.pbip.report_operations_engine import rebind_report

    model_path = args.get("model_path")
    model_id = args.get("model_id")
    if not model_path and not model_id:
        return {"success": False, "error": "model_path or model_id is required for rebind"}

    definition_path = find_definition_folder(args["pbip_path"])
    if not definition_path:
        return {"success": False, "error": f"Could not find definition folder in: {args['pbip_path']}"}

    return rebind_report(
        definition_path=definition_path,
        model_path=model_path,
        model_id=model_id,
    )


def _op_backup(args: Dict[str, Any]) -> Dict[str, Any]:
    """Create timestamped backup of the report."""
    from core.pbip.report_operations_engine import backup_report
    from server.handlers.bookmark_theme_handler import _find_report_folder

    try:
        report_path = Path(_find_report_folder(args["pbip_path"]))
    except FileNotFoundError as e:
        return {"success": False, "error": str(e)}

    return backup_report(
        report_path=report_path,
        message=args.get("message"),
    )


def _op_restore(args: Dict[str, Any]) -> Dict[str, Any]:
    """Restore report from a backup."""
    from core.pbip.report_operations_engine import restore_report
    from server.handlers.bookmark_theme_handler import _find_report_folder

    backup_path = args.get("backup_path")
    if not backup_path:
        return {"success": False, "error": "backup_path is required for restore"}

    try:
        report_path = Path(_find_report_folder(args["pbip_path"]))
    except FileNotFoundError as e:
        return {"success": False, "error": str(e)}

    return restore_report(
        report_path=report_path,
        backup_path=backup_path,
    )


def _op_discover_schema(args: Dict[str, Any]) -> Dict[str, Any]:
    """Discover visual type properties and data roles."""
    from core.pbip.report_operations_engine import discover_schema

    visual_type = args.get("visual_type")
    if not visual_type:
        return {"success": False, "error": "visual_type is required for discover_schema"}

    definition_path = find_definition_folder(args["pbip_path"])
    if not definition_path:
        return {"success": False, "error": f"Could not find definition folder in: {args['pbip_path']}"}

    return discover_schema(
        definition_path=definition_path,
        visual_type=visual_type,
    )


def _op_manage_extension_measures(args: Dict[str, Any]) -> Dict[str, Any]:
    """CRUD for report-level extension measures."""
    from core.pbip.extension_measures_engine import (
        list_measures, add_measure, update_measure, delete_measure,
    )

    sub_operation = args.get("sub_operation")
    if not sub_operation:
        return {"success": False, "error": "sub_operation is required (list, add, update, delete)"}

    definition_path = find_definition_folder(args["pbip_path"])
    if not definition_path:
        return {"success": False, "error": f"Could not find definition folder in: {args['pbip_path']}"}

    if sub_operation == "list":
        return list_measures(definition_path=definition_path)
    elif sub_operation == "add":
        measure_name = args.get("measure_name")
        expression = args.get("expression")
        if not measure_name or not expression:
            return {"success": False, "error": "measure_name and expression are required for add"}
        return add_measure(
            definition_path=definition_path,
            name=measure_name,
            expression=expression,
            table_ref=args.get("table_ref"),
            data_type=args.get("data_type", "double"),
            format_string=args.get("format_string"),
            description=args.get("description"),
        )
    elif sub_operation == "update":
        measure_name = args.get("measure_name")
        if not measure_name:
            return {"success": False, "error": "measure_name is required for update"}
        return update_measure(
            definition_path=definition_path,
            name=measure_name,
            expression=args.get("expression"),
            data_type=args.get("data_type"),
            format_string=args.get("format_string"),
            description=args.get("description"),
        )
    elif sub_operation == "delete":
        measure_name = args.get("measure_name")
        if not measure_name:
            return {"success": False, "error": "measure_name is required for delete"}
        return delete_measure(
            definition_path=definition_path,
            name=measure_name,
        )
    else:
        return {"success": False, "error": f"Unknown sub_operation: '{sub_operation}'. Valid: list, add, update, delete"}


# --- Registration ---


def register_report_operations_handler(registry):
    """Register the report operations tool."""
    from server.tool_schemas import TOOL_SCHEMAS

    registry.register(
        ToolDefinition(
            name="07_Report_Operations",
            description=(
                "Report operations: info, measure_usage, rename, rebind, "
                "backup, restore, discover_schema, manage_extension_measures."
            ),
            handler=handle_report_operations,
            input_schema=TOOL_SCHEMAS.get("report_operations", {}),
            category="pbip",
            sort_order=71,
            annotations={
                "readOnlyHint": False,
                "destructiveHint": False,
                "idempotentHint": False,
                "openWorldHint": True,
            },
        )
    )

    logger.info("Registered report_operations handler")
