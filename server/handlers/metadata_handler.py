"""
Metadata Handler
Handles searching tables, columns, measures
"""
from typing import Dict, Any
import logging
from server.registry import ToolDefinition

from core.validation import (
    get_manager_or_error,
    apply_pagination,
    apply_pagination_with_defaults,
    get_optional_bool,
)

logger = logging.getLogger(__name__)


def handle_search_string(args: Dict[str, Any]) -> Dict[str, Any]:
    """Search in measure names and/or expressions"""
    # Get manager with connection check
    qe = get_manager_or_error('query_executor')
    if isinstance(qe, dict):  # Error response
        return qe

    search_text = args.get('search_text', '')
    search_in_expression = get_optional_bool(args, 'search_in_expression', True)
    search_in_name = get_optional_bool(args, 'search_in_name', True)

    result = qe.search_measures_dax(search_text, search_in_expression, search_in_name)
    return apply_pagination_with_defaults(result, args)


def handle_search_objects(args: Dict[str, Any]) -> Dict[str, Any]:
    """Search across tables, columns, and measures"""
    # Get manager with connection check
    qe = get_manager_or_error('query_executor')
    if isinstance(qe, dict):  # Error response
        return qe

    pattern = args.get("pattern", "*")
    types = args.get("types", ["tables", "columns", "measures"])

    result = qe.search_objects_dax(pattern, types)
    return apply_pagination(result, args, rows_key='rows')


def register_metadata_handlers(registry):
    """Register all metadata-related handlers"""
    tools = [
        ToolDefinition(
            name="04_Search_Objects",
            description="Search tables/columns/measures by name pattern (wildcard). For DAX expression search, use Search_String.",
            handler=handle_search_objects,
            input_schema={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "types": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["tables", "columns", "measures"]}
                    },
                    "page_size": {"type": "integer"},
                    "next_token": {"type": "string"}
                },
                "required": []
            },
            category="query",
            sort_order=43  # 04 = Query & Search
        ),
        ToolDefinition(
            name="04_Search_String",
            description="Search inside DAX expressions and measure names. For object name search, use Search_Objects.",
            handler=handle_search_string,
            input_schema={
                "type": "object",
                "properties": {
                    "search_text": {"type": "string"},
                    "search_in_expression": {"type": "boolean"},
                    "search_in_name": {"type": "boolean"},
                    "page_size": {"type": "integer"},
                    "next_token": {"type": "string"}
                },
                "required": ["search_text"]
            },
            category="query",
            sort_order=44  # 04 = Query & Search
        ),
    ]

    for tool in tools:
        registry.register(tool)

    logger.info(f"Registered {len(tools)} metadata handlers")
