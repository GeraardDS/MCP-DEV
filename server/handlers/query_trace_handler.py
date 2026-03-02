"""
Query Trace Handler
Handles DAX query execution with SE/FE trace analysis (server timings)
"""
from typing import Dict, Any
import logging
from server.registry import ToolDefinition
from core.infrastructure.connection_state import connection_state
from core.validation.error_handler import ErrorHandler

logger = logging.getLogger(__name__)


def handle_run_dax_trace(args: Dict[str, Any]) -> Dict[str, Any]:
    """Execute DAX query with SE/FE trace analysis"""
    if not connection_state.is_connected():
        return ErrorHandler.handle_not_connected()

    query = args.get('query')
    if not query:
        return {'success': False, 'error': 'query parameter required'}

    clear_cache = args.get('clear_cache', False)

    try:
        from core.infrastructure.query_trace import QueryTraceRunner

        adomd_conn = connection_state.connection_manager.get_connection()
        if not adomd_conn:
            return {'success': False, 'error': 'Failed to get ADOMD connection'}

        conn_str = connection_state.connection_manager.connection_string
        if not conn_str:
            return {'success': False, 'error': 'No connection string available'}

        runner = QueryTraceRunner(adomd_conn, conn_str)
        result = runner.execute_with_trace(query, clear_cache)

        # Core returns flat dict — restructure into response format
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

        return {
            'success': True,
            'performance': perf,
            'se_events': result.get('se_events', []),
            'query_rows': result.get('query_rows', 0),
            'cache_cleared': result.get('cache_cleared', False),
            'summary': summary,
        }

    except ImportError:
        return {'success': False, 'error': 'QueryTraceRunner not available. Ensure core/infrastructure/query_trace.py exists.'}
    except Exception as e:
        logger.error(f"Query trace execution failed: {e}")
        return {'success': False, 'error': f'Trace execution failed: {str(e)}'}


def register_query_trace_handler(registry):
    """Register query trace handler"""
    registry.register(ToolDefinition(
        name="04_Run_DAX_Trace",
        description="Execute DAX query with SE/FE trace analysis (server timings)",
        handler=handle_run_dax_trace,
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "DAX query (EVALUATE statement)"},
                "clear_cache": {"type": "boolean", "default": False,
                                "description": "Clear VertiPaq cache before execution"}
            },
            "required": ["query"]
        },
        category="query",
        sort_order=43
    ))

    logger.info("Registered 1 query trace handler")
