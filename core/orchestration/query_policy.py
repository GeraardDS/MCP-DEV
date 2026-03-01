import logging
from typing import Any, Dict, List, Optional
from core.validation.error_handler import ErrorHandler

logger = logging.getLogger(__name__)


def _clear_vertipaq_cache(server: Any) -> bool:
    """Clear VertiPaq cache via AMO Server.Execute() before profiling.

    Ensures cold-cache results comparable to DAX Studio's 'Clear Cache then Run'.
    Returns True if cache was cleared successfully.
    """
    try:
        # PBI Desktop typically has one database
        if server.Databases.Count == 0:
            return False
        db_id = server.Databases[0].ID
        xmla = (
            '<ClearCache xmlns="http://schemas.microsoft.com/analysisservices/2003/engine">'
            f"<Object><DatabaseID>{db_id}</DatabaseID></Object>"
            "</ClearCache>"
        )
        server.Execute(xmla)
        logger.debug(f"VertiPaq cache cleared for database {db_id}")
        return True
    except Exception as e:
        logger.debug(f"Cache clear failed (non-critical): {e}")
        return False


def _run_sefe_profile(connection_state: Any, query: str) -> Dict[str, Any]:
    """Run DAX Studio-style SE/FE profiling via AMO trace events.

    Clears the VertiPaq cache before profiling to ensure cold-cache results
    comparable to DAX Studio's Server Timings.

    Returns a dict with total_ms, fe_ms, se_ms, se_query_count, se_cache_hits,
    se_queries, se_parallelism, and profiling_method.  Falls back to basic
    execution if tracing is unavailable.
    """
    from core.performance.se_fe_profiler import SEFEProfiler
    from core.performance.trace_manager import TraceManager

    query_executor = connection_state.query_executor
    connection = query_executor.connection if query_executor else None

    if connection is None:
        return ErrorHandler.handle_manager_unavailable("connection")

    # Create AMO server for both cache clearing and trace
    tm = TraceManager()
    amo_server = tm._create_amo_server(connection)

    # Clear VertiPaq cache before profiling (like DAX Studio)
    if amo_server is not None:
        _clear_vertipaq_cache(amo_server)

    profiler = SEFEProfiler(trace_manager=tm)
    try:
        result = profiler.profile_query(
            connection=connection, query=query, server=amo_server
        )
    except Exception as e:
        logger.warning(f"SE/FE profiling failed: {e}")
        exec_result = query_executor.validate_and_execute_dax(query, 0)
        exec_result.setdefault("notes", []).append(
            f"SE/FE profiling unavailable: {e}"
        )
        return exec_result
    finally:
        # Disconnect AMO server if we created it
        if amo_server is not None:
            try:
                amo_server.Disconnect()
            except Exception:
                pass

    return {"ok": True, "query": query, **result.to_dict()}


def _is_complete_define_query(query: str) -> bool:
    """Check if query is a complete DEFINE+EVALUATE statement that must not be wrapped."""
    q_upper = (query or "").strip().upper()
    return q_upper.startswith("DEFINE")


def _should_apply_topn(query: str) -> bool:
    """Check if query is a bare EVALUATE that should be wrapped with TOPN for safety."""
    q_upper = (query or "").strip().upper()
    return (
        q_upper.startswith("EVALUATE")
        and "TOPN(" not in q_upper
        and not _is_complete_define_query(query)
    )


def _apply_topn_wrapper(query: str, limit: int) -> str:
    """Wrap a bare EVALUATE query with TOPN for row safety."""
    body = (query.strip()[len("EVALUATE"):]).strip()
    return f"EVALUATE TOPN({limit}, {body})"


class QueryPolicy:
    def __init__(self, config: Any):
        self.config = config

    def _get_preview_limit(self, max_rows: Optional[int]) -> int:
        if isinstance(max_rows, int) and max_rows > 0:
            return max_rows
        return (
            self.config.get("query.max_rows_preview", 1000)
            or self.config.get("performance.default_top_n", 1000)
            or 1000
        )

    def _get_default_perf_runs(self, runs: Optional[int]) -> int:
        if isinstance(runs, int) and runs > 0:
            return runs
        return 3

    def safe_run_dax(
        self,
        connection_state,
        query: str,
        mode: str = "auto",
        runs: Optional[int] = None,
        max_rows: Optional[int] = None,
        verbose: bool = False,
        bypass_cache: bool = False,
        include_event_counts: bool = False,
    ) -> Dict[str, Any]:
        if not connection_state.is_connected():
            return ErrorHandler.handle_not_connected()
        query_executor = connection_state.query_executor
        performance_analyzer = connection_state.performance_analyzer
        if not query_executor:
            return ErrorHandler.handle_manager_unavailable('query_executor')
        analysis = query_executor.analyze_dax_query(query)
        if not analysis.get("success"):
            return analysis
        if analysis.get("syntax_errors"):
            return {
                "success": False,
                "error": "Query validation failed",
                "error_type": "syntax_validation_error",
                "details": analysis,
            }
        lim = self._get_preview_limit(max_rows)
        try:
            limits = connection_state.get_safety_limits()
            max_rows_cap = int(limits.get('max_rows_per_call', 10000))
            if isinstance(lim, int) and lim > 0:
                lim = min(lim, max_rows_cap)
        except Exception:
            pass
        effective_mode = (mode or "auto").lower()
        notes: List[str] = []

        # mode=profile → single-run SE/FE trace (DAX Studio Server Timings style)
        if effective_mode == "profile":
            result = _run_sefe_profile(connection_state, query)
            result.setdefault("decision", "profile")
            result.setdefault("reason", "SE/FE trace profiling via AMO trace events")
            return result

        q_upper = (query or "").strip().upper()
        if effective_mode == "auto":
            # EVALUATE/DEFINE queries are for data preview, not performance analysis
            do_perf = not q_upper.startswith(("EVALUATE", "DEFINE"))
        else:
            # "analyze" → N-run benchmark; "simple" → preview
            do_perf = effective_mode == "analyze"
        if do_perf:
            r = self._get_default_perf_runs(runs)
            if not performance_analyzer:
                basic = query_executor.validate_and_execute_dax(query, 0, bypass_cache=bypass_cache)
                basic.setdefault("notes", []).append("Performance analyzer unavailable; returned basic execution only")
                basic["success"] = basic.get("success", False)
                basic.setdefault("decision", "analyze")
                basic.setdefault("reason", "Requested performance analysis, but analyzer unavailable; returned basic execution")
                return basic
            try:
                result = performance_analyzer.analyze_query(query_executor, query, r, True, include_event_counts)
                if not result.get("success"):
                    raise RuntimeError(result.get("error") or "analysis_failed")
                result.setdefault("decision", "analyze")
                result.setdefault("reason", "Performance analysis selected to obtain execution timing statistics")
                return result
            except Exception as _e:
                if _should_apply_topn(query):
                    try:
                        query = _apply_topn_wrapper(query, lim)
                        notes.append(f"Applied TOPN({lim}) to EVALUATE query for safety (analyze fallback)")
                    except Exception:
                        pass
                exec_result = query_executor.validate_and_execute_dax(query, lim, bypass_cache=bypass_cache)
                exec_result.setdefault("notes", []).append(
                    f"Analyzer error; returned preview instead: {str(_e)}"
                )
                exec_result.setdefault("decision", "analyze_fallback_preview")
                exec_result.setdefault("reason", "XMLA/xEvents unavailable or errored; provided successful preview with safe TOPN")
                if verbose and notes:
                    exec_result.setdefault("notes", []).extend(notes)
                return exec_result
        # Preview path: apply TOPN for bare EVALUATE queries only
        if _should_apply_topn(query):
            try:
                query = _apply_topn_wrapper(query, lim)
                notes.append(f"Applied TOPN({lim}) to EVALUATE query for safety")
            except Exception:
                pass
        exec_result = query_executor.validate_and_execute_dax(query, lim, bypass_cache=bypass_cache)
        if verbose and notes:
            exec_result.setdefault("notes", []).extend(notes)
        exec_result.setdefault("decision", "preview")
        exec_result.setdefault("reason", "Fast preview chosen to minimize latency and limit rows safely with TOPN")
        if verbose:
            exec_result.setdefault("analysis", analysis)
        return exec_result
