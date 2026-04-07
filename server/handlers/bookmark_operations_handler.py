"""
Bookmark Operations Handler
CRUD operations for bookmarks plus analysis.

Operations:
- list: List all bookmarks
- create: Create a new bookmark
- rename: Rename a bookmark
- delete: Delete a bookmark
- set_capture: Configure what bookmark captures
- set_affected_visuals: Set which visuals are affected
- analyze: Generate HTML bookmark analysis (existing functionality)
"""
from typing import Dict, Any
import logging
from pathlib import Path

from server.registry import ToolDefinition
from core.utilities.pbip_utils import find_definition_folder

logger = logging.getLogger(__name__)


def handle_bookmark_operations(args: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatch bookmark operations."""
    operation = args.get("operation", "list")
    pbip_path = args.get("pbip_path")

    if not pbip_path:
        return {"success": False, "error": "pbip_path is required"}

    ops = {
        "list": _op_list,
        "create": _op_create,
        "rename": _op_rename,
        "delete": _op_delete,
        "set_capture": _op_set_capture,
        "set_affected_visuals": _op_set_affected_visuals,
        "analyze": _op_analyze,
    }

    handler = ops.get(operation)
    if not handler:
        return {
            "success": False,
            "error": f"Unknown operation: '{operation}'. Valid: {', '.join(sorted(ops.keys()))}",
        }

    return handler(args)


# --- Delegated operation (reuse existing logic) ---


def _op_analyze(args: Dict[str, Any]) -> Dict[str, Any]:
    """Generate HTML bookmark analysis — delegates to existing bookmark_theme_handler."""
    from server.handlers.bookmark_theme_handler import handle_analyze_bookmarks

    return handle_analyze_bookmarks(args)


# --- New operations (dispatch to domain engine) ---


def _op_list(args: Dict[str, Any]) -> Dict[str, Any]:
    """List all bookmarks."""
    from core.pbip.bookmark_engine import list_bookmarks

    definition_path = find_definition_folder(args["pbip_path"])
    if not definition_path:
        return {"success": False, "error": f"Could not find definition folder in: {args['pbip_path']}"}

    return list_bookmarks(definition_path=definition_path)


def _op_create(args: Dict[str, Any]) -> Dict[str, Any]:
    """Create a new bookmark."""
    from core.pbip.bookmark_engine import create_bookmark

    display_name = args.get("display_name")
    if not display_name:
        return {"success": False, "error": "display_name is required for create"}

    definition_path = find_definition_folder(args["pbip_path"])
    if not definition_path:
        return {"success": False, "error": f"Could not find definition folder in: {args['pbip_path']}"}

    return create_bookmark(
        definition_path=definition_path,
        display_name=display_name,
        page_name=args.get("page_name"),
    )


def _op_rename(args: Dict[str, Any]) -> Dict[str, Any]:
    """Rename a bookmark."""
    from core.pbip.bookmark_engine import rename_bookmark

    bookmark_id = args.get("bookmark_id")
    new_name = args.get("new_name")
    if not bookmark_id:
        return {"success": False, "error": "bookmark_id is required for rename"}
    if not new_name:
        return {"success": False, "error": "new_name is required for rename"}

    definition_path = find_definition_folder(args["pbip_path"])
    if not definition_path:
        return {"success": False, "error": f"Could not find definition folder in: {args['pbip_path']}"}

    return rename_bookmark(
        definition_path=definition_path,
        bookmark_id=bookmark_id,
        new_name=new_name,
    )


def _op_delete(args: Dict[str, Any]) -> Dict[str, Any]:
    """Delete a bookmark."""
    from core.pbip.bookmark_engine import delete_bookmark

    bookmark_id = args.get("bookmark_id")
    if not bookmark_id:
        return {"success": False, "error": "bookmark_id is required for delete"}

    definition_path = find_definition_folder(args["pbip_path"])
    if not definition_path:
        return {"success": False, "error": f"Could not find definition folder in: {args['pbip_path']}"}

    return delete_bookmark(
        definition_path=definition_path,
        bookmark_id=bookmark_id,
    )


def _op_set_capture(args: Dict[str, Any]) -> Dict[str, Any]:
    """Configure what a bookmark captures."""
    from core.pbip.bookmark_engine import set_bookmark_capture

    bookmark_id = args.get("bookmark_id")
    if not bookmark_id:
        return {"success": False, "error": "bookmark_id is required for set_capture"}

    definition_path = find_definition_folder(args["pbip_path"])
    if not definition_path:
        return {"success": False, "error": f"Could not find definition folder in: {args['pbip_path']}"}

    return set_bookmark_capture(
        definition_path=definition_path,
        bookmark_id=bookmark_id,
        capture_data=args.get("capture_data"),
        capture_display=args.get("capture_display"),
        capture_current_page=args.get("capture_current_page"),
    )


def _op_set_affected_visuals(args: Dict[str, Any]) -> Dict[str, Any]:
    """Set which visuals are affected by a bookmark."""
    from core.pbip.bookmark_engine import set_affected_visuals

    bookmark_id = args.get("bookmark_id")
    if not bookmark_id:
        return {"success": False, "error": "bookmark_id is required for set_affected_visuals"}

    visual_ids = args.get("visual_ids")
    all_visuals = args.get("all_visuals", False)

    if not visual_ids and not all_visuals:
        return {"success": False, "error": "visual_ids or all_visuals=true is required"}

    definition_path = find_definition_folder(args["pbip_path"])
    if not definition_path:
        return {"success": False, "error": f"Could not find definition folder in: {args['pbip_path']}"}

    return set_affected_visuals(
        definition_path=definition_path,
        bookmark_id=bookmark_id,
        visual_ids=visual_ids,
        all_visuals=all_visuals,
    )


# --- Registration ---


def register_bookmark_operations_handler(registry):
    """Register the bookmark operations tool."""
    from server.tool_schemas import TOOL_SCHEMAS

    registry.register(
        ToolDefinition(
            name="07_Bookmark_Operations",
            description=(
                "Bookmark operations: list, create, rename, delete, "
                "set_capture, set_affected_visuals, analyze (HTML)."
            ),
            handler=handle_bookmark_operations,
            input_schema=TOOL_SCHEMAS.get("bookmark_operations", {}),
            category="pbip",
            sort_order=76,
            annotations={"readOnlyHint": False, "destructiveHint": True},
        )
    )

    logger.info("Registered bookmark_operations handler")
