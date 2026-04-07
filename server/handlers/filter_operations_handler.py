"""
INTERNAL HELPER — Not a registered MCP tool.
Provides helper functions consumed by active handlers.

Filter CRUD operations for report, page, and visual levels;
consumed by page_operations_handler.py and visual_operations_handler.py.
"""
from typing import Dict, Any
import logging
from pathlib import Path

from core.utilities.pbip_utils import find_definition_folder

logger = logging.getLogger(__name__)


def handle_filter_operations(args: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatch filter CRUD operations."""
    operation = args.get("operation", "list")
    pbip_path = args.get("pbip_path")

    if not pbip_path:
        return {"success": False, "error": "pbip_path is required"}

    ops = {
        "list": _op_list,
        "add": _op_add,
        "set": _op_set,
        "clear": _op_clear,
        "hide": _op_hide,
        "unhide": _op_unhide,
        "lock": _op_lock,
        "unlock": _op_unlock,
    }

    handler = ops.get(operation)
    if not handler:
        return {
            "success": False,
            "error": f"Unknown operation: '{operation}'. Valid: {', '.join(sorted(ops.keys()))}",
        }

    return handler(args)


# --- Operations (all dispatch to filter_engine) ---


def _op_list(args: Dict[str, Any]) -> Dict[str, Any]:
    """List filters at specified level."""
    from core.pbip.filter_engine import list_filters

    definition_path = find_definition_folder(args["pbip_path"])
    if not definition_path:
        return {"success": False, "error": f"Could not find definition folder in: {args['pbip_path']}"}

    return list_filters(
        definition_path=definition_path,
        level=args.get("level", "all"),
        page_name=args.get("page_name"),
        visual_name=args.get("visual_name"),
    )


def _op_add(args: Dict[str, Any]) -> Dict[str, Any]:
    """Add a new filter."""
    from core.pbip.filter_engine import add_filter

    table = args.get("table")
    field = args.get("field")
    if not table or not field:
        return {"success": False, "error": "table and field are required for add"}

    level = args.get("level", "page")
    if level == "all":
        return {"success": False, "error": "level must be 'report', 'page', or 'visual' for add (not 'all')"}

    definition_path = find_definition_folder(args["pbip_path"])
    if not definition_path:
        return {"success": False, "error": f"Could not find definition folder in: {args['pbip_path']}"}

    return add_filter(
        definition_path=definition_path,
        level=level,
        table=table,
        field=field,
        filter_type=args.get("filter_type", "Categorical"),
        values=args.get("values"),
        page_name=args.get("page_name"),
        visual_name=args.get("visual_name"),
        operator=args.get("operator"),
        by_table=args.get("by_table"),
        by_field=args.get("by_field"),
    )


def _op_set(args: Dict[str, Any]) -> Dict[str, Any]:
    """Update filter values."""
    from core.pbip.filter_engine import set_filter_values

    filter_name = args.get("filter_name")
    if not filter_name:
        return {"success": False, "error": "filter_name is required for set"}

    values = args.get("values")
    if values is None:
        return {"success": False, "error": "values is required for set"}

    definition_path = find_definition_folder(args["pbip_path"])
    if not definition_path:
        return {"success": False, "error": f"Could not find definition folder in: {args['pbip_path']}"}

    return set_filter_values(
        definition_path=definition_path,
        filter_name=filter_name,
        values=values,
        level=args.get("level"),
        page_name=args.get("page_name"),
    )


def _op_clear(args: Dict[str, Any]) -> Dict[str, Any]:
    """Remove all filters at the specified level."""
    from core.pbip.filter_engine import clear_filters

    level = args.get("level", "page")
    if level == "all":
        return {"success": False, "error": "level must be 'report', 'page', or 'visual' for clear (not 'all')"}

    definition_path = find_definition_folder(args["pbip_path"])
    if not definition_path:
        return {"success": False, "error": f"Could not find definition folder in: {args['pbip_path']}"}

    return clear_filters(
        definition_path=definition_path,
        level=level,
        page_name=args.get("page_name"),
        visual_name=args.get("visual_name"),
    )


def _op_hide(args: Dict[str, Any]) -> Dict[str, Any]:
    """Hide filter in the filter pane."""
    from core.pbip.filter_engine import set_filter_visibility

    filter_name = args.get("filter_name")
    if not filter_name:
        return {"success": False, "error": "filter_name is required for hide"}

    definition_path = find_definition_folder(args["pbip_path"])
    if not definition_path:
        return {"success": False, "error": f"Could not find definition folder in: {args['pbip_path']}"}

    return set_filter_visibility(
        definition_path=definition_path,
        filter_name=filter_name,
        hidden=True,
        level=args.get("level"),
        page_name=args.get("page_name"),
    )


def _op_unhide(args: Dict[str, Any]) -> Dict[str, Any]:
    """Show filter in the filter pane."""
    from core.pbip.filter_engine import set_filter_visibility

    filter_name = args.get("filter_name")
    if not filter_name:
        return {"success": False, "error": "filter_name is required for unhide"}

    definition_path = find_definition_folder(args["pbip_path"])
    if not definition_path:
        return {"success": False, "error": f"Could not find definition folder in: {args['pbip_path']}"}

    return set_filter_visibility(
        definition_path=definition_path,
        filter_name=filter_name,
        hidden=False,
        level=args.get("level"),
        page_name=args.get("page_name"),
    )


def _op_lock(args: Dict[str, Any]) -> Dict[str, Any]:
    """Lock filter (prevent user changes)."""
    from core.pbip.filter_engine import set_filter_lock

    filter_name = args.get("filter_name")
    if not filter_name:
        return {"success": False, "error": "filter_name is required for lock"}

    definition_path = find_definition_folder(args["pbip_path"])
    if not definition_path:
        return {"success": False, "error": f"Could not find definition folder in: {args['pbip_path']}"}

    return set_filter_lock(
        definition_path=definition_path,
        filter_name=filter_name,
        locked=True,
        level=args.get("level"),
        page_name=args.get("page_name"),
    )


def _op_unlock(args: Dict[str, Any]) -> Dict[str, Any]:
    """Unlock filter."""
    from core.pbip.filter_engine import set_filter_lock

    filter_name = args.get("filter_name")
    if not filter_name:
        return {"success": False, "error": "filter_name is required for unlock"}

    definition_path = find_definition_folder(args["pbip_path"])
    if not definition_path:
        return {"success": False, "error": f"Could not find definition folder in: {args['pbip_path']}"}

    return set_filter_lock(
        definition_path=definition_path,
        filter_name=filter_name,
        locked=False,
        level=args.get("level"),
        page_name=args.get("page_name"),
    )


