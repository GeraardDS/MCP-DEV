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
                        "list_templates",
                        "get_template",
                        "preview_template",
                        "generate_measure",
                        "inject_measure",
                        "list_categories",
                        "search_templates",
                        "validate_svg",
                        "create_custom"
                    ],
                    "description": (
                        "Operation to perform:\n"
                        "- list_templates: List templates (optional: category filter)\n"
                        "- get_template: Get full template details (requires: template_id)\n"
                        "- preview_template: Get static SVG preview (requires: template_id)\n"
                        "- generate_measure: Generate DAX code (requires: template_id, parameters)\n"
                        "- inject_measure: Create measure in model (requires: template_id, table_name, parameters)\n"
                        "- list_categories: List all template categories\n"
                        "- search_templates: Search by keyword (requires: search_query)\n"
                        "- validate_svg: Check SVG compatibility (requires: svg_code)\n"
                        "- create_custom: Build custom SVG measure (requires: svg_code)"
                    )
                },
                "category": {
                    "type": "string",
                    "enum": ["kpi", "sparklines", "gauges", "databars", "advanced"],
                    "description": "Filter by category (for list_templates operation)"
                },
                "complexity": {
                    "type": "string",
                    "enum": ["basic", "intermediate", "advanced", "complex"],
                    "description": "Filter by complexity level (for list_templates operation)"
                },
                "template_id": {
                    "type": "string",
                    "description": "Template ID (for get_template, preview_template, generate_measure, inject_measure)"
                },
                "parameters": {
                    "type": "object",
                    "description": (
                        "Template parameters for DAX generation. Common parameters:\n"
                        "- measure_name: Name for the generated measure\n"
                        "- value_measure: The measure to visualize, e.g., [Profit Margin]\n"
                        "- threshold_low/threshold_high: Values for conditional coloring\n"
                        "- color_good/color_bad/color_warning: Colors in %23RRGGBB format"
                    )
                },
                "table_name": {
                    "type": "string",
                    "description": "Target table for inject_measure operation (e.g., '_Measures')"
                },
                "measure_name": {
                    "type": "string",
                    "description": "Name for the generated measure (can also be in parameters)"
                },
                "search_query": {
                    "type": "string",
                    "description": "Search term for search_templates operation"
                },
                "svg_code": {
                    "type": "string",
                    "description": "SVG code for validate_svg or create_custom operations"
                },
                "dynamic_vars": {
                    "type": "object",
                    "description": (
                        "For create_custom: Dynamic variables to include in the measure. "
                        "Keys are variable names, values are DAX expressions."
                    )
                },
                "context_aware": {
                    "type": "boolean",
                    "description": "Use connected model for parameter suggestions (default: true)",
                    "default": True
                }
            },
            "required": ["operation"]
        },
        category="visualization",
        sort_order=50
    )

    registry.register(tool)
    logger.info("Registered svg_operations handler")
