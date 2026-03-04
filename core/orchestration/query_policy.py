import logging
from typing import Any, Dict, List, Optional
from core.validation.error_handler import ErrorHandler

logger = logging.getLogger(__name__)



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

        if effective_mode == "analyze":
            # N-run benchmark via basic wall-clock timing
            basic = query_executor.validate_and_execute_dax(query, 0, bypass_cache=bypass_cache)
            basic.setdefault("decision", "analyze")
            basic.setdefault("reason", "Executed query for basic timing")
            return basic
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
