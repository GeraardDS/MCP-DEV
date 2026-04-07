"""
Theme Operations Handler
Theme manipulation and conditional formatting operations.

Operations:
- analyze_compliance: Theme compliance analysis with HTML output (existing)
- get_theme: Load and return current theme
- set_colors: Set theme colors
- set_formatting: Set theme formatting defaults
- push_visual: Push visual formatting to theme
- list_text_classes: List text class definitions
- set_font: Set font properties
- list_cf: List conditional formatting rules
- add_cf: Add conditional formatting rule
- remove_cf: Remove conditional formatting rule
- copy_cf: Copy CF rules between visuals
"""
from typing import Dict, Any
import logging
from pathlib import Path

from server.registry import ToolDefinition
from core.utilities.pbip_utils import find_definition_folder

logger = logging.getLogger(__name__)


def _resolve_report_path(pbip_path: str) -> Path:
    """Resolve a pbip_path string to the .Report folder Path.

    Theme engine functions expect report_path (the .Report folder), not definition_path.
    Raises FileNotFoundError if not found.
    """
    from server.handlers.bookmark_theme_handler import _find_report_folder

    return Path(_find_report_folder(pbip_path))


def handle_theme_operations(args: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatch theme and conditional formatting operations."""
    operation = args.get("operation", "get_theme")
    pbip_path = args.get("pbip_path")

    if not pbip_path:
        return {"success": False, "error": "pbip_path is required"}

    ops = {
        "analyze_compliance": _op_analyze_compliance,
        "get_theme": _op_get_theme,
        "set_colors": _op_set_colors,
        "set_formatting": _op_set_formatting,
        "push_visual": _op_push_visual,
        "list_text_classes": _op_list_text_classes,
        "set_font": _op_set_font,
        "list_cf": _op_list_cf,
        "add_cf": _op_add_cf,
        "remove_cf": _op_remove_cf,
        "copy_cf": _op_copy_cf,
    }

    handler = ops.get(operation)
    if not handler:
        return {
            "success": False,
            "error": f"Unknown operation: '{operation}'. Valid: {', '.join(sorted(ops.keys()))}",
        }

    return handler(args)


# --- Delegated operation (reuse existing logic) ---


def _op_analyze_compliance(args: Dict[str, Any]) -> Dict[str, Any]:
    """Theme compliance analysis — delegates to existing bookmark_theme_handler."""
    from server.handlers.bookmark_theme_handler import handle_theme_compliance

    return handle_theme_compliance(args)


# --- Theme operations (dispatch to theme_engine) ---


def _op_get_theme(args: Dict[str, Any]) -> Dict[str, Any]:
    """Load and return current theme."""
    from core.pbip.theme_engine import get_theme

    try:
        report_path = _resolve_report_path(args["pbip_path"])
    except FileNotFoundError as e:
        return {"success": False, "error": str(e)}

    return get_theme(report_path=report_path)


def _op_set_colors(args: Dict[str, Any]) -> Dict[str, Any]:
    """Set theme colors."""
    from core.pbip.theme_engine import set_colors

    colors = args.get("colors")
    if not colors:
        return {"success": False, "error": "colors is required (object with dataColors, background, foreground, etc.)"}

    try:
        report_path = _resolve_report_path(args["pbip_path"])
    except FileNotFoundError as e:
        return {"success": False, "error": str(e)}

    return set_colors(
        report_path=report_path,
        colors=colors,
    )


def _op_set_formatting(args: Dict[str, Any]) -> Dict[str, Any]:
    """Set theme formatting defaults for a visual type."""
    from core.pbip.theme_engine import set_formatting

    formatting = args.get("formatting")
    if not formatting:
        return {"success": False, "error": "formatting is required"}

    visual_type = args.get("visual_type_target")
    if not visual_type:
        return {"success": False, "error": "visual_type_target is required for set_formatting"}

    try:
        report_path = _resolve_report_path(args["pbip_path"])
    except FileNotFoundError as e:
        return {"success": False, "error": str(e)}

    return set_formatting(
        report_path=report_path,
        visual_type=visual_type,
        formatting=formatting,
    )


def _op_push_visual(args: Dict[str, Any]) -> Dict[str, Any]:
    """Push visual formatting to the theme."""
    from core.pbip.theme_engine import push_visual_to_theme

    page_name = args.get("page_name")
    visual_name = args.get("visual_name")
    if not page_name or not visual_name:
        return {"success": False, "error": "page_name and visual_name are required for push_visual"}

    try:
        report_path = _resolve_report_path(args["pbip_path"])
    except FileNotFoundError as e:
        return {"success": False, "error": str(e)}

    definition_path = find_definition_folder(args["pbip_path"])
    if not definition_path:
        return {"success": False, "error": f"Could not find definition folder in: {args['pbip_path']}"}

    return push_visual_to_theme(
        report_path=report_path,
        definition_path=definition_path,
        page_name=page_name,
        visual_name=visual_name,
    )


def _op_list_text_classes(args: Dict[str, Any]) -> Dict[str, Any]:
    """List text class definitions in the theme."""
    from core.pbip.theme_engine import list_text_classes

    try:
        report_path = _resolve_report_path(args["pbip_path"])
    except FileNotFoundError as e:
        return {"success": False, "error": str(e)}

    return list_text_classes(report_path=report_path)


def _op_set_font(args: Dict[str, Any]) -> Dict[str, Any]:
    """Set font properties in the theme or text class."""
    from core.pbip.theme_engine import set_font

    try:
        report_path = _resolve_report_path(args["pbip_path"])
    except FileNotFoundError as e:
        return {"success": False, "error": str(e)}

    return set_font(
        report_path=report_path,
        text_class=args.get("text_class"),
        font_family=args.get("font_family"),
        font_size=args.get("font_size"),
        color=args.get("color"),
        bold=args.get("bold"),
    )


# --- Conditional formatting operations (dispatch to conditional_formatting_engine) ---


def _op_list_cf(args: Dict[str, Any]) -> Dict[str, Any]:
    """List conditional formatting rules."""
    from core.pbip.conditional_formatting_engine import list_rules

    definition_path = find_definition_folder(args["pbip_path"])
    if not definition_path:
        return {"success": False, "error": f"Could not find definition folder in: {args['pbip_path']}"}

    return list_rules(
        definition_path=definition_path,
        page_name=args.get("page_name"),
        visual_name=args.get("visual_name"),
    )


def _op_add_cf(args: Dict[str, Any]) -> Dict[str, Any]:
    """Add a conditional formatting rule."""
    from core.pbip.conditional_formatting_engine import add_rule

    page_name = args.get("page_name")
    visual_name = args.get("visual_name")
    if not page_name or not visual_name:
        return {"success": False, "error": "page_name and visual_name are required for add_cf"}

    container = args.get("container")
    property_name = args.get("property_name")
    rule_type = args.get("rule_type")
    if not container or not property_name or not rule_type:
        return {"success": False, "error": "container, property_name, and rule_type are required for add_cf"}

    definition_path = find_definition_folder(args["pbip_path"])
    if not definition_path:
        return {"success": False, "error": f"Could not find definition folder in: {args['pbip_path']}"}

    return add_rule(
        definition_path=definition_path,
        page_name=page_name,
        visual_name=visual_name,
        container=container,
        property_name=property_name,
        rule_type=rule_type,
        config=args.get("cf_config", {}),
    )


def _op_remove_cf(args: Dict[str, Any]) -> Dict[str, Any]:
    """Remove a conditional formatting rule."""
    from core.pbip.conditional_formatting_engine import remove_rule

    page_name = args.get("page_name")
    visual_name = args.get("visual_name")
    if not page_name or not visual_name:
        return {"success": False, "error": "page_name and visual_name are required for remove_cf"}

    container = args.get("container")
    property_name = args.get("property_name")
    if not container or not property_name:
        return {"success": False, "error": "container and property_name are required for remove_cf"}

    definition_path = find_definition_folder(args["pbip_path"])
    if not definition_path:
        return {"success": False, "error": f"Could not find definition folder in: {args['pbip_path']}"}

    return remove_rule(
        definition_path=definition_path,
        page_name=page_name,
        visual_name=visual_name,
        container=container,
        property_name=property_name,
    )


def _op_copy_cf(args: Dict[str, Any]) -> Dict[str, Any]:
    """Copy conditional formatting rules between visuals."""
    from core.pbip.conditional_formatting_engine import copy_rule

    source_page = args.get("source_page")
    source_visual = args.get("source_visual")
    target_page = args.get("target_page")
    target_visual = args.get("target_visual")

    if not source_page or not source_visual:
        return {"success": False, "error": "source_page and source_visual are required for copy_cf"}
    if not target_page or not target_visual:
        return {"success": False, "error": "target_page and target_visual are required for copy_cf"}

    container = args.get("container")
    property_name = args.get("property_name")
    if not container or not property_name:
        return {"success": False, "error": "container and property_name are required for copy_cf"}

    definition_path = find_definition_folder(args["pbip_path"])
    if not definition_path:
        return {"success": False, "error": f"Could not find definition folder in: {args['pbip_path']}"}

    return copy_rule(
        definition_path=definition_path,
        source_page=source_page,
        source_visual=source_visual,
        target_page=target_page,
        target_visual=target_visual,
        container=container,
        property_name=property_name,
    )


# --- Registration ---


def register_theme_operations_handler(registry):
    """Register the theme operations tool."""
    from server.tool_schemas import TOOL_SCHEMAS

    registry.register(
        ToolDefinition(
            name="07_Theme_Operations",
            description=(
                "Theme and conditional formatting: analyze_compliance, "
                "colors, formatting, fonts, text classes, CF rules."
            ),
            handler=handle_theme_operations,
            input_schema=TOOL_SCHEMAS.get("theme_operations", {}),
            category="pbip",
            sort_order=77,
            annotations={"readOnlyHint": False, "destructiveHint": True},
        )
    )

    logger.info("Registered theme_operations handler")
