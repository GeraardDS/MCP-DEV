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

        # Deduplicate xmSQL query text in SE events
        raw_se_events = result.get('se_events', [])
        query_lookup = []
        query_to_idx = {}
        compact_se = []
        for evt in raw_se_events:
            qt = evt.get("query", "")
            if qt not in query_to_idx:
                query_to_idx[qt] = len(query_lookup)
                query_lookup.append(qt)
            ce = {k: v for k, v in evt.items() if k != "query"}
            ce["query_idx"] = query_to_idx[qt]
            compact_se.append(ce)

        trace_data = {
            'runner': 'native',
            'performance': perf,
            'se_queries_lookup': query_lookup,
            'se_events': compact_se,
            '_se_events_raw': raw_se_events,
            'cache_cleared': result.get('cache_cleared', False),
            'summary': summary,
        }
        # Cache for auto-retrieval by optimize
        connection_state.store_trace_result(trace_data)

        return {'success': True, **{k: v for k, v in trace_data.items() if not k.startswith('_')}}

    except ImportError:
        return {'success': False, 'error': 'NativeTraceRunner not available. Ensure core/infrastructure/query_trace.py exists.'}
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
                "clear_cache": {"type": "boolean", "default": True,
                                "description": "Clear VertiPaq cache before execution"}
            },
            "required": ["query"]
        },
        category="query",
        sort_order=43
    ))

    logger.info("Registered 1 query trace handler")
