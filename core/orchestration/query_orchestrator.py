"""DAX query execution orchestration."""
import logging
import time
from typing import Any, Dict, List, Optional
from .base_orchestrator import BaseOrchestrator

logger = logging.getLogger(__name__)

class QueryOrchestrator(BaseOrchestrator):
    """Handles DAX query execution workflows."""

    def __init__(self, config, query_policy=None):
        super().__init__(config)
        self.query_policy = query_policy

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
        """Validate, limit, and execute a DAX query. Optionally perform perf analysis."""
        from core.validation.error_handler import ErrorHandler

        qp = self.query_policy
        if qp is not None:
            return qp.safe_run_dax(
                connection_state,
                query,
                mode=mode,
                runs=runs,
                max_rows=max_rows,
                verbose=verbose,
                bypass_cache=bypass_cache,
                include_event_counts=include_event_counts,
            )
        # Fallback: in rare case policy import failed, use legacy logic
        if not connection_state.is_connected():
            return ErrorHandler.handle_not_connected()
        qe = connection_state.query_executor
        if not qe:
            return ErrorHandler.handle_manager_unavailable('query_executor')
        return qe.validate_and_execute_dax(query, 0)

    def plan_query(self, intent: str, context_table: Optional[str] = None, max_rows: Optional[int] = None) -> Dict[str, Any]:
        """Return a suggested approach and safe DAX skeleton based on a simple intent string."""
        intent_lower = (intent or "").lower()
        lim = self._get_preview_limit(max_rows)
        plan = {"success": True, "intent": intent, "recommendation": "preview", "max_rows": lim}

        if any(k in intent_lower for k in ["performance", "fast", "slow", "analyze se", "analyze fe"]):
            plan["recommendation"] = "analyze"
            plan["tool"] = "safe_run_dax(mode=analyze)"
        else:
            plan["tool"] = "safe_run_dax(mode=preview)"

        if context_table:
            plan["dax"] = f"EVALUATE TOPN({lim}, '{context_table}')"
        else:
            plan["dax"] = f"EVALUATE TOPN({lim}, <table_expression_here>)"

        plan["notes"] = [
            "Use SUMMARIZECOLUMNS / SELECTCOLUMNS for shaped previews",
            "Switch to mode=analyze for performance timing analysis",
        ]
        return plan

    def optimize_variants(
        self,
        connection_state,
        candidates: List[str],
        runs: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Benchmark N DAX variants and return the fastest.

        Returns per-variant timings and a winner with minimal avg_execution_ms.
        """
        from core.validation.error_handler import ErrorHandler

        if not connection_state.is_connected():
            return ErrorHandler.handle_not_connected()
        if not candidates or len([c for c in candidates if (c or "").strip()]) < 2:
            return {"success": False, "error": "Provide at least two non-empty candidates", "error_type": "invalid_input"}

        query_executor = connection_state.query_executor

        def run_bench(q: str) -> Dict[str, Any]:
            q = q or ""
            res = query_executor.validate_and_execute_dax(q, 0)
            return {"success": bool(res.get("success")), "execution_time_ms": res.get("execution_time_ms", 0), "raw": res}

        results: List[Dict[str, Any]] = []
        for idx, cand in enumerate(candidates):
            results.append({"candidate": idx, **run_bench(cand)})

        # Choose the minimal positive time; if all zero/False, mark no_winner
        valid = [r for r in results if r.get("success") and r.get("execution_time_ms", 0) >= 0]
        if not valid:
            return {"success": False, "error": "All candidates failed", "results": results}
        winner = min(valid, key=lambda r: r.get("execution_time_ms", float("inf")))
        return {"success": True, "runs": r, "results": results, "winner": winner, "decision": "optimize_variants", "reason": "Selected variant with minimum average execution time across runs"}

    def decide_and_run(
        self,
        connection_manager,
        connection_state,
        goal: str,
        query: Optional[str] = None,
        candidates: Optional[List[str]] = None,
        runs: Optional[int] = None,
        max_rows: Optional[int] = None,
        verbose: bool = False,
    ) -> Dict[str, Any]:
        """Performance-first decision orchestrator.

        - Ensures connection
        - If multiple candidates → benchmark and return the winner
        - Else if goal mentions performance → analyze query
        - Else → fast preview with safe TOPN
        """
        from core.orchestration.connection_orchestrator import ConnectionOrchestrator

        actions: List[Dict[str, Any]] = []
        conn_orch = ConnectionOrchestrator(self.config)
        ensured = conn_orch.ensure_connected(connection_manager, connection_state)
        actions.append({"action": "ensure_connected", "result": ensured})
        if not ensured.get("success"):
            return {"success": False, "phase": "ensure_connected", "actions": actions, "final": ensured}

        text = (goal or "").lower()
        nonempty_candidates = [c for c in (candidates or []) if (c or "").strip()]

        if len(nonempty_candidates) >= 2:
            bench = self.optimize_variants(connection_state, nonempty_candidates, runs)
            actions.append({"action": "optimize_variants", "result": bench})
            return {"success": bench.get("success", False), "decision": "optimize_variants", "reason": "Multiple candidates provided; benchmarking to pick the fastest", "actions": actions, "final": bench}

        if any(k in text for k in ["analyze", "performance", "perf", "timing"]):
            if not query:
                return {"success": False, "error": "No query provided for performance analysis", "phase": "input_validation", "actions": actions}
            res = self.safe_run_dax(connection_state, query, mode="analyze", runs=runs, max_rows=max_rows, verbose=verbose)
            actions.append({"action": "safe_run_dax(analyze)", "result": res})
            return {"success": res.get("success", False), "decision": "analyze", "reason": "Goal indicates performance focus; running performance timing analysis", "actions": actions, "final": res}

        # Default to preview for speed
        res = self.safe_run_dax(connection_state, query or "", mode="preview", runs=runs, max_rows=max_rows, verbose=verbose)
        actions.append({"action": "safe_run_dax(preview)", "result": res})
        return {"success": res.get("success", False), "decision": "preview", "reason": "No performance focus or multiple candidates; using fast safe preview for minimal latency", "actions": actions, "final": res}

    def execute_intent(
        self,
        connection_manager,
        connection_state,
        goal: str,
        query: Optional[str] = None,
        table: Optional[str] = None,
        runs: Optional[int] = None,
        max_rows: Optional[int] = None,
        verbose: bool = False,
        candidate_a: Optional[str] = None,
        candidate_b: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Simple rule-based intent executor so users don't need to say 'run safely'.
        Decides which orchestrations to call based on keywords and inputs.
        """
        from core.orchestration.connection_orchestrator import ConnectionOrchestrator
        from core.orchestration.analysis_orchestrator import AnalysisOrchestrator

        # Ensure connection first
        conn_orch = ConnectionOrchestrator(self.config)
        ensured = conn_orch.ensure_connected(connection_manager, connection_state)
        actions: List[Dict[str, Any]] = [{"action": "ensure_connected", "result": ensured}]
        if not ensured.get("success"):
            return {"success": False, "error": "Connection not established", "phase": "ensure_connected", "details": ensured}

        text = (goal or "").lower()

        # Schema + samples intent: produce flat list with sample values per column
        if any(k in text for k in [
            "sample row", "sample rows", "sample values", "columns with sample", "columns and samples",
            "flat schema", "schema samples", "all tables and columns with sample"
        ]):
            # Determine preferred format from intent
            fmt = 'csv'
            if 'excel' in text or 'xlsx' in text:
                fmt = 'xlsx'
            elif 'txt' in text or 'text' in text:
                fmt = 'txt'
            # Detect desired row count (1-10) if present
            import re
            m = re.search(r"(\d+)\s*(sample|row|rows)", text)
            rows = 3
            try:
                if m:
                    rows = max(1, min(10, int(m.group(1))))
            except Exception:
                pass

        # Relationship-focused intents: return list and analysis directly
        if any(k in text for k in ["relationship", "relationships", "rels", "cardinality", "relations"]):
            analysis_orch = AnalysisOrchestrator(self.config)
            rel = analysis_orch.relationship_overview(connection_state)
            actions.append({"action": "relationship_overview", "result": rel})
            return {"success": rel.get("success", False), "actions": actions, "final": rel}

        # Optimization benchmark if both candidates present
        if candidate_a and candidate_b:
            # Use optimize_variants for 2-candidate case to avoid duplicate tooling
            bench = self.optimize_variants(connection_state, [candidate_a, candidate_b], runs)
            actions.append({"action": "optimize_variants", "result": bench})
            return {"success": bench.get("success", False), "actions": actions, "final": bench}

        # Documentation or model summary intents
        if any(k in text for k in ["document", "documentation", "docs", "summarize", "overview", "schema", "structure", "model summary", "list tables", "list measures"]):
            # Prefer a safe summary
            summary = conn_orch.summarize_model_safely(connection_state)
            actions.append({"action": "summarize_model", "result": summary})
            if not summary.get("success"):
                return {"success": False, "phase": "summarize_model", "actions": actions, "final": summary}
            # If explicitly asked to document, proceed to docs
            if any(k in text for k in ["document", "documentation", "docs"]):
                from core.orchestration.documentation_orchestrator import DocumentationOrchestrator
                doc_orch = DocumentationOrchestrator(self.config)
                doc = doc_orch.generate_docs_safe(connection_state)
                actions.append({"action": "generate_docs_safe", "result": doc})
                return {"success": doc.get("success", False), "actions": actions, "final": doc}
            return {"success": True, "actions": actions, "final": summary}

        # Performance analysis intents
        if any(k in text for k in ["analyze performance", "performance", "perf", "timing"]):
            if not query:
                return {"success": False, "error": "No query provided for performance analysis", "phase": "input_validation", "actions": actions}
            res = self.safe_run_dax(connection_state, query, mode="analyze", runs=runs, max_rows=max_rows, verbose=verbose)
            actions.append({"action": "safe_run_dax(analyze)", "result": res})
            return {"success": res.get("success", False), "actions": actions, "final": res}

        # If user asks to analyze the model without specifics, propose options (fast vs normal)
        if any(k in text for k in ["analyze", "analysis"]) and not query and not any(k in text for k in ["performance", "perf", "timing"]):
            analysis_orch = AnalysisOrchestrator(self.config)
            proposal = analysis_orch.propose_analysis_options(connection_state, goal)
            actions.append({"action": "propose_analysis_options", "result": proposal})
            return {"success": True, "decision": "propose_analysis", "actions": actions, "final": proposal}

        # Generic run/query/preview intents
        if query or any(k in text for k in ["run", "execute", "preview", "query", "show"]):
            res = self.safe_run_dax(connection_state, query or "", mode="preview", runs=runs, max_rows=max_rows, verbose=verbose)
            actions.append({"action": "safe_run_dax(preview)", "result": res})
            return {"success": res.get("success", False), "actions": actions, "final": res}

        # Health/status intents
        if any(k in text for k in ["health", "status", "connected", "ready"]):
            health = conn_orch.agent_health(connection_manager, connection_state)
            actions.append({"action": "agent_health", "result": health})
            return {"success": health.get("success", False), "actions": actions, "final": health}

        # Default: plan based on table context
        plan = self.plan_query(text, table, max_rows)
        actions.append({"action": "plan_query", "result": plan})
        return {"success": True, "actions": actions, "final": plan}

    def auto_analyze_or_preview(self, connection_manager, connection_state, query: str, runs: Optional[int] = None, max_rows: Optional[int] = None, priority: str = 'depth') -> Dict[str, Any]:
        """Auto analyze or preview based on priority."""
        # priority: 'speed' -> preview, 'depth' -> analyze
        mode = 'preview' if (priority or 'depth').lower() == 'speed' else 'analyze'
        return self.safe_run_dax(connection_state, query, mode=mode, runs=runs, max_rows=max_rows)

    def _get_default_perf_runs(self, runs: Optional[int]) -> int:
        """Get default performance analysis run count."""
        if isinstance(runs, int) and runs > 0:
            return runs
        return self.config.get("performance.default_runs", 3) or 3
