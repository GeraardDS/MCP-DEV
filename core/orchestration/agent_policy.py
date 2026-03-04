"""
Agent policy layer for PBIXRay MCP Server - REFACTORED FACADE

This module now serves as a facade/adapter that delegates to specialized orchestrators.
All methods have been extracted to focused orchestrator classes for better maintainability.

For direct usage, import the specific orchestrators:
- ConnectionOrchestrator
- QueryOrchestrator
- DocumentationOrchestrator
- AnalysisOrchestrator
- PbipOrchestrator
- CacheOrchestrator
"""

import logging
from typing import Any, Dict, Optional, List

from core.orchestration.connection_orchestrator import ConnectionOrchestrator
from core.orchestration.query_orchestrator import QueryOrchestrator
from core.orchestration.documentation_orchestrator import DocumentationOrchestrator
from core.orchestration.analysis_orchestrator import AnalysisOrchestrator
from core.orchestration.pbip_orchestrator import PbipOrchestrator
from core.orchestration.cache_orchestrator import CacheOrchestrator
from core.orchestration.hybrid_analysis_orchestrator import HybridAnalysisOrchestrator
from core.orchestration.query_policy import QueryPolicy

logger = logging.getLogger("mcp_powerbi_finvision")


class AgentPolicy:
    """
    Facade for orchestrator classes - maintains backward compatibility.

    This class delegates all method calls to specialized orchestrators.
    For new code, prefer using orchestrators directly for better clarity.
    """

    def __init__(self, config, timeout_manager=None, cache_manager=None, rate_limiter=None, limits_manager=None):
        self.config = config
        self.timeout_manager = timeout_manager
        self.cache_manager = cache_manager
        self.rate_limiter = rate_limiter
        self.limits_manager = limits_manager

        # Lazy-initialized orchestrators (created on-demand for faster startup)
        self._connection_orch = None
        self._query_orch = None
        self._documentation_orch = None
        self._analysis_orch = None
        self._pbip_orch = None
        self._cache_orch = None
        self._hybrid_orch = None
        self._query_policy = None

    @property
    def connection_orch(self):
        """Lazy-load connection orchestrator"""
        if self._connection_orch is None:
            self._connection_orch = ConnectionOrchestrator(self.config)
        return self._connection_orch

    @property
    def query_orch(self):
        """Lazy-load query orchestrator"""
        if self._query_orch is None:
            self._query_orch = QueryOrchestrator(self.config)
            # Initialize query policy if needed
            if self._query_policy is None:
                try:
                    self._query_policy = QueryPolicy(self.config)
                except Exception:
                    self._query_policy = None
            self._query_orch.query_policy = self._query_policy
        return self._query_orch

    @property
    def documentation_orch(self):
        """Lazy-load documentation orchestrator"""
        if self._documentation_orch is None:
            self._documentation_orch = DocumentationOrchestrator(self.config)
        return self._documentation_orch

    @property
    def analysis_orch(self):
        """Lazy-load analysis orchestrator"""
        if self._analysis_orch is None:
            self._analysis_orch = AnalysisOrchestrator(self.config)
        return self._analysis_orch

    @property
    def pbip_orch(self):
        """Lazy-load PBIP orchestrator"""
        if self._pbip_orch is None:
            self._pbip_orch = PbipOrchestrator(self.config)
        return self._pbip_orch

    @property
    def cache_orch(self):
        """Lazy-load cache orchestrator"""
        if self._cache_orch is None:
            self._cache_orch = CacheOrchestrator(self.config)
        return self._cache_orch

    @property
    def hybrid_orch(self):
        """Lazy-load hybrid analysis orchestrator"""
        if self._hybrid_orch is None:
            self._hybrid_orch = HybridAnalysisOrchestrator(self.config)
        return self._hybrid_orch

    @property
    def query_policy(self):
        """Lazy-load query policy"""
        if self._query_policy is None:
            try:
                self._query_policy = QueryPolicy(self.config)
            except Exception:
                pass
        return self._query_policy

    # ==================== CONNECTION ORCHESTRATOR DELEGATES ====================

    def ensure_connected(self, connection_manager, connection_state, preferred_index: Optional[int] = None) -> Dict[str, Any]:
        """Delegate to ConnectionOrchestrator."""
        return self.connection_orch.ensure_connected(connection_manager, connection_state, preferred_index)

    def agent_health(self, connection_manager, connection_state) -> Dict[str, Any]:
        """Delegate to ConnectionOrchestrator."""
        return self.connection_orch.agent_health(connection_manager, connection_state)

    def summarize_model_safely(self, connection_state) -> Dict[str, Any]:
        """Delegate to ConnectionOrchestrator."""
        return self.connection_orch.summarize_model_safely(connection_state)

    # ==================== QUERY ORCHESTRATOR DELEGATES ====================

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
        """Delegate to QueryOrchestrator."""
        return self.query_orch.safe_run_dax(
            connection_state, query, mode, runs, max_rows, verbose, bypass_cache, include_event_counts
        )

    def plan_query(self, intent: str, context_table: Optional[str] = None, max_rows: Optional[int] = None) -> Dict[str, Any]:
        """Delegate to QueryOrchestrator."""
        return self.query_orch.plan_query(intent, context_table, max_rows)

    def optimize_variants(
        self,
        connection_state,
        candidates: List[str],
        runs: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Delegate to QueryOrchestrator."""
        return self.query_orch.optimize_variants(connection_state, candidates, runs)

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
        """Delegate to QueryOrchestrator."""
        return self.query_orch.decide_and_run(
            connection_manager, connection_state, goal, query, candidates, runs, max_rows, verbose
        )

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
        """Delegate to QueryOrchestrator."""
        return self.query_orch.execute_intent(
            connection_manager, connection_state, goal, query, table, runs, max_rows, verbose, candidate_a, candidate_b
        )

    def auto_analyze_or_preview(self, connection_manager, connection_state, query: str, runs: Optional[int] = None, max_rows: Optional[int] = None, priority: str = 'depth') -> Dict[str, Any]:
        """Delegate to QueryOrchestrator."""
        return self.query_orch.auto_analyze_or_preview(connection_manager, connection_state, query, runs, max_rows, priority)

    # ==================== DOCUMENTATION ORCHESTRATOR DELEGATES ====================

    def generate_docs_safe(self, connection_state) -> Dict[str, Any]:
        """Delegate to DocumentationOrchestrator."""
        return self.documentation_orch.generate_docs_safe(connection_state)

    def generate_documentation_profiled(self, connection_state, format: str = 'markdown', include_examples: bool = False) -> Dict[str, Any]:
        """Delegate to DocumentationOrchestrator."""
        return self.documentation_orch.generate_documentation_profiled(connection_state, format, include_examples)

    def generate_model_documentation_word(
        self,
        connection_state,
        output_dir: Optional[str] = None,
        include_hidden: bool = True,
        dependency_depth: int = 1,
        export_pdf: bool = False,
    ) -> Dict[str, Any]:
        """Delegate to DocumentationOrchestrator."""
        return self.documentation_orch.generate_model_documentation_word(
            connection_state, output_dir, include_hidden, dependency_depth, export_pdf
        )

    def update_model_documentation_word(
        self,
        connection_state,
        output_dir: Optional[str] = None,
        snapshot_path: Optional[str] = None,
        include_hidden: bool = True,
        dependency_depth: int = 1,
        export_pdf: bool = False,
    ) -> Dict[str, Any]:
        """Delegate to DocumentationOrchestrator."""
        return self.documentation_orch.update_model_documentation_word(
            connection_state, output_dir, snapshot_path, include_hidden, dependency_depth, export_pdf
        )

    def export_interactive_relationship_graph(
        self,
        connection_state,
        output_dir: Optional[str] = None,
        include_hidden: bool = True,
        dependency_depth: int = 5,
    ) -> Dict[str, Any]:
        """Delegate to DocumentationOrchestrator."""
        return self.documentation_orch.export_interactive_relationship_graph(
            connection_state, output_dir, include_hidden, dependency_depth
        )

    def export_interactive_relationship_graph_legacy(
        self,
        connection_state,
        output_dir: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Delegate to DocumentationOrchestrator."""
        return self.documentation_orch.export_interactive_relationship_graph_legacy(connection_state, output_dir)

    def auto_document(self, connection_manager, connection_state, profile: str = 'light', include_lineage: bool = False) -> Dict[str, Any]:
        """Delegate to DocumentationOrchestrator."""
        return self.documentation_orch.auto_document(connection_manager, connection_state, profile, include_lineage)

    # ==================== ANALYSIS ORCHESTRATOR DELEGATES ====================

    def validate_best_practices(self, connection_state) -> Dict[str, Any]:
        """Delegate to AnalysisOrchestrator."""
        return self.analysis_orch.validate_best_practices(connection_state)

    def analyze_best_practices_unified(
        self,
        connection_state,
        mode: str = "all",
        bpa_profile: str = "balanced",
        max_seconds: Optional[int] = None
    ) -> Dict[str, Any]:
        """Delegate to AnalysisOrchestrator."""
        return self.analysis_orch.analyze_best_practices_unified(connection_state, mode, bpa_profile, max_seconds)

    def analyze_performance_unified(
        self,
        connection_state,
        mode: str = "comprehensive",
        queries: Optional[List[str]] = None,
        table: Optional[str] = None,
        runs: int = 3,
        clear_cache: bool = True,
        include_event_counts: bool = False
    ) -> Dict[str, Any]:
        """Delegate to AnalysisOrchestrator."""
        return self.analysis_orch.analyze_performance_unified(
            connection_state, mode, queries, table, runs, clear_cache, include_event_counts
        )

    def analyze_queries_batch(self, connection_state, queries: List[str], runs: Optional[int] = 3, clear_cache: bool = True, include_event_counts: bool = False) -> Dict[str, Any]:
        """Delegate to AnalysisOrchestrator."""
        return self.analysis_orch.analyze_queries_batch(connection_state, queries, runs, clear_cache, include_event_counts)

    def profile_columns(self, connection_state, table: str, columns: Optional[List[str]] = None) -> Dict[str, Any]:
        """Delegate to AnalysisOrchestrator."""
        return self.analysis_orch.profile_columns(connection_state, table, columns)

    def get_value_distribution(self, connection_state, table: str, column: str, top_n: int = 50) -> Dict[str, Any]:
        """Delegate to AnalysisOrchestrator."""
        return self.analysis_orch.get_value_distribution(connection_state, table, column, top_n)

    def relationship_overview(self, connection_state) -> Dict[str, Any]:
        """Delegate to AnalysisOrchestrator."""
        return self.analysis_orch.relationship_overview(connection_state)

    def get_measure_impact(self, connection_state, table: str, measure: str, depth: Optional[int] = 3) -> Dict[str, Any]:
        """Delegate to AnalysisOrchestrator."""
        return self.analysis_orch.get_measure_impact(connection_state, table, measure, depth)

    def propose_analysis_options(self, connection_state, goal: Optional[str] = None) -> Dict[str, Any]:
        """Delegate to AnalysisOrchestrator."""
        return self.analysis_orch.propose_analysis_options(connection_state, goal)

    def create_model_changelog(self, connection_state, reference_tmsl) -> Dict[str, Any]:
        """Create model changelog - legacy method."""
        from core.validation.error_handler import ErrorHandler
        if not connection_state.is_connected():
            return ErrorHandler.handle_not_connected()
        exporter = connection_state.model_exporter
        if not exporter:
            return ErrorHandler.handle_manager_unavailable('model_exporter')
        diff = exporter.compare_models(reference_tmsl)
        summary: Dict[str, Any] = {'notes': 'Summary generated by server'}
        if isinstance(diff, dict):
            keys_list = [str(k) for k in diff.keys()]
            summary['keys'] = keys_list
        return {'success': True, 'diff': diff, 'summary': summary}

    # ==================== PBIP ORCHESTRATOR DELEGATES ====================

    def analyze_pbip_repository_enhanced(
        self,
        repo_path: str,
        output_path: str = "exports/pbip_analysis",
        exclude_folders: Optional[List[str]] = None,
        bpa_rules_path: Optional[str] = "config/bpa_rules_comprehensive.json",
        enable_enhanced: bool = True
    ) -> Dict[str, Any]:
        """Delegate to PbipOrchestrator."""
        return self.pbip_orch.analyze_pbip_repository_enhanced(
            repo_path, output_path, exclude_folders, bpa_rules_path, enable_enhanced
        )

    def analyze_aggregation(
        self,
        pbip_path: str,
        output_format: str = "summary",
        output_path: Optional[str] = None,
        page_filter: Optional[str] = None,
        include_visual_details: bool = True,
        estimate_row_savings: bool = True,
        base_table_rows: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Delegate aggregation analysis to PbipOrchestrator.

        Analyzes aggregation table usage across visuals and pages, showing
        which aggregation tables are hit based on filter context.
        """
        return self.pbip_orch.analyze_aggregation(
            pbip_path, output_format, output_path, page_filter,
            include_visual_details, estimate_row_savings, base_table_rows
        )

    def get_column_lineage(
        self,
        repo_path: str,
        column_key: str,
        exclude_folders: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Delegate to PbipOrchestrator."""
        return self.pbip_orch.get_column_lineage(repo_path, column_key, exclude_folders)

    # ==================== CACHE ORCHESTRATOR DELEGATES ====================

    def warm_query_cache(self, connection_state, queries: List[str], runs: Optional[int] = 1, clear_cache: bool = False) -> Dict[str, Any]:
        """Delegate to CacheOrchestrator."""
        return self.cache_orch.warm_query_cache(connection_state, queries, runs, clear_cache)

    def set_cache_policy(self, connection_state, ttl_seconds: Optional[int] = None) -> Dict[str, Any]:
        """Delegate to CacheOrchestrator."""
        return self.cache_orch.set_cache_policy(connection_state, ttl_seconds)

    # ==================== LEGACY/UTILITY METHODS ====================

    def apply_recommended_fixes(self, connection_state, actions: List[str]) -> Dict[str, Any]:
        """Apply recommended fixes - returns plan only."""
        from core.validation.error_handler import ErrorHandler
        if not connection_state.is_connected():
            return ErrorHandler.handle_not_connected()
        plan = []
        for a in actions or []:
            if a == 'hide_keys':
                plan.append({'action': a, 'status': 'suggestion', 'note': 'Hide IsKey columns in report view'})
            elif a == 'fix_summarization':
                plan.append({'action': a, 'status': 'suggestion', 'note': 'Set default summarization for numeric columns appropriately'})
            elif a == 'organize_folders':
                plan.append({'action': a, 'status': 'suggestion', 'note': 'Group measures into display folders by subject'})
            else:
                plan.append({'action': a, 'status': 'unknown'})
        return {'success': True, 'plan': plan}

    def format_dax(self, expression: str) -> Dict[str, Any]:
        """Format DAX expression."""
        if expression is None:
            return {'success': False, 'error': 'No expression provided'}
        text = expression.strip()
        while '  ' in text:
            text = text.replace('  ', ' ')
        return {'success': True, 'formatted': text}

    def check_rate_limit(self, connection_state) -> Dict[str, Any]:
        """Check rate limiting status."""
        if self.rate_limiter:
            return self.rate_limiter.get_status()
        return {'success': True, 'rate_limiting': 'disabled'}

    def wrap_response_with_limits_info(self, result: Dict[str, Any], tool_name: str) -> Dict[str, Any]:
        """
        Wrap response with limits information including token usage estimation.

        Args:
            result: The tool result dictionary
            tool_name: Name of the tool being executed

        Returns:
            Result dictionary with added _limits_info metadata
        """
        if not self.limits_manager or not isinstance(result, dict):
            return result

        # Estimate token usage
        import json
        result_text = json.dumps(result)
        estimated_tokens = self.limits_manager.token.estimate_tokens(result_text)
        max_tokens = self.limits_manager.token.max_result_tokens
        percentage = f"{(estimated_tokens / max_tokens * 100):.1f}%"

        # Determine level
        if self.limits_manager.token.is_over_limit(estimated_tokens):
            level = "over"
        elif self.limits_manager.token.is_at_critical(estimated_tokens):
            level = "critical"
        elif self.limits_manager.token.is_at_warning(estimated_tokens):
            level = "warning"
        else:
            level = "ok"

        # Add limits info to result
        result['_limits_info'] = {
            'token_usage': {
                'estimated_tokens': estimated_tokens,
                'max_tokens': max_tokens,
                'percentage': percentage,
                'level': level
            },
            'tool_name': tool_name
        }

        return result

    def suggest_optimizations(self, tool_name: str, result: Dict[str, Any]) -> Optional[str]:
        """
        Suggest optimizations based on tool usage and result size.

        Args:
            tool_name: Name of the tool
            result: Tool result dictionary

        Returns:
            Optimization suggestion string or None
        """
        if not isinstance(result, dict):
            return None

        # Get token info if available
        limits_info = result.get('_limits_info', {})
        token_usage = limits_info.get('token_usage', {})
        level = token_usage.get('level', 'ok')

        # Suggest optimizations based on level and tool
        if level in ['warning', 'critical', 'over']:
            suggestions = []

            if tool_name in ['list_tables', 'list_columns', 'list_measures']:
                suggestions.append("Use 'limit' parameter to reduce result set size")

            if tool_name == 'describe_table':
                suggestions.append("Use 'include_columns=false' or 'include_measures=false' to reduce details")

            if tool_name == 'analyze_model_bpa':
                suggestions.append("Use filtering parameters to reduce result size")

            if tool_name == 'export_tmdl':
                suggestions.append("Export to file instead of returning full content")

            if suggestions:
                return " | ".join(suggestions)

        return None

    # Helper methods for backward compatibility
    def _get_preview_limit(self, max_rows: Optional[int]) -> int:
        if isinstance(max_rows, int) and max_rows > 0:
            return max_rows
        return self.config.get("query.max_rows_preview", 1000) or 1000

    def _get_default_perf_runs(self, runs: Optional[int]) -> int:
        if isinstance(runs, int) and runs > 0:
            return runs
        return 3
