"""
PBIP Authoring Handler

MCP tool handler for report authoring operations: cloning, creating,
and deleting pages and visuals in PBIP reports.
"""

import logging
from pathlib import Path
from typing import Any, Dict

from server.registry import ToolDefinition
from core.utilities.pbip_utils import resolve_definition_path

logger = logging.getLogger(__name__)


def handle_pbip_authoring(args: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatch PBIP authoring operations."""
    operation = args.get("operation", "")
    pbip_path = args.get("pbip_path", "")

    if not pbip_path:
        return {"success": False, "error": "pbip_path is required"}

    ops = {
        "clone_page": _op_clone_page,
        "clone_report": _op_clone_report,
        "create_page": _op_create_page,
        "create_visual": _op_create_visual,
        "create_visual_group": _op_create_visual_group,
        "delete_page": _op_delete_page,
        "delete_visual": _op_delete_visual,
        "list_templates": _op_list_templates,
        "get_template": _op_get_template,
    }

    handler = ops.get(operation)
    if not handler:
        return {
            "success": False,
            "error": f"Unknown operation: '{operation}'. Valid: {', '.join(sorted(ops.keys()))}",
        }

    return handler(args, pbip_path)


# --- Operation Implementations ---


def _op_clone_page(args: Dict[str, Any], pbip_path: str) -> Dict[str, Any]:
    """Clone a page with all visuals, regenerating IDs."""
    from core.pbip.authoring.clone_engine import CloneEngine

    resolved = resolve_definition_path(pbip_path)
    if "error" in resolved:
        return {"success": False, **resolved}

    source_page = args.get("source_page")
    if not source_page:
        return {"success": False, "error": "source_page is required (page ID or display name)"}

    engine = CloneEngine()
    result = engine.clone_page(
        definition_path=resolved["path"],
        source_page_id=source_page,
        new_display_name=args.get("new_display_name"),
        insert_after=args.get("insert_after"),
    )
    result["operation"] = "clone_page"
    return result


def _op_clone_report(args: Dict[str, Any], pbip_path: str) -> Dict[str, Any]:
    """Clone an entire report with new IDs."""
    from core.pbip.authoring.clone_engine import CloneEngine

    from core.utilities.pbip_utils import normalize_path, resolve_pbip_report_path

    source = resolve_pbip_report_path(pbip_path)
    if not source:
        return {"success": False, "error": f"Could not resolve report path: {pbip_path}"}

    target_path = args.get("target_path")
    if not target_path:
        return {"success": False, "error": "target_path is required"}

    target_path = normalize_path(target_path)
    engine = CloneEngine()
    result = engine.clone_report(
        source_report_path=Path(source),
        target_path=Path(target_path),
        new_report_name=args.get("new_report_name"),
    )
    result["operation"] = "clone_report"
    return result


def _op_create_page(args: Dict[str, Any], pbip_path: str) -> Dict[str, Any]:
    """Create a new empty page."""
    from core.pbip.authoring.page_builder import PageBuilder

    resolved = resolve_definition_path(pbip_path)
    if "error" in resolved:
        return {"success": False, **resolved}

    page_name = args.get("page_name")
    if not page_name:
        return {"success": False, "error": "page_name is required"}

    builder = PageBuilder(resolved["path"], page_name)

    width = args.get("width")
    height = args.get("height")
    if width and height:
        builder.set_dimensions(int(width), int(height))

    insert_after = args.get("insert_after")
    result = builder.build(insert_after=insert_after)
    result["operation"] = "create_page"
    return result


def _op_create_visual(args: Dict[str, Any], pbip_path: str) -> Dict[str, Any]:
    """Create a new visual on a page from a template spec."""
    from core.pbip.authoring.visual_builder import VisualBuilder

    resolved = resolve_definition_path(pbip_path)
    if "error" in resolved:
        return {"success": False, **resolved}

    page_id = args.get("page_id") or args.get("page_name")
    if not page_id:
        return {"success": False, "error": "page_id or page_name is required"}

    visual_type = args.get("visual_type")
    if not visual_type:
        return {"success": False, "error": "visual_type is required"}

    # Resolve page
    definition_path = resolved["path"]
    page_dir = _resolve_page_dir(definition_path, page_id)
    if not page_dir:
        return {"success": False, "error": f"Page not found: {page_id}"}

    # Build the visual
    builder = VisualBuilder(visual_type)

    # Position
    pos = args.get("position", {})
    if pos:
        builder.position(
            x=pos.get("x", 0),
            y=pos.get("y", 0),
            width=pos.get("width", 300),
            height=pos.get("height", 200),
            z=pos.get("z", 0),
        )

    # Title
    title = args.get("title")
    if title:
        builder.set_title(title)

    # Data bindings - measures
    for m in args.get("measures", []):
        builder.add_measure(
            table=m.get("table", ""),
            measure=m.get("measure", ""),
            bucket=m.get("bucket", "Values"),
            display_name=m.get("display_name"),
        )

    # Data bindings - columns
    for c in args.get("columns", []):
        builder.add_column(
            table=c.get("table", ""),
            column=c.get("column", ""),
            bucket=c.get("bucket", "Category"),
            display_name=c.get("display_name"),
        )

    # Parent group
    parent_group = args.get("parent_group")
    if parent_group:
        builder.in_group(parent_group)

    # Formatting overrides
    for fmt in args.get("formatting", []):
        builder.set_formatting(
            config_type=fmt.get("config_type", ""),
            property_name=fmt.get("property_name", ""),
            value=fmt.get("value"),
        )

    visual_dict = builder.build()

    # Write to disk
    visuals_dir = page_dir / "visuals"
    visuals_dir.mkdir(exist_ok=True)
    visual_id = visual_dict["name"]
    visual_folder = visuals_dir / visual_id
    visual_folder.mkdir(exist_ok=True)

    from core.utilities.pbip_utils import save_json_file

    save_json_file(visual_folder / "visual.json", visual_dict)

    return {
        "success": True,
        "operation": "create_visual",
        "visual_id": visual_id,
        "visual_type": visual_type,
        "page_id": page_dir.name,
        "path": str(visual_folder),
    }


def _op_create_visual_group(args: Dict[str, Any], pbip_path: str) -> Dict[str, Any]:
    """Create a visual group container on a page."""
    from core.pbip.authoring.visual_builder import VisualBuilder

    resolved = resolve_definition_path(pbip_path)
    if "error" in resolved:
        return {"success": False, **resolved}

    page_id = args.get("page_id") or args.get("page_name")
    if not page_id:
        return {"success": False, "error": "page_id or page_name is required"}

    definition_path = resolved["path"]
    page_dir = _resolve_page_dir(definition_path, page_id)
    if not page_dir:
        return {"success": False, "error": f"Page not found: {page_id}"}

    group_name = args.get("group_name", "Visual Group")

    builder = VisualBuilder("visualGroup")
    pos = args.get("position", {})
    if pos:
        builder.position(
            x=pos.get("x", 0),
            y=pos.get("y", 0),
            width=pos.get("width", 400),
            height=pos.get("height", 300),
            z=pos.get("z", 0),
        )
    builder.set_group_name(group_name)

    visual_dict = builder.build()
    visual_id = visual_dict["name"]

    visuals_dir = page_dir / "visuals"
    visuals_dir.mkdir(exist_ok=True)
    visual_folder = visuals_dir / visual_id
    visual_folder.mkdir(exist_ok=True)

    from core.utilities.pbip_utils import save_json_file

    save_json_file(visual_folder / "visual.json", visual_dict)

    return {
        "success": True,
        "operation": "create_visual_group",
        "visual_id": visual_id,
        "group_name": group_name,
        "page_id": page_dir.name,
        "path": str(visual_folder),
    }


def _op_delete_page(args: Dict[str, Any], pbip_path: str) -> Dict[str, Any]:
    """Delete a page and update pages.json."""
    from core.pbip.authoring.clone_engine import CloneEngine

    resolved = resolve_definition_path(pbip_path)
    if "error" in resolved:
        return {"success": False, **resolved}

    page_id = args.get("page_id") or args.get("page_name")
    if not page_id:
        return {"success": False, "error": "page_id or page_name is required"}

    engine = CloneEngine()
    result = engine.delete_page(resolved["path"], page_id)
    result["operation"] = "delete_page"
    return result


def _op_delete_visual(args: Dict[str, Any], pbip_path: str) -> Dict[str, Any]:
    """Delete a visual (and children if it's a group)."""
    from core.pbip.authoring.clone_engine import CloneEngine

    resolved = resolve_definition_path(pbip_path)
    if "error" in resolved:
        return {"success": False, **resolved}

    page_id = args.get("page_id") or args.get("page_name")
    visual_id = args.get("visual_id") or args.get("visual_name")
    if not page_id:
        return {"success": False, "error": "page_id or page_name is required"}
    if not visual_id:
        return {"success": False, "error": "visual_id or visual_name is required"}

    engine = CloneEngine()
    result = engine.delete_visual(
        definition_path=resolved["path"],
        page_id=page_id,
        visual_id=visual_id,
        delete_children=args.get("delete_children", True),
    )
    result["operation"] = "delete_visual"
    return result


def _op_list_templates(args: Dict[str, Any], pbip_path: str) -> Dict[str, Any]:
    """List available visual templates."""
    from core.pbip.authoring.visual_templates import get_template_catalog

    catalog = get_template_catalog()
    return {
        "success": True,
        "operation": "list_templates",
        "templates": catalog,
        "count": len(catalog),
    }


def _op_get_template(args: Dict[str, Any], pbip_path: str) -> Dict[str, Any]:
    """Get the full template structure for a visual type."""
    from core.pbip.authoring.visual_templates import get_template, TEMPLATE_REGISTRY

    visual_type = args.get("visual_type")
    if not visual_type:
        return {"success": False, "error": "visual_type is required"}

    if visual_type not in TEMPLATE_REGISTRY:
        return {
            "success": False,
            "error": f"Unknown visual type: '{visual_type}'. Available: {', '.join(sorted(TEMPLATE_REGISTRY.keys()))}",
        }

    template = get_template(visual_type)
    return {
        "success": True,
        "operation": "get_template",
        "visual_type": visual_type,
        "template": template,
    }


# --- Helpers ---


def _resolve_page_dir(definition_path: Path, page_id: str) -> Path | None:
    """Resolve a page ID or display name to its directory."""
    from core.utilities.pbip_utils import load_json_file

    pages_dir = definition_path / "pages"
    if not pages_dir.exists():
        return None

    # Try direct ID match
    direct = pages_dir / page_id
    if direct.exists() and direct.is_dir():
        return direct

    # Try display name match
    page_id_lower = page_id.lower()
    for page_folder in pages_dir.iterdir():
        if not page_folder.is_dir():
            continue
        page_json = load_json_file(page_folder / "page.json")
        if page_json:
            display_name = page_json.get("displayName", "")
            if display_name.lower() == page_id_lower or page_id_lower in display_name.lower():
                return page_folder

    return None


# --- Registration ---


AUTHORING_SCHEMA = {
    "type": "object",
    "properties": {
        "pbip_path": {
            "type": "string",
            "description": "Path to PBIP project, .Report folder, or .pbip file",
        },
        "operation": {
            "type": "string",
            "enum": [
                "clone_page",
                "clone_report",
                "create_page",
                "create_visual",
                "create_visual_group",
                "delete_page",
                "delete_visual",
                "list_templates",
                "get_template",
            ],
            "description": "Operation to perform",
        },
        # Clone operations
        "source_page": {
            "type": "string",
            "description": "Source page ID or display name (for clone_page)",
        },
        "new_display_name": {
            "type": "string",
            "description": "New display name for cloned page",
        },
        "target_path": {
            "type": "string",
            "description": "Target path for cloned report (clone_report)",
        },
        "new_report_name": {
            "type": "string",
            "description": "New name for cloned report",
        },
        # Page operations
        "page_name": {
            "type": "string",
            "description": "Display name for new page, or page identifier for other ops",
        },
        "page_id": {
            "type": "string",
            "description": "Page ID (alternative to page_name)",
        },
        "width": {
            "type": "integer",
            "description": "Page width in pixels (default: 1280)",
        },
        "height": {
            "type": "integer",
            "description": "Page height in pixels (default: 720)",
        },
        "insert_after": {
            "type": "string",
            "description": "Page ID to insert new page after",
        },
        # Visual operations
        "visual_type": {
            "type": "string",
            "description": "Visual type (e.g., columnChart, card, table, slicer, shape)",
        },
        "visual_id": {
            "type": "string",
            "description": "Visual ID (for delete_visual)",
        },
        "visual_name": {
            "type": "string",
            "description": "Visual name/title (alternative to visual_id)",
        },
        "title": {
            "type": "string",
            "description": "Visual title text",
        },
        "position": {
            "type": "object",
            "description": "Visual position {x, y, width, height, z}",
            "properties": {
                "x": {"type": "number"},
                "y": {"type": "number"},
                "width": {"type": "number"},
                "height": {"type": "number"},
                "z": {"type": "integer"},
            },
        },
        "measures": {
            "type": "array",
            "description": "Measure bindings [{table, measure, bucket?, display_name?}]",
            "items": {
                "type": "object",
                "properties": {
                    "table": {"type": "string"},
                    "measure": {"type": "string"},
                    "bucket": {"type": "string"},
                    "display_name": {"type": "string"},
                },
                "required": ["table", "measure"],
            },
        },
        "columns": {
            "type": "array",
            "description": "Column bindings [{table, column, bucket?, display_name?}]",
            "items": {
                "type": "object",
                "properties": {
                    "table": {"type": "string"},
                    "column": {"type": "string"},
                    "bucket": {"type": "string"},
                    "display_name": {"type": "string"},
                },
                "required": ["table", "column"],
            },
        },
        "parent_group": {
            "type": "string",
            "description": "Parent visual group ID",
        },
        "group_name": {
            "type": "string",
            "description": "Display name for visual group",
        },
        "formatting": {
            "type": "array",
            "description": "Formatting overrides [{config_type, property_name, value}]",
            "items": {
                "type": "object",
                "properties": {
                    "config_type": {"type": "string"},
                    "property_name": {"type": "string"},
                    "value": {},
                },
            },
        },
        "delete_children": {
            "type": "boolean",
            "description": "Delete child visuals of groups (default: true)",
        },
    },
    "required": ["pbip_path", "operation"],
}


def register_authoring_handler(registry):
    """Register the PBIP authoring tool."""
    registry.register(
        ToolDefinition(
            name="11_PBIP_Authoring",
            description=(
                "Create, clone, and delete pages/visuals in PBIP reports. "
                "Operations: clone_page, clone_report, create_page, create_visual, "
                "create_visual_group, delete_page, delete_visual, list_templates, get_template"
            ),
            handler=handle_pbip_authoring,
            input_schema=AUTHORING_SCHEMA,
            category="authoring",
            sort_order=1100,
            annotations={
                "readOnlyHint": False,
                "destructiveHint": True,
                "idempotentHint": False,
                "openWorldHint": False,
            },
        )
    )
