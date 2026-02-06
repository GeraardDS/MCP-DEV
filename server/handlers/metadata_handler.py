"""
Metadata Handler
Handles listing and searching tables, columns, measures

Refactored to use validation utilities for reduced code duplication.
"""
from typing import Dict, Any
import logging
from server.registry import ToolDefinition, get_registry
from core.infrastructure.query_executor import COLUMN_TYPE_CALCULATED

# Import validation utilities
from core.validation import (
    get_manager_or_error,
    get_table_name,
    apply_pagination,
    apply_pagination_with_defaults,
    apply_describe_table_defaults,
    validate_required,
    validate_required_params,
    get_optional_bool,
    ErrorHandler,
)

logger = logging.getLogger(__name__)


def handle_list_tables(args: Dict[str, Any]) -> Dict[str, Any]:
    """List all tables in the model"""
    # Get manager with connection check
    qe = get_manager_or_error('query_executor')
    if isinstance(qe, dict):  # Error response
        return qe

    result = qe.execute_info_query("TABLES")
    return apply_pagination(result, args)


def handle_list_columns(args: Dict[str, Any]) -> Dict[str, Any]:
    """List columns, optionally filtered by table"""
    # Get manager with connection check
    qe = get_manager_or_error('query_executor')
    if isinstance(qe, dict):  # Error response
        return qe

    table = args.get("table")

    result = qe.execute_info_query("COLUMNS", table_name=table)
    return apply_pagination_with_defaults(result, args)


def handle_list_measures(args: Dict[str, Any]) -> Dict[str, Any]:
    """List measures, optionally filtered by table"""
    # Get manager with connection check
    qe = get_manager_or_error('query_executor')
    if isinstance(qe, dict):  # Error response
        return qe

    table = args.get("table")

    result = qe.execute_info_query("MEASURES", table_name=table, exclude_columns=['Expression'])
    return apply_pagination_with_defaults(result, args)


def handle_describe_table(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get comprehensive table description with columns, measures, relationships"""
    # Get manager with connection check
    qe = get_manager_or_error('query_executor')
    if isinstance(qe, dict):  # Error response
        return qe

    # Apply default pagination limits for describe_table
    args = apply_describe_table_defaults(args)

    table = args.get("table")

    # Validate required parameter
    if error := validate_required(table, 'table', 'describe_table'):
        return error

    # Check if method exists
    if not hasattr(qe, 'describe_table'):
        return {
            'success': False,
            'error': 'describe_table method not implemented in query executor',
            'error_type': 'not_implemented',
            'suggestion': 'This tool requires legacy implementation'
        }

    try:
        result = qe.describe_table(table, args)
        return result
    except AttributeError as e:
        logger.error(f"AttributeError in describe_table: {e}", exc_info=True)
        return {
            'success': False,
            'error': f'Method error: {str(e)}',
            'error_type': 'method_not_found',
            'suggestion': 'This tool may need to be bridged to legacy implementation'
        }
    except Exception as e:
        logger.error(f"Error in describe_table: {e}", exc_info=True)
        return ErrorHandler.handle_unexpected_error('describe_table', e)


def handle_get_measure_details(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get detailed measure information including DAX formula"""
    # Get manager with connection check
    qe = get_manager_or_error('query_executor')
    if isinstance(qe, dict):  # Error response
        return qe

    table = args.get("table")
    measure = args.get("measure")

    # Validate required parameters
    if error := validate_required_params(
        (table, 'table'),
        (measure, 'measure'),
        operation='get_measure_details'
    ):
        return error

    result = qe.get_measure_details_with_fallback(table, measure)
    return result


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


def handle_list_calculated_columns(args: Dict[str, Any]) -> Dict[str, Any]:
    """List calculated columns"""
    # Get manager with connection check
    qe = get_manager_or_error('query_executor')
    if isinstance(qe, dict):  # Error response
        return qe

    table = args.get("table")

    filter_expr = f'[Type] = {COLUMN_TYPE_CALCULATED}'
    result = qe.execute_info_query("COLUMNS", filter_expr=filter_expr, table_name=table)
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
            category="metadata",
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
            category="metadata",
            sort_order=44  # 04 = Query & Search
        ),
    ]

    for tool in tools:
        registry.register(tool)

    logger.info(f"Registered {len(tools)} metadata handlers")
