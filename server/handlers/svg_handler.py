"""
SVG Operations Handler
Unified handler for SVG template operations
"""
from typing import Dict, Any
import logging
from server.registry import ToolDefinition
from core.svg.svg_operations import SVGOperationsHandler

logger = logging.getLogger(__name__)

# Create singleton instance
_svg_ops_handler = SVGOperationsHandler()


def handle_svg_operations(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle unified SVG operations"""
    return _svg_ops_handler.execute(args)


def register_svg_operations_handler(registry):
    """Register SVG operations handler"""

    tool = ToolDefinition(
        name="SVG_Visual_Operations",
        description="SVG visual generation: 40+ DAX templates for KPIs, sparklines, gauges, data bars. List, preview, generate, inject.",
        handler=handle_svg_operations,
        input_schema={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": [
                        "list_templates", "get_template", "preview_template",
                        "generate_measure", "inject_measure", "list_categories",
                        "search_templates", "validate_svg", "create_custom"
                    ],
                },
                "category": {
                    "type": "string",
                    "enum": ["kpi", "sparklines", "gauges", "databars", "advanced"],
                    "description": "Category filter (list_templates)"
                },
                "complexity": {
                    "type": "string",
                    "enum": ["basic", "intermediate", "advanced", "complex"],
                    "description": "Complexity filter (list_templates)"
                },
                "template_id": {
                    "type": "string",
                    "description": "Template ID"
                },
                "parameters": {
                    "type": "object",
                    "description": "Template params: measure_name, value_measure, threshold_low/high, color_good/bad/warning (%23RRGGBB)"
                },
                "table_name": {
                    "type": "string",
                    "description": "Target table (inject_measure)"
                },
                "measure_name": {
                    "type": "string",
                    "description": "Measure name"
                },
                "search_query": {
                    "type": "string",
                    "description": "Search term (search_templates)"
                },
                "svg_code": {
                    "type": "string",
                    "description": "SVG code (validate_svg, create_custom)"
                },
                "dynamic_vars": {
                    "type": "object",
                    "description": "Dynamic variables: keys=var names, values=DAX expressions (create_custom)"
                },
                "context_aware": {
                    "type": "boolean",
                    "description": "Use connected model for suggestions",
                    "default": True
                }
            },
            "required": ["operation"]
        },
        category="pbip",
        sort_order=50
    )

    registry.register(tool)
    logger.info("Registered svg_operations handler")
