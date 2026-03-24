"""
PBIP Prototype Handler

MCP tool handler for report prototyping operations: spec-based generation,
HTML prototype creation, and HTML-to-PBIP translation.
"""

import logging
from pathlib import Path
from typing import Any, Dict

from server.registry import ToolDefinition

logger = logging.getLogger(__name__)


def _resolve_definition_path(pbip_path: str) -> Dict[str, Any]:
    """Resolve and validate the definition path from a PBIP path."""
    from core.utilities.pbip_utils import find_definition_folder

    definition_path = find_definition_folder(pbip_path)
    if not definition_path:
        return {
            "error": (
                f"Could not find definition folder in: {pbip_path}."
                " Ensure path points to a valid PBIP project."
            )
        }
    return {"path": definition_path}


def handle_pbip_prototype(args: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatch PBIP prototyping operations."""
    operation = args.get("operation", "")
    pbip_path = args.get("pbip_path", "")

    if not pbip_path:
        return {"success": False, "error": "pbip_path is required"}

    ops = {
        "generate_from_spec": _op_generate_from_spec,
        "generate_html": _op_generate_html,
        "apply_html": _op_apply_html,
    }

    handler = ops.get(operation)
    if not handler:
        return {
            "success": False,
            "error": f"Unknown operation: '{operation}'. Valid: {', '.join(sorted(ops.keys()))}",
        }

    return handler(args, pbip_path)


def _op_generate_from_spec(args: Dict[str, Any], pbip_path: str) -> Dict[str, Any]:
    """Generate a complete PBIP page from a structured specification."""
    from core.pbip.authoring.report_builder import ReportBuilder

    resolved = _resolve_definition_path(pbip_path)
    if "error" in resolved:
        return {"success": False, **resolved}

    spec = args.get("spec")
    if not spec:
        return {"success": False, "error": "spec is required (page specification object)"}

    if not isinstance(spec, dict):
        return {"success": False, "error": "spec must be an object (dict)"}

    builder = ReportBuilder()
    result = builder.generate_from_spec(
        definition_path=resolved["path"],
        spec=spec,
    )
    result["operation"] = "generate_from_spec"
    return result


def _op_generate_html(args: Dict[str, Any], pbip_path: str) -> Dict[str, Any]:
    """Generate an interactive HTML prototype from a PBIP page.

    Auto-connects to Power BI if needed, then calls the debug handler's
    visual operation for each data visual to get real data with proper
    filter context, then renders into HTML.
    """
    from core.pbip.authoring.html.prototype_generator import PrototypeGenerator

    resolved = _resolve_definition_path(pbip_path)
    if "error" in resolved:
        return {"success": False, **resolved}

    page_name = args.get("page_name")
    if not page_name:
        return {"success": False, "error": "page_name is required"}

    output_path = args.get("output_path")
    auto_open = args.get("auto_open", True)
    include_data = args.get("include_data", True)

    # Step 1: Auto-connect to Power BI if not already connected
    is_connected = False
    if include_data:
        try:
            from src.pbixray_server_enhanced import connection_state

            if not connection_state.is_connected():
                # Auto-detect and connect
                from server.handlers.connection_handler import handle_connect_to_powerbi

                connect_result = handle_connect_to_powerbi({"model_index": 0})
                if connect_result.get("ok"):
                    is_connected = True
                    logger.info("Auto-connected to Power BI for HTML prototype")
                else:
                    logger.warning(f"Auto-connect failed: {connect_result.get('err', 'unknown')}")
            else:
                is_connected = True
        except Exception as e:
            logger.warning(f"Could not auto-connect to Power BI: {e}")

    generator = PrototypeGenerator()

    # Step 2: Generate the visual layout (without data initially)
    result = generator.generate(
        definition_path=resolved["path"],
        page_name=page_name,
        output_path=output_path,
        auto_open=False,  # Don't open yet — inject data first
        include_data=False,
    )

    if not result.get("success"):
        return result

    # Step 3: Inject live data by calling debug handler for each data visual
    data_count = 0
    if include_data and is_connected:
        data_count = _inject_live_data_via_debug(
            resolved["path"], page_name, result.get("path", ""), generator
        )
        result["data_visuals_populated"] = data_count
    elif include_data and not is_connected:
        result["warning"] = "Not connected to Power BI — data not populated"

    # Step 4: Open in browser
    if auto_open and result.get("path"):
        import webbrowser

        webbrowser.open(result["path"])

    result["operation"] = "generate_html"
    return result


def _inject_live_data_via_debug(definition_path, page_name: str, html_path: str, generator) -> int:
    """Call the debug handler for each data visual and regenerate HTML with data.

    This uses the exact same code path as 09_Debug_Operations visual operation,
    so filter context (slicers, page filters, report filters) is correct.
    """
    from core.pbip.authoring.html.prototype_generator import PrototypeGenerator
    from pathlib import Path

    try:
        from server.handlers.debug_handler import handle_debug_operations
    except Exception:
        return 0

    # Read visuals from the page
    page_dir = generator._find_page(definition_path, page_name)
    if not page_dir:
        return 0

    visuals = generator._read_visuals_with_hierarchy(page_dir)

    # Data visual types worth querying
    data_visual_types = {
        "columnChart",
        "barChart",
        "lineChart",
        "areaChart",
        "lineClusteredColumnComboChart",
        "lineStackedColumnComboChart",
        "donutChart",
        "pieChart",
        "waterfallChart",
        "clusteredColumnChart",
        "clusteredBarChart",
        "stackedColumnChart",
        "ribbonChart",
        "table",
        "tableEx",
        "matrix",
        "pivotTable",
        "card",
        "cardVisual",
        "multiRowCard",
        "kpi",
        "gauge",
    }
    scalar_types = {"card", "cardVisual", "multiRowCard", "kpi", "gauge"}

    data_count = 0

    for v in visuals:
        if v.get("is_hidden") or v.get("is_visual_group"):
            continue

        vtype = v.get("visual_type", "")
        vid = v.get("id", "")
        measures = v.get("fields", {}).get("measures", [])
        columns = v.get("fields", {}).get("columns", [])

        if not measures or vtype not in data_visual_types:
            continue

        try:
            # Call debug handler — same as MCP tool 09_Debug_Operations
            debug_result = handle_debug_operations(
                {
                    "operation": "visual",
                    "page_name": page_name,
                    "visual_id": vid,
                    "execute_query": True,
                    "compact": True,
                }
            )

            # Debug handler returns "success" (direct call) or "ok" (via MCP)
            if not (debug_result.get("ok") or debug_result.get("success")):
                continue

            result_data = debug_result.get("result", {})
            if not isinstance(result_data, dict) or result_data.get("err"):
                continue

            rows = result_data.get("rows", [])
            if not rows:
                continue

            # Inject data into the visual
            if vtype in scalar_types or (not columns and measures):
                # Extract scalar values from the grand total row or first row
                data_values = {}
                # For matrices with IsGrandTotalRowTotal, find the total row
                total_row = None
                for row in rows:
                    if isinstance(row, dict) and row.get("[IsGrandTotalRowTotal]") == "True":
                        total_row = row
                        break
                target_row = total_row or rows[0]

                for m in measures:
                    key = f"{m['table']}.{m['measure']}"
                    val = PrototypeGenerator._find_measure_in_row(target_row, m["measure"])
                    if val is not None:
                        data_values[key] = PrototypeGenerator._format_value(val)
                if data_values:
                    v["data_values"] = data_values
                    data_count += 1
            else:
                # Tabular data for charts and tables
                v["table_data"] = rows
                data_count += 1

        except Exception as e:
            logger.debug(f"Debug query failed for visual {vid}: {e}")

    # Regenerate HTML with data-populated visuals
    if data_count > 0:
        from core.pbip.authoring.html.html_template import generate_html_page
        from core.utilities.pbip_utils import load_json_file

        page_json = load_json_file(page_dir / "page.json")
        display_name = page_json.get("displayName", page_name) if page_json else page_name
        width = page_json.get("width", 1280) if page_json else 1280
        height = page_json.get("height", 720) if page_json else 720

        html = generate_html_page(
            page_name=display_name,
            page_width=width,
            page_height=height,
            visuals=visuals,
        )

        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)

    return data_count


def _op_apply_html(args: Dict[str, Any], pbip_path: str) -> Dict[str, Any]:
    """Apply changes from an HTML prototype back to PBIP."""
    from core.pbip.authoring.html.prototype_parser import PrototypeParser

    resolved = _resolve_definition_path(pbip_path)
    if "error" in resolved:
        return {"success": False, **resolved}

    state = args.get("state")
    if not state:
        return {"success": False, "error": "state is required (exported HTML state JSON)"}

    dry_run = args.get("dry_run", False)

    parser = PrototypeParser()
    result = parser.apply_state(
        definition_path=resolved["path"],
        state=state,
        dry_run=dry_run,
    )
    result["operation"] = "apply_html"
    return result


# --- Schema ---


PROTOTYPE_SCHEMA = {
    "type": "object",
    "properties": {
        "pbip_path": {
            "type": "string",
            "description": "Path to PBIP project, .Report folder, or .pbip file",
        },
        "operation": {
            "type": "string",
            "enum": ["generate_from_spec", "generate_html", "apply_html"],
            "description": "Operation to perform",
        },
        # generate_from_spec
        "spec": {
            "type": "object",
            "description": (
                "Page specification for generate_from_spec. Structure: "
                "{page_name: str, width?: int, height?: int, background_color?: str, "
                "visuals: [{type: str, title?: str, position: {x, y, width, height, z?}, "
                "measures?: [{table, measure, bucket?, display_name?}], "
                "columns?: [{table, column, bucket?, display_name?}], "
                "category?: [{table, column}], values?: [{table, measure}], "
                "rows?: [{table, column}], "
                "formatting?: {config_type: {prop: value}}, "
                "slicer_mode?: str, single_select?: bool, "
                "sort?: {table, field, direction?}, "
                "parent_group?: str, hidden?: bool, "
                "group_name?: str, children?: [visual_spec...]}]}"
            ),
        },
        # generate_html
        "page_name": {
            "type": "string",
            "description": "Page display name (for generate_html)",
        },
        "output_path": {
            "type": "string",
            "description": "Custom HTML output file path",
        },
        "auto_open": {
            "type": "boolean",
            "description": "Auto-open HTML in browser (default: true)",
        },
        "include_data": {
            "type": "boolean",
            "description": "Include live data from Power BI connection (default: false)",
        },
        # apply_html
        "state": {
            "type": "object",
            "description": "Exported state JSON from HTML prototype",
        },
        "dry_run": {
            "type": "boolean",
            "description": "Preview changes without saving (default: false)",
        },
    },
    "required": ["pbip_path", "operation"],
}


def register_prototype_handler(registry):
    """Register the PBIP prototype tool."""
    registry.register(
        ToolDefinition(
            name="11_PBIP_Prototype",
            description=(
                "Generate and prototype Power BI report pages. "
                "Operations: generate_from_spec (create page from spec), "
                "generate_html (PBIP to interactive HTML), apply_html (HTML changes back to PBIP)"
            ),
            handler=handle_pbip_prototype,
            input_schema=PROTOTYPE_SCHEMA,
            category="authoring",
            sort_order=1101,
        )
    )
