"""
Query Handler
Handles DAX query execution, validation, and data preview.
Includes SE/FE trace analysis (previously in query_trace_handler).
"""
from typing import Dict, Any
import logging
from server.registry import ToolDefinition
from core.infrastructure.connection_state import connection_state
from core.validation.error_handler import ErrorHandler

logger = logging.getLogger(__name__)


def handle_run_dax_trace(args: Dict[str, Any]) -> Dict[str, Any]:
    """Execute DAX query with SE/FE trace analysis using native .NET runner"""
    if not connection_state.is_connected():
        return ErrorHandler.handle_not_connected()

    query = args.get('query')
    if not query:
        return {'success': False, 'error': 'query parameter required'}

    clear_cache = args.get('clear_cache', True)

    try:
        conn_str = connection_state.connection_manager.connection_string
        if not conn_str:
            return {'success': False, 'error': 'No connection string available'}

        from core.infrastructure.query_trace import NativeTraceRunner
        if not NativeTraceRunner.is_available():
            return {
                'success': False,
                'error': 'Native trace runner (DaxExecutor.exe) not found. '
                         'Build it with: cd core/infrastructure/dax_executor && dotnet build -c Release'
            }

        native = NativeTraceRunner(conn_str)
        result = native.execute_with_trace(query, clear_cache)

        if "_error" in result:
            return {'success': False, 'error': f'Trace execution failed: {result["_error"]}'}

        perf = {
            'total_ms': result.get('total_ms', 0),
            'fe_ms': result.get('fe_ms', 0),
            'se_ms': result.get('se_ms', 0),
            'se_cpu_ms': result.get('se_cpu_ms', 0),
            'se_parallelism': result.get('se_parallelism', 0.0),
            'se_queries': result.get('se_queries', 0),
            'se_cache_hits': result.get('se_cache_hits', 0),
            'fe_pct': result.get('fe_pct', 0.0),
            'se_pct': result.get('se_pct', 0.0),
        }

        summary = (
            f"Total: {perf['total_ms']}ms | "
            f"FE: {perf['fe_ms']}ms ({perf['fe_pct']}%) | "
            f"SE: {perf['se_ms']}ms ({perf['se_pct']}%) | "
            f"SE queries: {perf['se_queries']} | "
            f"SE cache: {perf['se_cache_hits']}"
        )

        trace_data = {
            'runner': 'native',
            'performance': perf,
            'se_events': result.get('se_events', []),
            'cache_cleared': result.get('cache_cleared', False),
            'summary': summary,
        }
        # Cache for auto-retrieval by optimize
        connection_state.store_trace_result(trace_data)

        return {'success': True, **trace_data}

    except ImportError:
        return {'success': False, 'error': 'NativeTraceRunner not available. Ensure core/infrastructure/query_trace.py exists.'}
    except Exception as e:
        logger.error(f"Query trace execution failed: {e}")
        return {'success': False, 'error': f'Trace execution failed: {str(e)}'}


def handle_run_dax(args: Dict[str, Any]) -> Dict[str, Any]:
    """Execute DAX query with auto limits"""
    if not connection_state.is_connected():
        return ErrorHandler.handle_not_connected()

    query = args.get('query')
    if not query:
        return {'success': False, 'error': 'query parameter required'}

    mode = args.get('mode', 'auto')

    # Trace mode: SE/FE timing analysis
    if mode == 'trace':
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

def handle_get_roles(args: Dict[str, Any]) -> Dict[str, Any]:
    """List RLS/OLS security roles with permissions"""
    from core.operations.role_operations import RoleOperationsHandler
    handler = RoleOperationsHandler()
    return handler.execute({'operation': 'list'})


def handle_query_operations(args: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatch query operations: data_sources, m_expressions, search_objects, roles"""
    operation = args.get('operation', 'data_sources')

    if operation == 'data_sources':
        return handle_get_data_sources(args)
    elif operation == 'm_expressions':
        return handle_get_m_expressions(args)
    elif operation == 'search_objects':
        from server.handlers.metadata_handler import handle_search_objects
        return handle_search_objects(args)
    elif operation == 'roles':
        return handle_get_roles(args)
    else:
        return {
            'success': False,
            'error': f'Unknown operation: {operation}. Valid: data_sources, m_expressions, search_objects, roles'
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
                             "description": "auto=preview, simple=preview, analyze=N-run benchmark, trace=SE/FE timing analysis"},
                    "clear_cache": {"type": "boolean", "default": True,
                                    "description": "Clear VertiPaq cache before execution (trace mode only)"}
                },
                "required": ["query"]
            },
            category="query",
            sort_order=40
        ),
        ToolDefinition(
            name="04_Query_Operations",
            description="Query model metadata: data_sources, m_expressions, search_objects, roles",
            handler=handle_query_operations,
            input_schema={
                "type": "object",
                "properties": {
                    "operation": {"type": "string", "enum": ["data_sources", "m_expressions", "search_objects", "roles"]},
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
