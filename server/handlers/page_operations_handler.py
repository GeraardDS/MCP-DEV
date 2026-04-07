"""
Page Operations Handler
Consolidated tool for page-level operations.

Operations:
- list: List pages with display names and dimensions
- create: Create new empty page (from authoring_handler)
- clone: Clone page with all visuals (from authoring_handler)
- delete: Delete page (from authoring_handler)
- reorder: Reorder pages
- resize: Resize page canvas
- set_display: Set display option (FitToPage/FitToWidth/ActualSize)
- set_background: Set page background color/transparency
- set_wallpaper: Set page wallpaper (outspace pane)
- set_drillthrough: Configure drillthrough filters
- set_tooltip: Configure as tooltip page
- hide: Hide page
- show: Show page
- set_interaction: Set interaction between two visuals (from slicer_handler)
- bulk_set_interactions: Bulk set interactions (from slicer_handler)
- list_interactions: List visual interactions on a page (from slicer_handler)
- list_filters: List filters at report/page/visual level (from filter_operations_handler)
- add_filter: Add a new filter (from filter_operations_handler)
- set_filter: Update filter values (from filter_operations_handler)
- clear_filters: Remove all filters at level (from filter_operations_handler)
- hide_filter: Hide filter in filter pane (from filter_operations_handler)
- unhide_filter: Show filter in filter pane (from filter_operations_handler)
- lock_filter: Lock filter (from filter_operations_handler)
- unlock_filter: Unlock filter (from filter_operations_handler)
"""
from typing import Dict, Any, List
import logging
from pathlib import Path

from server.registry import ToolDefinition
from core.utilities.pbip_utils import (
    find_definition_folder,
    load_json_file,
    get_page_display_name,
)

logger = logging.getLogger(__name__)


def handle_page_operations(args: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatch page-level operations."""
    operation = args.get("operation", "list")
    pbip_path = args.get("pbip_path")

    if not pbip_path:
        return {"success": False, "error": "pbip_path is required"}

    ops = {
        "list": _op_list,
        "create": _op_create,
        "clone": _op_clone,
        "delete": _op_delete,
        "reorder": _op_reorder,
        "resize": _op_resize,
        "set_display": _op_set_display,
        "set_background": _op_set_background,
        "set_wallpaper": _op_set_wallpaper,
        "set_drillthrough": _op_set_drillthrough,
        "set_tooltip": _op_set_tooltip,
        "hide": _op_hide,
        "show": _op_show,
        "set_interaction": _op_set_interaction,
        "bulk_set_interactions": _op_bulk_set_interactions,
        "list_interactions": _op_list_interactions,
        # Filter operations (absorbed from filter_operations_handler)
        "list_filters": _op_list_filters,
        "add_filter": _op_add_filter,
        "set_filter": _op_set_filter,
        "clear_filters": _op_clear_filters,
        "hide_filter": _op_hide_filter,
        "unhide_filter": _op_unhide_filter,
        "lock_filter": _op_lock_filter,
        "unlock_filter": _op_unlock_filter,
    }

    handler = ops.get(operation)
    if not handler:
        return {
            "success": False,
            "error": f"Unknown operation: '{operation}'. Valid: {', '.join(sorted(ops.keys()))}",
        }

    return handler(args)


# --- List operation (new, lightweight) ---


def _op_list(args: Dict[str, Any]) -> Dict[str, Any]:
    """List pages with display names and dimensions."""
    definition_path = find_definition_folder(args["pbip_path"])
    if not definition_path:
        return {"success": False, "error": f"Could not find definition folder in: {args['pbip_path']}"}

    pages_path = definition_path / "pages"
    if not pages_path.exists():
        return {"success": False, "error": "No pages folder found"}

    page_filter = args.get("page_name")
    summary_only = args.get("summary_only", True)
    pages: List[Dict] = []

    for page_folder in sorted(pages_path.iterdir()):
        if not page_folder.is_dir():
            continue

        page_json_path = page_folder / "page.json"
        if not page_json_path.exists():
            continue

        page_data = load_json_file(page_json_path)
        if not page_data:
            continue

        display_name = page_data.get("displayName", page_folder.name)

        # Apply page name filter
        if page_filter and page_filter.lower() not in display_name.lower():
            continue

        page_info: Dict[str, Any] = {
            "page_id": page_folder.name,
            "display_name": display_name,
            "width": page_data.get("width", 1280),
            "height": page_data.get("height", 720),
        }

        annotations = page_data.get("annotations", [])
        if annotations:
            page_info["annotations"] = annotations

        if not summary_only:
            page_info["display_option"] = page_data.get("displayOption", "")
            page_info["is_hidden"] = page_data.get("visibility", 0) == 1
            page_info["background"] = page_data.get("background", {})
            page_info["wallpaper"] = page_data.get("wallpaper", {})

            # Count visuals
            visuals_path = page_folder / "visuals"
            visual_count = 0
            if visuals_path.exists():
                visual_count = sum(
                    1 for v in visuals_path.iterdir()
                    if v.is_dir() and (v / "visual.json").exists()
                )
            page_info["visual_count"] = visual_count

        pages.append(page_info)

    # Sort by display name
    pages.sort(key=lambda p: p.get("display_name", ""))

    return {
        "success": True,
        "pages": pages,
        "count": len(pages),
    }


# --- Delegated operations from authoring_handler ---


def _op_create(args: Dict[str, Any]) -> Dict[str, Any]:
    """Create new empty page — delegates to authoring_handler."""
    from server.handlers.authoring_handler import _op_create_page

    pbip_path = args["pbip_path"]
    # Map page_name -> page_name (authoring expects this)
    return _op_create_page(args, pbip_path)


def _op_clone(args: Dict[str, Any]) -> Dict[str, Any]:
    """Clone page with all visuals — delegates to authoring_handler."""
    from server.handlers.authoring_handler import _op_clone_page

    pbip_path = args["pbip_path"]
    return _op_clone_page(args, pbip_path)


def _op_delete(args: Dict[str, Any]) -> Dict[str, Any]:
    """Delete page — delegates to authoring_handler."""
    from server.handlers.authoring_handler import _op_delete_page

    pbip_path = args["pbip_path"]
    return _op_delete_page(args, pbip_path)


# --- Delegated operations from slicer_operations_handler ---


def _op_set_interaction(args: Dict[str, Any]) -> Dict[str, Any]:
    """Set interaction between two visuals — delegates to slicer_operations_handler."""
    from server.handlers.slicer_operations_handler import _op_set_interaction as _slicer_set_interaction

    definition_path = find_definition_folder(args["pbip_path"])
    if not definition_path:
        return {"success": False, "error": f"Could not find definition folder in: {args['pbip_path']}"}

    return _slicer_set_interaction(args, definition_path)


def _op_bulk_set_interactions(args: Dict[str, Any]) -> Dict[str, Any]:
    """Bulk set interactions — delegates to slicer_operations_handler."""
    from server.handlers.slicer_operations_handler import (
        _op_bulk_set_interactions as _slicer_bulk_set,
    )

    definition_path = find_definition_folder(args["pbip_path"])
    if not definition_path:
        return {"success": False, "error": f"Could not find definition folder in: {args['pbip_path']}"}

    return _slicer_bulk_set(args, definition_path)


def _op_list_interactions(args: Dict[str, Any]) -> Dict[str, Any]:
    """List visual interactions on a page — delegates to slicer_operations_handler."""
    from server.handlers.slicer_operations_handler import (
        _op_list_interactions as _slicer_list_interactions,
    )

    definition_path = find_definition_folder(args["pbip_path"])
    if not definition_path:
        return {"success": False, "error": f"Could not find definition folder in: {args['pbip_path']}"}

    return _slicer_list_interactions(args, definition_path)


# --- New operations (dispatch to domain engine) ---


def _op_reorder(args: Dict[str, Any]) -> Dict[str, Any]:
    """Reorder pages."""
    from core.pbip.page_operations_engine import reorder_pages

    page_order = args.get("page_order")
    if not page_order:
        return {"success": False, "error": "page_order is required (array of page IDs/names)"}

    definition_path = find_definition_folder(args["pbip_path"])
    if not definition_path:
        return {"success": False, "error": f"Could not find definition folder in: {args['pbip_path']}"}

    return reorder_pages(
        definition_path=definition_path,
        page_order=page_order,
    )


def _op_resize(args: Dict[str, Any]) -> Dict[str, Any]:
    """Resize page canvas."""
    from core.pbip.page_operations_engine import resize_page

    page_name = args.get("page_name") or args.get("page_id")
    if not page_name:
        return {"success": False, "error": "page_name or page_id is required"}

    width = args.get("width")
    height = args.get("height")
    if not width and not height:
        return {"success": False, "error": "width and/or height is required"}

    definition_path = find_definition_folder(args["pbip_path"])
    if not definition_path:
        return {"success": False, "error": f"Could not find definition folder in: {args['pbip_path']}"}

    return resize_page(
        definition_path=definition_path,
        page_name=page_name,
        width=width,
        height=height,
    )


def _op_set_display(args: Dict[str, Any]) -> Dict[str, Any]:
    """Set display option (FitToPage/FitToWidth/ActualSize)."""
    from core.pbip.page_operations_engine import set_display_options

    page_name = args.get("page_name") or args.get("page_id")
    if not page_name:
        return {"success": False, "error": "page_name or page_id is required"}

    display_option = args.get("display_option")
    if not display_option:
        return {"success": False, "error": "display_option is required (FitToPage, FitToWidth, ActualSize)"}

    definition_path = find_definition_folder(args["pbip_path"])
    if not definition_path:
        return {"success": False, "error": f"Could not find definition folder in: {args['pbip_path']}"}

    return set_display_options(
        definition_path=definition_path,
        page_name=page_name,
        display_option=display_option,
    )


def _op_set_background(args: Dict[str, Any]) -> Dict[str, Any]:
    """Set page background color/transparency."""
    from core.pbip.page_operations_engine import set_page_background

    page_name = args.get("page_name") or args.get("page_id")
    if not page_name:
        return {"success": False, "error": "page_name or page_id is required"}

    definition_path = find_definition_folder(args["pbip_path"])
    if not definition_path:
        return {"success": False, "error": f"Could not find definition folder in: {args['pbip_path']}"}

    return set_page_background(
        definition_path=definition_path,
        page_name=page_name,
        color=args.get("color"),
        transparency=args.get("transparency"),
    )


def _op_set_wallpaper(args: Dict[str, Any]) -> Dict[str, Any]:
    """Set page wallpaper (outspace pane)."""
    from core.pbip.page_operations_engine import set_page_wallpaper

    page_name = args.get("page_name") or args.get("page_id")
    if not page_name:
        return {"success": False, "error": "page_name or page_id is required"}

    definition_path = find_definition_folder(args["pbip_path"])
    if not definition_path:
        return {"success": False, "error": f"Could not find definition folder in: {args['pbip_path']}"}

    return set_page_wallpaper(
        definition_path=definition_path,
        page_name=page_name,
        color=args.get("color"),
        transparency=args.get("transparency"),
    )


def _op_set_drillthrough(args: Dict[str, Any]) -> Dict[str, Any]:
    """Configure drillthrough filters on a page."""
    from core.pbip.page_operations_engine import set_drillthrough

    page_name = args.get("page_name") or args.get("page_id")
    if not page_name:
        return {"success": False, "error": "page_name or page_id is required"}

    definition_path = find_definition_folder(args["pbip_path"])
    if not definition_path:
        return {"success": False, "error": f"Could not find definition folder in: {args['pbip_path']}"}

    return set_drillthrough(
        definition_path=definition_path,
        page_name=page_name,
        table=args.get("table"),
        field=args.get("field"),
        clear=args.get("clear", False),
    )


def _op_set_tooltip(args: Dict[str, Any]) -> Dict[str, Any]:
    """Configure page as tooltip page."""
    from core.pbip.page_operations_engine import set_tooltip_page

    page_name = args.get("page_name") or args.get("page_id")
    if not page_name:
        return {"success": False, "error": "page_name or page_id is required"}

    definition_path = find_definition_folder(args["pbip_path"])
    if not definition_path:
        return {"success": False, "error": f"Could not find definition folder in: {args['pbip_path']}"}

    kwargs: Dict[str, Any] = {
        "definition_path": definition_path,
        "page_name": page_name,
    }
    if args.get("enabled") is not None:
        kwargs["enabled"] = args["enabled"]
    if args.get("width") is not None:
        kwargs["width"] = args["width"]
    if args.get("height") is not None:
        kwargs["height"] = args["height"]

    return set_tooltip_page(**kwargs)


def _op_hide(args: Dict[str, Any]) -> Dict[str, Any]:
    """Hide a page."""
    from core.pbip.page_operations_engine import set_page_visibility

    page_name = args.get("page_name") or args.get("page_id")
    if not page_name:
        return {"success": False, "error": "page_name or page_id is required"}

    definition_path = find_definition_folder(args["pbip_path"])
    if not definition_path:
        return {"success": False, "error": f"Could not find definition folder in: {args['pbip_path']}"}

    return set_page_visibility(
        definition_path=definition_path,
        page_name=page_name,
        hidden=True,
    )


def _op_show(args: Dict[str, Any]) -> Dict[str, Any]:
    """Show a hidden page."""
    from core.pbip.page_operations_engine import set_page_visibility

    page_name = args.get("page_name") or args.get("page_id")
    if not page_name:
        return {"success": False, "error": "page_name or page_id is required"}

    definition_path = find_definition_folder(args["pbip_path"])
    if not definition_path:
        return {"success": False, "error": f"Could not find definition folder in: {args['pbip_path']}"}

    return set_page_visibility(
        definition_path=definition_path,
        page_name=page_name,
        hidden=False,
    )


# --- Filter operations (delegated to filter_operations_handler) ---


def _op_list_filters(args: Dict[str, Any]) -> Dict[str, Any]:
    """List filters at report/page/visual level."""
    from server.handlers.filter_operations_handler import _op_list as _filter_list

    return _filter_list(args)


def _op_add_filter(args: Dict[str, Any]) -> Dict[str, Any]:
    """Add a new filter."""
    from server.handlers.filter_operations_handler import _op_add as _filter_add

    return _filter_add(args)


def _op_set_filter(args: Dict[str, Any]) -> Dict[str, Any]:
    """Update filter values."""
    from server.handlers.filter_operations_handler import _op_set as _filter_set

    return _filter_set(args)


def _op_clear_filters(args: Dict[str, Any]) -> Dict[str, Any]:
    """Remove all filters at the specified level."""
    from server.handlers.filter_operations_handler import _op_clear as _filter_clear

    return _filter_clear(args)


def _op_hide_filter(args: Dict[str, Any]) -> Dict[str, Any]:
    """Hide filter in the filter pane."""
    from server.handlers.filter_operations_handler import _op_hide as _filter_hide

    return _filter_hide(args)


def _op_unhide_filter(args: Dict[str, Any]) -> Dict[str, Any]:
    """Show filter in the filter pane."""
    from server.handlers.filter_operations_handler import _op_unhide as _filter_unhide

    return _filter_unhide(args)


def _op_lock_filter(args: Dict[str, Any]) -> Dict[str, Any]:
    """Lock filter (prevent user changes)."""
    from server.handlers.filter_operations_handler import _op_lock as _filter_lock

    return _filter_lock(args)


def _op_unlock_filter(args: Dict[str, Any]) -> Dict[str, Any]:
    """Unlock filter."""
    from server.handlers.filter_operations_handler import _op_unlock as _filter_unlock

    return _filter_unlock(args)


# --- Registration ---


def register_page_operations_handler(registry):
    """Register the page operations tool."""
    from server.tool_schemas import TOOL_SCHEMAS

    registry.register(
        ToolDefinition(
            name="07_Page_Operations",
            description=(
                "Page operations: list, create, clone, delete, reorder, resize, "
                "display, background, drillthrough, tooltip, hide/show, interactions, "
                "and filter CRUD (list_filters/add_filter/set_filter/clear_filters/hide_filter/lock_filter)."
            ),
            handler=handle_page_operations,
            input_schema=TOOL_SCHEMAS.get("page_operations", {}),
            category="pbip",
            sort_order=72,
            annotations={
                "readOnlyHint": False,
                "destructiveHint": True,
                "idempotentHint": False,
                "openWorldHint": True,
            },
        )
    )

    logger.info("Registered page_operations handler")
