"""
Query Handler
Handles DAX query execution, validation, and data preview
"""
from typing import Dict, Any
import logging
from server.registry import ToolDefinition
from core.infrastructure.connection_state import connection_state
from core.validation.error_handler import ErrorHandler

logger = logging.getLogger(__name__)

def handle_run_dax(args: Dict[str, Any]) -> Dict[str, Any]:
    """Execute DAX query with auto limits"""
    if not connection_state.is_connected():
        return ErrorHandler.handle_not_connected()

    query = args.get('query')
    if not query:
        return {'success': False, 'error': 'query parameter required'}

    mode = args.get('mode', 'auto')

    # Trace mode: delegate to query trace handler for SE/FE analysis
    if mode == 'trace':
        from server.handlers.query_trace_handler import handle_run_dax_trace
        return handle_run_dax_trace(args)

    agent_policy = connection_state.agent_policy
    if not agent_policy:
        return ErrorHandler.handle_manager_unavailable('agent_policy')

    top_n = args.get('top_n', 100)

    result = agent_policy.safe_run_dax(
        connection_state=connection_state,
        query=query,
        mode=mode,
        max_rows=top_n
    )

    return result

def handle_get_data_sources(args: Dict[str, Any]) -> Dict[str, Any]:
    """List data sources with fallback to TOM"""
    if not connection_state.is_connected():
        return ErrorHandler.handle_not_connected()

    qe = connection_state.query_executor
    if not qe:
        return ErrorHandler.handle_manager_unavailable('query_executor')

    # Use INFO query to get data sources
    result = qe.execute_info_query("DATASOURCES")
    return result

def handle_get_m_expressions(args: Dict[str, Any]) -> Dict[str, Any]:
    """List M/Power Query expressions"""
    if not connection_state.is_connected():
        return ErrorHandler.handle_not_connected()

    qe = connection_state.query_executor
    if not qe:
        return ErrorHandler.handle_manager_unavailable('query_executor')

    limit = args.get('limit')

    # Use INFO query to get partitions which contain M expressions
    result = qe.execute_info_query("PARTITIONS")

    if result.get('success') and limit:
        rows = result.get('rows', [])
        result['rows'] = rows[:limit]

    return result

def handle_query_operations(args: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatch query operations: data_sources, m_expressions, search_objects"""
    operation = args.get('operation', 'data_sources')

    if operation == 'data_sources':
        return handle_get_data_sources(args)
    elif operation == 'm_expressions':
        return handle_get_m_expressions(args)
    elif operation == 'search_objects':
        from server.handlers.metadata_handler import handle_search_objects
        return handle_search_objects(args)
    else:
        return {
            'success': False,
            'error': f'Unknown operation: {operation}. Valid: data_sources, m_expressions, search_objects'
        }


def register_query_handlers(registry):
    """Register query handlers"""
    from server.handlers.metadata_handler import handle_search_string

    tools = [
        ToolDefinition(
            name="04_Run_DAX",
            description="Execute DAX query with auto limits",
            handler=handle_run_dax,
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "DAX query (EVALUATE statement)"},
                    "top_n": {"type": "integer", "description": "Max rows (default: 100)", "default": 100},
                    "mode": {"type": "string", "enum": ["auto", "analyze", "simple", "trace"], "default": "auto",
                             "description": "auto=preview, simple=preview, analyze=N-run benchmark, trace=SE/FE timing analysis"}
                },
                "required": ["query"]
            },
            category="query",
            sort_order=40
        ),
        ToolDefinition(
            name="04_Query_Operations",
            description="Query model metadata: data_sources, m_expressions, search_objects",
            handler=handle_query_operations,
            input_schema={
                "type": "object",
                "properties": {
                    "operation": {"type": "string", "enum": ["data_sources", "m_expressions", "search_objects"]},
                    "pattern": {"type": "string", "description": "Search pattern (search_objects)"},
                    "types": {"type": "array", "items": {"type": "string", "enum": ["tables", "columns", "measures"]}, "description": "Object types (search_objects)"},
                    "limit": {"type": "integer", "description": "Max results (m_expressions)"},
                    "page_size": {"type": "integer"},
                    "next_token": {"type": "string"}
                },
                "required": ["operation"]
            },
            category="query",
            sort_order=41
        ),
        ToolDefinition(
            name="04_Search_String",
            description="Search inside DAX expressions and measure names",
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
            sort_order=42
        ),
    ]

    for tool in tools:
        registry.register(tool)

    logger.info(f"Registered {len(tools)} query handlers")
