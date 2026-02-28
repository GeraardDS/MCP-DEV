"""Performance and BPA analysis orchestration."""
import logging
import time
from typing import Any, Dict, List, Optional
from .base_orchestrator import BaseOrchestrator

logger = logging.getLogger(__name__)

class AnalysisOrchestrator(BaseOrchestrator):
    """Handles performance and BPA analysis workflows."""

    def validate_best_practices(self, connection_state) -> Dict[str, Any]:
        """Validate model best practices with simple naming checks."""
        from core.validation.error_handler import ErrorHandler

        if not connection_state.is_connected():
            return ErrorHandler.handle_not_connected()
        executor = connection_state.query_executor
        validator = connection_state.model_validator
        if not executor:
            return ErrorHandler.handle_manager_unavailable('query_executor')
        issues: List[Dict[str, Any]] = []
        # Include integrity issues if validator available
        if validator:
            integrity = validator.validate_model_integrity()
            if integrity.get('success'):
                for i in integrity.get('issues', []):
                    issues.append(i)
        # Simple naming checks
        tables = executor.execute_info_query('TABLES')
        if tables.get('success'):
            for t in tables.get('rows', []):
                name = t.get('Name') or ''
                if name != name.strip():
                    issues.append({'type': 'naming', 'severity': 'low', 'object': f"Table:{name}", 'description': 'Leading/trailing spaces in table name'})
        measures = executor.execute_info_query('MEASURES')
        if measures.get('success'):
            for m in measures.get('rows', []):
                name = m.get('Name') or ''
                if ' ' in name and name.strip().endswith(')'):
                    pass
                # Example heuristic: discourage very short names
                if len(name.strip()) < 2:
                    issues.append({'type': 'naming', 'severity': 'low', 'object': f"Measure:{name}", 'description': 'Very short measure name'})
        return {'success': True, 'issues': issues, 'total_issues': len(issues)}

    def analyze_queries_batch(self, connection_state, queries: List[str], runs: Optional[int] = 3, clear_cache: bool = True, include_event_counts: bool = False) -> Dict[str, Any]:
        """Run performance analysis on multiple queries in batch."""
        from core.validation.error_handler import ErrorHandler

        if not connection_state.is_connected():
            return ErrorHandler.handle_not_connected()
        executor = connection_state.query_executor
        perf = connection_state.performance_analyzer
        if not executor:
            return ErrorHandler.handle_manager_unavailable('query_executor')
        r = self._get_default_perf_runs(runs)
        results: List[Dict[str, Any]] = []
        for q in queries or []:
            if perf:
                results.append(perf.analyze_query(executor, q, r, bool(clear_cache), include_event_counts))
            else:
                # basic timing fallback
                start = time.time()
                res = executor.validate_and_execute_dax(q, 0)
                ms = (time.time() - start) * 1000
                results.append({'success': res.get('success', False), 'query': q, 'summary': {'avg_execution_ms': round(ms, 2), 'note': 'analyzer unavailable'}})
        return {'success': True, 'runs': r, 'items': results}

    def profile_columns(self, connection_state, table: str, columns: Optional[List[str]] = None) -> Dict[str, Any]:
        """Profile columns in a table with min/max/distinct/nulls stats."""
        from core.validation.error_handler import ErrorHandler

        if not connection_state.is_connected():
            return ErrorHandler.handle_not_connected()
        executor = connection_state.query_executor
        if not executor:
            return ErrorHandler.handle_manager_unavailable('query_executor')
        # Build per-column profiling queries
        cols = columns or []
        if not cols:
            # fetch all columns for table
            info = executor.execute_info_query('COLUMNS', table_name=table)
            if not info.get('success'):
                return info
            cols = [c.get('Name') for c in info.get('rows', []) if c.get('Name')]
        results: List[Dict[str, Any]] = []
        for col in cols[:200]:  # safety cap
            q = (
                f"EVALUATE ROW(\"Min\", MIN('{table}'[{col}]), "
                f"\"Max\", MAX('{table}'[{col}]), "
                f"\"Distinct\", DISTINCTCOUNT('{table}'[{col}]), "
                f"\"Nulls\", COUNTBLANK('{table}'[{col}]))"
            )
            r = executor.validate_and_execute_dax(q, 0)
            results.append({'column': col, 'success': r.get('success', False), 'stats': (r.get('rows') or [{}])[0] if r.get('rows') else {}})
        return {'success': True, 'table': table, 'columns': len(results), 'results': results}

    def get_value_distribution(self, connection_state, table: str, column: str, top_n: int = 50) -> Dict[str, Any]:
        """Get value distribution for a column."""
        from core.validation.error_handler import ErrorHandler

        if not connection_state.is_connected():
            return ErrorHandler.handle_not_connected()
        executor = connection_state.query_executor
        if not executor:
            return ErrorHandler.handle_manager_unavailable('query_executor')
        q = (
            f"EVALUATE TOPN({int(top_n)}, "
            f"SUMMARIZECOLUMNS('{table}'[{column}], \"Count\", COUNTROWS('{table}')), [Count], DESC)"
        )
        return executor.validate_and_execute_dax(q, 0)

    def relationship_overview(self, connection_state) -> Dict[str, Any]:
        """Return relationships list plus optional cardinality checks."""
        from core.validation.error_handler import ErrorHandler

        if not connection_state.is_connected():
            return ErrorHandler.handle_not_connected()
        executor = connection_state.query_executor
        if not executor:
            return ErrorHandler.handle_manager_unavailable('query_executor')
        rels = executor.execute_info_query('RELATIONSHIPS')
        result: Dict[str, Any] = {'success': bool(rels.get('success')), 'relationships': rels.get('rows', []), 'count': len(rels.get('rows', []) if rels.get('success') else [])}
        # Optionally attach issue analysis when available
        perf_opt = getattr(connection_state, 'performance_optimizer', None)
        try:
            if perf_opt:
                analysis = perf_opt.analyze_relationship_cardinality()
                result['analysis'] = analysis
        except Exception:
            # Non-fatal; just omit analysis
            pass
        return result

    def get_measure_impact(self, connection_state, table: str, measure: str, depth: Optional[int] = 3) -> Dict[str, Any]:
        """Get measure dependency impact analysis."""
        from core.validation.error_handler import ErrorHandler

        if not connection_state.is_connected():
            return ErrorHandler.handle_not_connected()
        dep = connection_state.dependency_analyzer
        if not dep:
            return ErrorHandler.handle_manager_unavailable('dependency_analyzer')
        return dep.analyze_measure_dependencies(table, measure, depth or 3)

    def propose_analysis_options(self, connection_state, goal: Optional[str] = None) -> Dict[str, Any]:
        """Return a simple decision card offering Fast vs Normal analysis."""
        # Determine if connected for realistic expectation
        connected = connection_state.is_connected()
        notes = []
        if not connected:
            notes.append("Not connected yet; choose an option to auto-connect and run.")
        options: List[Dict[str, Any]] = [
            {
                'name': 'Fast summary',
                'id': 'fast',
                'description': 'Very quick summary of model (tables, columns, measures, relationships) with relationship list.',
                'estimated_time': 'few seconds',
                'call': {
                    'tool': 'full_analysis',
                    'arguments': {
                        'profile': 'fast',
                        'depth': 'light',
                        'include_bpa': False,
                        'limits': {'relationships_max': 200, 'issues_max': 200}
                    }
                }
            },
            {
                'name': 'Normal analysis',
                'id': 'normal',
                'description': 'Comprehensive analysis including best practices and M scan; optionally BPA if available.',
                'estimated_time': 'tens of seconds',
                'call': {
                    'tool': 'full_analysis',
                    'arguments': {
                        'profile': 'balanced',
                        'depth': 'standard',
                        'include_bpa': True,
                        'limits': {'relationships_max': 200, 'issues_max': 200}
                    }
                }
            }
        ]
        return {
            'success': True,
            'decision': 'propose_analysis',
            'goal': goal,
            'connected': connected,
            'options': options,
            'notes': notes
        }

    def analyze_best_practices_unified(
        self,
        connection_state,
        mode: str = "all",
        bpa_profile: str = "balanced",
        max_seconds: Optional[int] = None
    ) -> Dict[str, Any]:
        """Unified best practices analysis combining BPA and M query practices."""
        from core.validation.error_handler import ErrorHandler

        if not connection_state.is_connected():
            return ErrorHandler.handle_not_connected()

        mode = (mode or "all").lower()
        results: Dict[str, Any] = {
            'success': True,
            'mode': mode,
            'analyses': {}
        }

        # Run BPA if requested
        if mode in ("all", "bpa"):
            bpa_analyzer = connection_state.bpa_analyzer
            if bpa_analyzer:
                try:
                    # Get TMSL definition first
                    query_executor = connection_state.query_executor
                    if not query_executor:
                        results['analyses']['bpa'] = {
                            'success': False,
                            'error': 'Query executor not available'
                        }
                    else:
                        tmsl_result = query_executor.get_tmsl_definition()
                        if not tmsl_result.get('success'):
                            results['analyses']['bpa'] = {
                                'success': False,
                                'error': f"Failed to get TMSL: {tmsl_result.get('error')}"
                            }
                        else:
                            # Run BPA analysis based on profile
                            tmsl_json = tmsl_result.get('tmsl')
                            if bpa_profile == "fast":
                                cfg = {
                                    'max_seconds': max_seconds or 10,
                                    'per_rule_max_ms': 100,
                                    'severity_at_least': 'WARNING'
                                }
                                violations = bpa_analyzer.analyze_model_fast(tmsl_json, cfg)
                            elif bpa_profile == "deep":
                                violations = bpa_analyzer.analyze_model(tmsl_json)
                            else:  # balanced
                                cfg = {
                                    'max_seconds': max_seconds or 20,
                                    'per_rule_max_ms': 150
                                }
                                violations = bpa_analyzer.analyze_model_fast(tmsl_json, cfg)

                            results['analyses']['bpa'] = {
                                'success': True,
                                'violations': [vars(v) for v in violations],
                                'violation_count': len(violations),
                                'summary': bpa_analyzer.get_violations_summary(),
                                'notes': bpa_analyzer.get_run_notes()
                            }
                except Exception as e:
                    results['analyses']['bpa'] = {
                        'success': False,
                        'error': f'BPA analysis failed: {str(e)}'
                    }
            else:
                results['analyses']['bpa'] = {
                    'success': True,
                    'skipped': True,
                    'reason': 'BPA analyzer not available - dependencies not installed',
                    'note': 'To enable BPA analysis, install Best Practice Analyzer dependencies',
                    'violations': [],
                    'violation_count': 0
                }

        # Run M query practices scan if requested
        if mode in ("all", "m_queries"):
            try:
                from core.analysis.m_practices import scan_m_practices
                m_result = scan_m_practices(connection_state.query_executor)
                results['analyses']['m_practices'] = m_result
            except Exception as e:
                results['analyses']['m_practices'] = {
                    'success': False,
                    'error': f'M practices scan failed: {str(e)}'
                }

        # Aggregate summary
        total_issues = 0
        for analysis_name, analysis_result in results['analyses'].items():
            if isinstance(analysis_result, dict):
                issues_count = analysis_result.get('total_issues', 0) or len(analysis_result.get('issues', []))
                total_issues += issues_count

        results['total_issues'] = total_issues
        results['summary'] = f'Found {total_issues} total issues across {len(results["analyses"])} analyses'

        return results

    def analyze_performance_unified(
        self,
        connection_state
    ) -> Dict[str, Any]:
        """Performance analysis focused on relationship and column cardinality."""
        from core.validation.error_handler import ErrorHandler

        if not connection_state.is_connected():
            return ErrorHandler.handle_not_connected()

        performance_optimizer = connection_state.performance_optimizer

        results: Dict[str, Any] = {
            'success': True,
            'analyses': {}
        }

        # Always run cardinality analysis
        if performance_optimizer:
            try:
                # Relationship cardinality analysis
                rel_card = performance_optimizer.analyze_relationship_cardinality()
                results['analyses']['relationship_cardinality'] = rel_card
            except Exception as e:
                results['analyses']['cardinality_error'] = {
                    'success': False,
                    'error': f'Cardinality analysis failed: {str(e)}'
                }
        else:
            results['analyses']['cardinality'] = {
                'success': False,
                'error': 'Performance optimizer not available'
            }

        # Generate summary
        analysis_count = len([a for a in results['analyses'].values() if isinstance(a, dict) and a.get('success')])
        results['summary'] = f'Completed {analysis_count} performance analyses'

        return results

    def _get_default_perf_runs(self, runs: Optional[int]) -> int:
        """Get default performance analysis run count."""
        if isinstance(runs, int) and runs > 0:
            return runs
        return self.config.get("performance.default_runs", 3) or 3

    def full_analysis(self, connection_state, summary_only: bool = False) -> Dict[str, Any]:
        """
        Comprehensive model analysis.
        Alias that delegates to the appropriate analysis methods.
        """
        from core.validation.error_handler import ErrorHandler

        if not connection_state.is_connected():
            return ErrorHandler.handle_not_connected()

        results: Dict[str, Any] = {
            'success': True,
            'summary_only': summary_only,
            'analyses': {}
        }

        # Get basic best practices validation
        try:
            bp_result = self.validate_best_practices(connection_state)
            results['analyses']['best_practices'] = bp_result
        except Exception as e:
            results['analyses']['best_practices'] = {
                'success': False,
                'error': f'Best practices analysis failed: {str(e)}'
            }

        # Get relationship overview
        try:
            rel_result = self.relationship_overview(connection_state)
            results['analyses']['relationships'] = rel_result
        except Exception as e:
            results['analyses']['relationships'] = {
                'success': False,
                'error': f'Relationship analysis failed: {str(e)}'
            }

        # If not summary_only, run more detailed analysis
        if not summary_only:
            try:
                bpa_result = self.analyze_best_practices_unified(connection_state, mode="all")
                results['analyses']['bpa_unified'] = bpa_result
            except Exception as e:
                results['analyses']['bpa_unified'] = {
                    'success': False,
                    'error': f'Unified BPA analysis failed: {str(e)}'
                }

        return results

    def comprehensive_analysis(
        self,
        connection_state,
        scope: str = "all",
        depth: str = "balanced",
        include_bpa: bool = True,
        include_performance: bool = True,
        include_integrity: bool = True,
        max_seconds: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Unified comprehensive model analysis combining best practices, performance, and integrity checks.

        Args:
            connection_state: Current connection state
            scope: Analysis scope - "all", "best_practices", "performance", "integrity"
            depth: Analysis depth - "fast", "balanced", "deep"
            include_bpa: Whether to run BPA analysis (requires dependencies)
            include_performance: Whether to run performance analysis
            include_integrity: Whether to run integrity validation
            max_seconds: Maximum execution time (optional)

        Returns:
            Comprehensive analysis results with all requested analyses
        """
        from core.validation.error_handler import ErrorHandler

        if not connection_state.is_connected():
            return ErrorHandler.handle_not_connected()

        scope = (scope or "all").lower()
        depth = (depth or "balanced").lower()

        results: Dict[str, Any] = {
            'success': True,
            'scope': scope,
            'depth': depth,
            'analyses': {},
            'start_time': time.time()
        }

        # Determine what to run based on scope
        run_bp = scope in ("all", "best_practices")
        run_perf = scope in ("all", "performance") and include_performance
        run_integrity = scope in ("all", "integrity") and include_integrity

        # 1. Model Integrity Validation
        if run_integrity:
            try:
                validator = connection_state.model_validator
                if validator:
                    integrity_result = validator.validate_model_integrity()
                    results['analyses']['integrity'] = integrity_result
                else:
                    results['analyses']['integrity'] = {
                        'success': False,
                        'error': 'Model validator not available'
                    }
            except Exception as e:
                logger.error(f"Integrity validation failed: {e}")
                results['analyses']['integrity'] = {
                    'success': False,
                    'error': f'Integrity validation failed: {str(e)}'
                }

        # 2. Best Practice Analyzer (BPA)
        if run_bp and include_bpa:
            try:
                bpa_analyzer = connection_state.bpa_analyzer
                query_executor = connection_state.query_executor

                if bpa_analyzer and query_executor:
                    # Get TMSL definition
                    tmsl_result = query_executor.get_tmsl_definition()

                    if tmsl_result.get('success'):
                        tmsl_json = tmsl_result.get('tmsl')

                        # Configure BPA based on depth
                        if depth == "fast":
                            cfg = {
                                'max_seconds': max_seconds or 10,
                                'per_rule_max_ms': 100,
                                'severity_at_least': 'WARNING'
                            }
                            violations = bpa_analyzer.analyze_model_fast(tmsl_json, cfg)
                        elif depth == "deep":
                            violations = bpa_analyzer.analyze_model(tmsl_json)
                        else:  # balanced
                            cfg = {
                                'max_seconds': max_seconds or 20,
                                'per_rule_max_ms': 150
                            }
                            violations = bpa_analyzer.analyze_model_fast(tmsl_json, cfg)

                        results['analyses']['bpa'] = {
                            'success': True,
                            'violations': [vars(v) for v in violations],
                            'violation_count': len(violations),
                            'summary': bpa_analyzer.get_violations_summary(),
                            'notes': bpa_analyzer.get_run_notes()
                        }
                    else:
                        results['analyses']['bpa'] = {
                            'success': False,
                            'error': f"Failed to get TMSL: {tmsl_result.get('error')}"
                        }
                else:
                    results['analyses']['bpa'] = {
                        'success': True,
                        'skipped': True,
                        'reason': 'BPA analyzer not available - dependencies not installed',
                        'violations': [],
                        'violation_count': 0
                    }
            except Exception as e:
                logger.error(f"BPA analysis failed: {e}")
                results['analyses']['bpa'] = {
                    'success': False,
                    'error': f'BPA analysis failed: {str(e)}'
                }

        # 3. M Query Practices
        if run_bp:
            try:
                from core.analysis.m_practices import scan_m_practices
                query_executor = connection_state.query_executor

                if query_executor:
                    m_result = scan_m_practices(query_executor)
                    results['analyses']['m_practices'] = m_result
                else:
                    results['analyses']['m_practices'] = {
                        'success': False,
                        'error': 'Query executor not available'
                    }
            except Exception as e:
                logger.error(f"M practices scan failed: {e}")
                results['analyses']['m_practices'] = {
                    'success': False,
                    'error': f'M practices scan failed: {str(e)}'
                }

        # 4. Performance Analysis (Cardinality)
        if run_perf:
            try:
                performance_optimizer = connection_state.performance_optimizer

                if performance_optimizer:
                    rel_card = performance_optimizer.analyze_relationship_cardinality()
                    results['analyses']['performance'] = rel_card
                else:
                    results['analyses']['performance'] = {
                        'success': False,
                        'error': 'Performance optimizer not available'
                    }
            except Exception as e:
                logger.error(f"Performance analysis failed: {e}")
                results['analyses']['performance'] = {
                    'success': False,
                    'error': f'Performance analysis failed: {str(e)}'
                }

        # 5. Relationship Overview (always included for context)
        try:
            query_executor = connection_state.query_executor
            if query_executor:
                rels = query_executor.execute_info_query('RELATIONSHIPS')
                results['analyses']['relationships'] = {
                    'success': bool(rels.get('success')),
                    'count': len(rels.get('rows', [])),
                    'relationships': rels.get('rows', [])
                }
        except Exception as e:
            logger.error(f"Relationship overview failed: {e}")
            results['analyses']['relationships'] = {
                'success': False,
                'error': f'Relationship overview failed: {str(e)}'
            }

        # Calculate execution time
        results['execution_time_seconds'] = round(time.time() - results['start_time'], 2)
        del results['start_time']

        # Aggregate summary
        total_issues = 0
        successful_analyses = 0

        for analysis_name, analysis_result in results['analyses'].items():
            if isinstance(analysis_result, dict):
                if analysis_result.get('success'):
                    successful_analyses += 1

                # Count issues from different analysis types
                if analysis_name == 'integrity':
                    total_issues += analysis_result.get('total_issues', 0)
                elif analysis_name == 'bpa':
                    total_issues += analysis_result.get('violation_count', 0)
                elif analysis_name == 'm_practices':
                    total_issues += analysis_result.get('total_issues', 0)
                elif analysis_name == 'performance':
                    # Count high/critical performance issues
                    issues = analysis_result.get('issues', [])
                    if isinstance(issues, list):
                        total_issues += len([i for i in issues if isinstance(i, dict) and i.get('severity') in ('high', 'critical')])

        results['summary'] = {
            'total_issues': total_issues,
            'successful_analyses': successful_analyses,
            'total_analyses': len(results['analyses']),
            'recommendation': self._get_recommendation(total_issues, results['analyses'])
        }

        return results

    def _get_recommendation(self, total_issues: int, analyses: Dict[str, Any]) -> str:
        """Generate recommendation based on analysis results."""
        if total_issues == 0:
            return "Model is in good shape. No critical issues found."

        # Check for critical issues
        critical_count = 0
        high_count = 0

        if 'integrity' in analyses and isinstance(analyses['integrity'], dict):
            summary = analyses['integrity'].get('summary', {})
            if isinstance(summary, dict):
                critical_count += summary.get('critical_issues', 0)
                high_count += summary.get('high_issues', 0)

        if 'bpa' in analyses and isinstance(analyses['bpa'], dict):
            violations = analyses['bpa'].get('violations', [])
            for v in violations:
                if isinstance(v, dict):
                    severity = v.get('Severity', '').upper()
                    if 'ERROR' in severity or 'CRITICAL' in severity:
                        critical_count += 1
                    elif 'WARNING' in severity or 'HIGH' in severity:
                        high_count += 1

        if critical_count > 0:
            return f"CRITICAL: Found {critical_count} critical issues. Address immediately before deployment."
        elif high_count > 0:
            return f"WARNING: Found {high_count} high-priority issues. Review and fix before production use."
        else:
            return f"Found {total_issues} issues (low/medium severity). Consider addressing for optimization."

    def analyze_best_practices(self, connection_state, summary_only: bool = False) -> Dict[str, Any]:
        """
        Alias for comprehensive_analysis focused on best practices.
        """
        return self.comprehensive_analysis(
            connection_state,
            scope="best_practices",
            depth="balanced" if not summary_only else "fast",
            include_bpa=True,
            include_performance=False,
            include_integrity=True
        )

    def analyze_performance(self, connection_state) -> Dict[str, Any]:
        """
        Alias for comprehensive_analysis focused on performance.
        """
        return self.comprehensive_analysis(
            connection_state,
            scope="performance",
            depth="balanced",
            include_bpa=False,
            include_performance=True,
            include_integrity=False
        )

    def validate_model_integrity(self, connection_state) -> Dict[str, Any]:
        """
        Validate model integrity - now delegates to comprehensive_analysis.

        Returns only the integrity analysis results for backward compatibility.
        """
        result = self.comprehensive_analysis(
            connection_state,
            scope="integrity",
            depth="balanced",
            include_bpa=False,
            include_performance=False,
            include_integrity=True
        )

        # Extract just the integrity analysis for backward compatibility
        if result.get('success') and 'integrity' in result.get('analyses', {}):
            integrity_result = result['analyses']['integrity']
            # Add execution metadata
            integrity_result['execution_time_seconds'] = result.get('execution_time_seconds')
            return integrity_result

        return result

    def _infer_table_type(self, table_name: str) -> str:
        """
        Infer table type from naming convention.

        Common prefixes in Power BI models:
        - d_: dimension tables
        - f_: fact tables
        - m_: measure tables
        - s_: support/slicer tables
        - c_: calculation groups
        - r_: RLS (Row-Level Security) tables
        - sfp_/dfp_: field parameters
        - dyn_: dynamic tables

        Args:
            table_name: Name of the table

        Returns:
            Table type category as string
        """
        name_lower = table_name.lower()

        if name_lower.startswith('d_'):
            return 'dimension'
        elif name_lower.startswith('f_'):
            return 'fact'
        elif name_lower.startswith('m_'):
            return 'measure'
        elif name_lower.startswith('s_'):
            return 'support'
        elif name_lower.startswith('c_'):
            return 'calculation_group'
        elif name_lower.startswith('r_'):
            return 'rls'
        elif name_lower.startswith('sfp_') or name_lower.startswith('dfp_'):
            return 'field_parameter'
        elif name_lower.startswith('dyn_'):
            return 'dynamic'
        else:
            return 'other'

    def list_tables_simple(self, connection_state) -> Dict[str, Any]:
        """
        Ultra-fast table list (< 500ms).

        Similar to Microsoft MCP Server's List operation.
        Returns table names with basic counts only.

        Args:
            connection_state: Current connection state

        Returns:
            {
                'success': True,
                'analysis_type': 'table_list',
                'execution_time_seconds': 0.25,
                'message': 'Found 109 tables',
                'table_count': 109,
                'tables': [
                    {
                        'name': 'd_Company',
                        'column_count': 5,
                        'partition_count': 1
                    },
                    {
                        'name': 'm_Measures',
                        'column_count': 1,
                        'measure_count': 224,
                        'partition_count': 1
                    }
                ]
            }
        """
        from core.validation.error_handler import ErrorHandler

        if not connection_state.is_connected():
            return ErrorHandler.handle_not_connected()

        start_time = time.time()
        executor = connection_state.query_executor

        if not executor:
            return ErrorHandler.handle_manager_unavailable('query_executor')

        try:
            # Get tables (already cached in most cases)
            # Use high top_n to ensure we get ALL tables (not just default 100)
            tables_result = executor.execute_info_query('TABLES', top_n=10000)

            if not tables_result.get('success'):
                return tables_result

            # Build simple table list
            tables = []
            for table in tables_result.get('rows', []):
                table_info = {
                    'name': table.get('Name', ''),
                    'column_count': table.get('ColumnCount', 0),
                    'partition_count': table.get('PartitionCount', 1)
                }

                # Include measure count if > 0 (matching Microsoft MCP behavior)
                measure_count = table.get('MeasureCount', 0)
                if measure_count > 0:
                    table_info['measure_count'] = measure_count

                tables.append(table_info)

            execution_time = round(time.time() - start_time, 2)

            return {
                'success': True,
                'analysis_type': 'table_list',
                'execution_time_seconds': execution_time,
                'message': f'Found {len(tables)} tables',
                'table_count': len(tables),
                'data': tables  # Changed from 'tables' to 'data' for consistency with other operations
            }

        except Exception as e:
            logger.error(f"Table list failed: {e}")
            return {
                'success': False,
                'error': f'Table list failed: {str(e)}'
            }

    def simple_model_analysis(self, connection_state) -> Dict[str, Any]:
        """
        Fast model statistics overview (< 1 second).

        Similar to Microsoft MCP Server's GetStats operation.
        Provides comprehensive model metadata and counts without heavy analysis.

        Args:
            connection_state: Current connection state

        Returns:
            {
                'success': True,
                'analysis_type': 'simple_stats',
                'execution_time_seconds': 0.45,
                'model': {
                    'name': 'Model',
                    'database': 'guid',
                    'compatibility_level': 1601,
                    'compatibility_version': 'Power BI 2025'
                },
                'counts': {
                    'tables': 109,
                    'columns': 833,
                    'measures': 239,
                    'relationships': 91,
                    'partitions': 109,
                    'roles': 1,
                    'data_sources': 0,
                    'cultures': 1,
                    'perspectives': 0,
                    'calculation_groups': 5
                },
                'tables': [...],
                'summary': {...}
            }
        """
        from core.validation.error_handler import ErrorHandler

        if not connection_state.is_connected():
            return ErrorHandler.handle_not_connected()

        start_time = time.time()
        executor = connection_state.query_executor

        if not executor:
            return ErrorHandler.handle_manager_unavailable('query_executor')

        try:
            # Step 1: Get all object counts (matching Microsoft MCP GetStats)
            # Use high top_n limits to ensure we get ALL objects (not just default 100)
            model_info = executor.execute_info_query('MODEL', top_n=10)
            tables = executor.execute_info_query('TABLES', top_n=10000)  # Support large models
            measures = executor.execute_info_query('MEASURES', top_n=10000)  # Support many measures
            columns = executor.execute_info_query('COLUMNS', top_n=20000)  # Support many columns
            relationships = executor.execute_info_query('RELATIONSHIPS', top_n=5000)  # Support complex models
            partitions = executor.execute_info_query('PARTITIONS', top_n=10000)  # One partition per table typically
            roles = executor.execute_info_query('ROLES', top_n=1000)  # Support many roles
            calc_groups = executor.execute_info_query('CALCULATION_GROUPS', top_n=1000)  # Support many calc groups

            # Try to get optional counts (may not be available in all model versions)
            data_sources = executor.execute_info_query('DATA_SOURCES')
            cultures = executor.execute_info_query('CULTURES')
            perspectives = executor.execute_info_query('PERSPECTIVES')

            # Step 2: Extract model metadata
            model_data = model_info.get('rows', [{}])[0] if model_info.get('success') else {}
            model = {
                'name': model_data.get('Name', 'Model'),
                'database': model_data.get('Database', ''),
                'compatibility_level': model_data.get('CompatibilityLevel', 0)
            }

            # Add compatibility version description
            compat_level = model['compatibility_level']
            if compat_level >= 1601:
                model['compatibility_version'] = 'Power BI 2025'
            elif compat_level >= 1600:
                model['compatibility_version'] = 'Power BI 2021+'
            elif compat_level >= 1500:
                model['compatibility_version'] = 'SQL Server 2019 / Power BI'
            elif compat_level >= 1400:
                model['compatibility_version'] = 'SQL Server 2017 / Power BI'
            elif compat_level >= 1200:
                model['compatibility_version'] = 'SQL Server 2016 / Power BI'
            else:
                model['compatibility_version'] = 'Unknown'

            # Step 3: Aggregate counts (matching Microsoft MCP GetStats exactly)
            counts = {
                'tables': len(tables.get('rows', [])),
                'columns': len(columns.get('rows', [])),
                'measures': len(measures.get('rows', [])),
                'relationships': len(relationships.get('rows', [])),
                'partitions': len(partitions.get('rows', [])),
                'roles': len(roles.get('rows', [])),
                'data_sources': len(data_sources.get('rows', [])) if data_sources.get('success') else 0,
                'cultures': len(cultures.get('rows', [])) if cultures.get('success') else 1,
                'perspectives': len(perspectives.get('rows', [])) if perspectives.get('success') else 0,
                'calculation_groups': len(calc_groups.get('rows', []))
            }

            # Step 4: Per-table analysis
            tables_detailed = []
            for table in tables.get('rows', []):
                table_name = table.get('Name', '')

                # Infer table type from prefix (our enhancement for categorization)
                table_type = self._infer_table_type(table_name)

                # Build table info matching Microsoft MCP GetStats format
                table_info = {
                    'name': table_name,
                    'type': table_type,  # Our enhancement
                    'column_count': table.get('ColumnCount', 0),
                    'partition_count': table.get('PartitionCount', 1),
                    'is_hidden': table.get('IsHidden', False)
                }

                # Include measure_count only if > 0 (matching Microsoft MCP behavior)
                measure_count = table.get('MeasureCount', 0)
                if measure_count > 0:
                    table_info['measure_count'] = measure_count

                tables_detailed.append(table_info)

            # Step 5: Generate summary
            # Identify measure tables (tables with high measure:column ratio)
            measure_tables = [t['name'] for t in tables_detailed
                             if t.get('measure_count', 0) > 0 and t['column_count'] < 5]

            # Find largest tables by column count
            largest_tables = sorted(tables_detailed,
                                   key=lambda t: t['column_count'],
                                   reverse=True)[:5]
            largest_tables = [{'name': t['name'], 'column_count': t['column_count']}
                             for t in largest_tables]

            # Count table types
            table_types = {}
            for t in tables_detailed:
                table_type = t['type']
                table_types[table_type] = table_types.get(table_type, 0) + 1

            summary = {
                'total_objects': (counts['tables'] + counts['columns'] +
                                 counts['measures'] + counts['relationships']),
                'measure_tables': measure_tables,
                'largest_tables': largest_tables,
                'table_types': table_types
            }

            execution_time = round(time.time() - start_time, 2)

            return {
                'success': True,
                'analysis_type': 'simple_stats',
                'execution_time_seconds': execution_time,
                'model': model,
                'counts': counts,
                'tables': tables_detailed,
                'summary': summary
            }

        except Exception as e:
            logger.error(f"Simple model analysis failed: {e}")
            return {
                'success': False,
                'error': f'Simple model analysis failed: {str(e)}'
            }

    def list_measures_simple(self, connection_state, table_name: str = None, max_results: int = None) -> Dict[str, Any]:
        """
        List measures with optional table filter.
        Microsoft MCP Measure List operation.

        Args:
            connection_state: Current connection state
            table_name: Optional table filter
            max_results: Optional limit on results

        Returns:
            {
                'success': True,
                'message': 'Found 30 measures in table "m_Measures"',
                'operation': 'List',
                'tableName': 'm_Measures',
                'data': [
                    {
                        'displayFolder': 'Financial Model\\1.3 Base measures Balance Sheet',
                        'name': 'PL-COL-Background'
                    }
                ],
                'warnings': ['Results truncated: Showing 30 of 224 measures']
            }
        """
        from core.validation.error_handler import ErrorHandler

        if not connection_state.is_connected():
            return ErrorHandler.handle_not_connected()

        executor = connection_state.query_executor
        if not executor:
            return ErrorHandler.handle_manager_unavailable('query_executor')

        try:
            # Get measures
            result = executor.execute_info_query('MEASURES', table_name=table_name, exclude_columns=['Expression'])

            if not result.get('success'):
                return result

            rows = result.get('rows', [])
            total_count = len(rows)

            # Build measure list (name and displayFolder only for List operation)
            measures = []
            for row in rows:
                measure_info = {
                    'name': row.get('Name', ''),
                    'displayFolder': row.get('DisplayFolder', '')
                }
                measures.append(measure_info)

            # Apply max_results if specified
            truncated = False
            if max_results and len(measures) > max_results:
                measures = measures[:max_results]
                truncated = True

            # Build response matching Microsoft MCP format
            response = {
                'success': True,
                'operation': 'List'
            }

            # Message format
            if table_name:
                response['message'] = f'Found {len(measures)} measures in table \'{table_name}\''
                response['tableName'] = table_name
            else:
                response['message'] = f'Found {len(measures)} measures'

            response['data'] = measures

            # Add warning if truncated
            if truncated:
                response['warnings'] = [
                    f'Results truncated: Showing {len(measures)} of {total_count} measures (limited by MaxResults={max_results})'
                ]

            return response

        except Exception as e:
            logger.error(f"List measures failed: {e}")
            return {
                'success': False,
                'error': f'List measures failed: {str(e)}'
            }

    def get_measure_simple(self, connection_state, table_name: str, measure_name: str) -> Dict[str, Any]:
        """
        Get detailed measure information including DAX expression.
        Microsoft MCP Measure Get operation.

        Args:
            connection_state: Current connection state
            table_name: Table containing the measure
            measure_name: Measure name to retrieve

        Returns:
            {
                'success': True,
                'message': 'Measure "PL-AMT-BASE Scenario" retrieved successfully',
                'operation': 'Get',
                'measureName': 'PL-AMT-BASE Scenario',
                'tableName': 'm_Measures',
                'data': {
                    'tableName': 'm_Measures',
                    'name': 'PL-AMT-BASE Scenario',
                    'expression': '...',
                    'description': '',
                    'formatString': '',
                    'isHidden': False,
                    'displayFolder': '...',
                    ...
                }
            }
        """
        from core.validation.error_handler import ErrorHandler

        if not connection_state.is_connected():
            return ErrorHandler.handle_not_connected()

        executor = connection_state.query_executor
        if not executor:
            return ErrorHandler.handle_manager_unavailable('query_executor')

        if not table_name or not measure_name:
            return {
                'success': False,
                'error': 'table_name and measure_name are required'
            }

        try:
            # Use the existing get_measure_details_with_fallback
            result = executor.get_measure_details_with_fallback(table_name, measure_name)

            if not result.get('success'):
                return result

            measure_data = result.get('measure', {})

            # Build response matching Microsoft MCP format
            return {
                'success': True,
                'message': f'Measure \'{measure_name}\' retrieved successfully',
                'operation': 'Get',
                'measureName': measure_name,
                'tableName': table_name,
                'data': measure_data
            }

        except Exception as e:
            logger.error(f"Get measure failed: {e}")
            return {
                'success': False,
                'error': f'Get measure failed: {str(e)}'
            }

    def _map_cardinality(self, value) -> str:
        """
        Map numeric cardinality values to readable names.
        Microsoft MCP format uses 'One' and 'Many' instead of numeric values.

        Args:
            value: Cardinality value (can be int, str, or None)

        Returns:
            Readable cardinality name: 'One', 'Many', or original value if unknown
        """
        if value is None:
            return 'One'  # Default

        # Handle numeric values
        if isinstance(value, int):
            mapping = {1: 'One', 2: 'Many'}
            return mapping.get(value, str(value))

        # Handle string values
        if isinstance(value, str):
            # If already readable, return as-is
            if value in ['One', 'Many']:
                return value
            # Try to convert to int first
            try:
                num_value = int(value)
                mapping = {1: 'One', 2: 'Many'}
                return mapping.get(num_value, value)
            except (ValueError, TypeError):
                return value

        return str(value)

    def list_relationships_simple(self, connection_state, active_only: bool = False) -> Dict[str, Any]:
        """
        List all relationships with full metadata.
        Microsoft MCP Relationship List operation.

        Args:
            connection_state: Current connection state
            active_only: If True, only return active relationships

        Returns:
            {
                'success': True,
                'message': 'Found 91 relationships',
                'operation': 'LIST',
                'data': [
                    {
                        'fromTable': 'f_FINREP',
                        'fromColumn': '#Company Code',
                        'toTable': 'd_Company',
                        'toColumn': 'Company Code',
                        'isActive': True,
                        'crossFilteringBehavior': 'OneDirection',
                        'fromCardinality': 'Many',
                        'toCardinality': 'One',
                        'name': '70c38ab1-00b9-bb04-7903-4027e569f76e'
                    }
                ]
            }
        """
        from core.validation.error_handler import ErrorHandler

        if not connection_state.is_connected():
            return ErrorHandler.handle_not_connected()

        executor = connection_state.query_executor
        if not executor:
            return ErrorHandler.handle_manager_unavailable('query_executor')

        try:
            # Get relationships
            result = executor.execute_info_query('RELATIONSHIPS')

            if not result.get('success'):
                return result

            rows = result.get('rows', [])

            # Filter for active only if requested
            if active_only:
                rows = [r for r in rows if r.get('IsActive')]

            # Build relationship list matching Microsoft MCP format
            relationships = []
            for row in rows:
                # Get cardinality values and map to readable names
                from_card = self._map_cardinality(row.get('FromCardinality'))
                to_card = self._map_cardinality(row.get('ToCardinality'))

                rel_info = {
                    'fromTable': row.get('FromTable', row.get('FromTableName', '')),
                    'fromColumn': row.get('FromColumn', row.get('FromColumnName', '')),
                    'toTable': row.get('ToTable', row.get('ToTableName', '')),
                    'toColumn': row.get('ToColumn', row.get('ToColumnName', '')),
                    'isActive': row.get('IsActive', False),
                    'crossFilteringBehavior': row.get('CrossFilteringBehavior', 'OneDirection'),
                    'fromCardinality': from_card,
                    'toCardinality': to_card,
                    'name': row.get('Name', '')
                }
                relationships.append(rel_info)

            # Build response matching Microsoft MCP format
            return {
                'success': True,
                'message': f'Found {len(relationships)} relationships',
                'operation': 'LIST',
                'data': relationships
            }

        except Exception as e:
            logger.error(f"List relationships failed: {e}")
            return {
                'success': False,
                'error': f'List relationships failed: {str(e)}'
            }

    def list_calculation_groups_simple(self, connection_state) -> Dict[str, Any]:
        """
        List all calculation groups with their items.
        Microsoft MCP Calculation Group ListGroups operation.

        Uses the CalculationGroupManager for robust calculation group retrieval.

        Args:
            connection_state: Current connection state

        Returns:
            {
                'success': True,
                'message': 'Found 5 calculation groups',
                'operation': 'ListGroups',
                'data': [
                    {
                        'calculationItems': [
                            {'ordinal': 0, 'name': 'MTD'},
                            {'ordinal': 1, 'name': 'QTD'}
                        ],
                        'name': 'c_Time Intelligence P&L'
                    }
                ]
            }
        """
        from core.validation.error_handler import ErrorHandler

        if not connection_state.is_connected():
            return ErrorHandler.handle_not_connected()

        calc_group_manager = connection_state.calc_group_manager
        if not calc_group_manager:
            return ErrorHandler.handle_manager_unavailable('calc_group_manager')

        try:
            # Use the dedicated CalculationGroupManager which has robust DAX + AMO fallback
            result = calc_group_manager.list_calculation_groups()

            if not result.get('success'):
                # If listing failed, return empty list with success=True (model may have no calc groups)
                return {
                    'success': True,
                    'message': 'Found 0 calculation groups',
                    'operation': 'ListGroups',
                    'data': [],
                    'note': result.get('error', 'Unable to query calculation groups')
                }

            # Convert from CalculationGroupManager format to Microsoft MCP format
            calc_groups = result.get('calculation_groups', [])
            mcp_groups = []

            for cg in calc_groups:
                # Convert items to MCP format (simplified - just ordinal and name)
                calc_items = []
                for item in cg.get('items', []):
                    calc_items.append({
                        'ordinal': item.get('ordinal', 0),
                        'name': item.get('name', '')
                    })

                # Sort by ordinal
                calc_items.sort(key=lambda x: x['ordinal'])

                mcp_groups.append({
                    'name': cg.get('name', cg.get('table', '')),
                    'calculationItems': calc_items
                })

            # Build response matching Microsoft MCP format
            return {
                'success': True,
                'message': f'Found {len(mcp_groups)} calculation groups',
                'operation': 'ListGroups',
                'data': mcp_groups
            }

        except Exception as e:
            logger.error(f"List calculation groups failed: {e}")
            # Return empty list rather than error (model may have no calc groups)
            return {
                'success': True,
                'message': 'Found 0 calculation groups',
                'operation': 'ListGroups',
                'data': [],
                'note': f'Calculation group query failed: {str(e)}'
            }

    def list_columns_simple(self, connection_state, table_name: str = None, max_results: int = None) -> Dict[str, Any]:
        """
        List columns across tables or for a specific table.
        Microsoft MCP Column List operation.

        Args:
            connection_state: Current connection state
            table_name: Optional table filter
            max_results: Optional limit on results

        Returns:
            {
                'success': True,
                'message': 'Found 20 columns across 2 tables',
                'operation': 'List',
                'data': [{
                    'tableName': 'd_Company',
                    'columns': [
                        {'dataType': 'String', 'name': 'Company Name'},
                        {'dataType': 'Int64', 'name': 'Company Code'}
                    ]
                }],
                'warnings': ['Results truncated: Showing 20 of 724 columns']
            }
        """
        from core.validation.error_handler import ErrorHandler

        if not connection_state.is_connected():
            return ErrorHandler.handle_not_connected()

        executor = connection_state.query_executor
        if not executor:
            return ErrorHandler.handle_manager_unavailable('query_executor')

        try:
            # Get columns - use unlimited query for complete data
            result = executor.execute_info_query('COLUMNS', table_name=table_name, top_n=10000)

            if not result.get('success'):
                return result

            rows = result.get('rows', [])
            total_count = len(rows)

            if total_count == 0:
                return {
                    'success': True,
                    'operation': 'List',
                    'message': 'No columns found',
                    'data': []
                }

            # Group columns by table - be very permissive with field names
            tables_dict = {}
            for row in rows:
                # Try ALL possible table field names
                tbl = (row.get('Table') or row.get('TableName') or
                       row.get('table') or row.get('tablename') or
                       row.get('[Table]') or row.get('[TableName]') or 'Unknown')

                if tbl not in tables_dict:
                    tables_dict[tbl] = []

                # Try ALL possible column name fields
                col_name = (row.get('Name') or row.get('ColumnName') or
                           row.get('name') or row.get('columnname') or
                           row.get('[Name]') or row.get('[ColumnName]') or '')

                # Try ALL possible datatype fields
                data_type = (row.get('DataType') or row.get('Type') or
                            row.get('datatype') or row.get('type') or
                            row.get('[DataType]') or row.get('[Type]') or 'Unknown')

                # Always add the column
                col_info = {
                    'name': col_name if col_name else f'Column_{len(tables_dict[tbl])+1}',
                    'dataType': data_type
                }
                tables_dict[tbl].append(col_info)

            # Convert to list format with max_results limit
            columns_by_table = []
            column_count = 0

            for tbl_name, cols in sorted(tables_dict.items()):
                # Apply max_results limit
                cols_to_add = []
                for col in cols:
                    if max_results and column_count >= max_results:
                        break
                    cols_to_add.append(col)
                    column_count += 1

                columns_by_table.append({
                    'tableName': tbl_name,
                    'columns': cols_to_add
                })

                if max_results and column_count >= max_results:
                    break

            # Count actual columns returned
            returned_count = sum(len(t['columns']) for t in columns_by_table)
            truncated = max_results and total_count > max_results

            # Build response matching Microsoft MCP format
            response = {
                'success': True,
                'operation': 'List'
            }

            # Message format
            if table_name:
                response['message'] = f'Found {returned_count} columns in table \'{table_name}\''
            else:
                response['message'] = f'Found {returned_count} columns across {len(columns_by_table)} tables'

            response['data'] = columns_by_table

            # Add warning if truncated
            if truncated:
                response['warnings'] = [
                    f'Results truncated: Showing {returned_count} of {total_count} columns'
                ]

            return response

        except Exception as e:
            logger.error(f"List columns failed: {e}")
            return {
                'success': False,
                'error': f'List columns failed: {str(e)}'
            }

    def list_roles_simple(self, connection_state) -> Dict[str, Any]:
        """
        List security roles with RLS definitions and table permissions detail.
        Microsoft MCP Role List operation with enhanced table permissions.

        Args:
            connection_state: Current connection state

        Returns:
            {
                'success': True,
                'message': 'Found 1 roles',
                'operation': 'List',
                'data': [{
                    'name': 'RLS_Role',
                    'modelPermission': 'Read',
                    'tablePermissionCount': 5,
                    'filteredTables': ['Sales', 'Customers', 'Orders']
                }]
            }
        """
        from core.validation.error_handler import ErrorHandler

        if not connection_state.is_connected():
            return ErrorHandler.handle_not_connected()

        executor = connection_state.query_executor
        if not executor:
            return ErrorHandler.handle_manager_unavailable('query_executor')

        try:
            # Get roles
            result = executor.execute_info_query('ROLES')

            if not result.get('success'):
                return result

            rows = result.get('rows', [])

            # Query table permissions for all roles
            table_permissions_by_role = {}
            try:
                # Use DAX to query table permissions from DMV
                perms_query = """
                EVALUATE
                SELECTCOLUMNS(
                    FILTER(
                        TMSCHEMA_MODEL_ROLE_TABLE_PERMISSIONS(),
                        [FilterExpression] <> BLANK()
                    ),
                    "RoleName", [RoleName],
                    "TableName", [TableName],
                    "FilterExpression", [FilterExpression]
                )
                """
                perms_result = executor.validate_and_execute_dax(perms_query, 0)

                if perms_result.get('success'):
                    perm_rows = perms_result.get('rows', [])

                    # Group permissions by role
                    for perm_row in perm_rows:
                        role_name = perm_row.get('RoleName') or perm_row.get('[RoleName]', '')
                        table_name = perm_row.get('TableName') or perm_row.get('[TableName]', '')

                        if role_name:
                            if role_name not in table_permissions_by_role:
                                table_permissions_by_role[role_name] = []
                            if table_name and table_name not in table_permissions_by_role[role_name]:
                                table_permissions_by_role[role_name].append(table_name)
                else:
                    logger.warning("Could not query table permissions - permissions detail will be limited")

            except Exception as perm_error:
                logger.warning(f"Error querying table permissions: {perm_error}")
                # Continue without table permissions detail

            # Build role list matching Microsoft MCP format with enhanced permissions
            roles = []
            for row in rows:
                role_name = row.get('Name', '')
                role_info = {
                    'name': role_name,
                    'modelPermission': row.get('ModelPermission', 'Read')
                }

                # Add table permissions detail if available
                if role_name in table_permissions_by_role:
                    filtered_tables = table_permissions_by_role[role_name]
                    role_info['tablePermissionCount'] = len(filtered_tables)
                    role_info['filteredTables'] = filtered_tables
                elif row.get('TablePermissionCount'):
                    # Fallback to basic count if available from DMV
                    role_info['tablePermissionCount'] = row.get('TablePermissionCount')

                roles.append(role_info)

            # Build response matching Microsoft MCP format
            return {
                'success': True,
                'message': f'Found {len(roles)} roles',
                'operation': 'List',
                'data': roles
            }

        except Exception as e:
            logger.error(f"List roles failed: {e}")
            return {
                'success': False,
                'error': f'List roles failed: {str(e)}'
            }

    def list_databases_simple(self, connection_state) -> Dict[str, Any]:
        """
        List databases on the server.
        Microsoft MCP Database List operation.

        Args:
            connection_state: Current connection state

        Returns:
            {
                'success': True,
                'message': 'Found 1 databases on server',
                'operation': 'List',
                'data': [{
                    'id': 'edb241b5-77e6-42a5-8199-67fc2c6224bd',
                    'name': 'edb241b5-77e6-42a5-8199-67fc2c6224bd',
                    'compatibilityLevel': 1601,
                    'state': 'Ready',
                    'modelType': 'Tabular'
                }]
            }
        """
        from core.validation.error_handler import ErrorHandler

        if not connection_state.is_connected():
            return ErrorHandler.handle_not_connected()

        executor = connection_state.query_executor
        if not executor:
            return ErrorHandler.handle_manager_unavailable('query_executor')

        try:
            # Get model/database info
            result = executor.execute_info_query('MODEL')

            if not result.get('success'):
                return result

            rows = result.get('rows', [])

            # Build database list matching Microsoft MCP format
            databases = []
            for row in rows:
                db_info = {
                    'id': row.get('Database', row.get('ID', '')),
                    'name': row.get('Database', row.get('Name', '')),
                    'compatibilityLevel': row.get('CompatibilityLevel', 0),
                    'modelType': 'Tabular'
                }

                # Add optional fields if present
                if row.get('State'):
                    db_info['state'] = row.get('State')
                if row.get('CreatedTimestamp'):
                    db_info['createdTimestamp'] = row.get('CreatedTimestamp')
                if row.get('LastProcessed'):
                    db_info['lastProcessed'] = row.get('LastProcessed')
                if row.get('LastUpdate'):
                    db_info['lastUpdate'] = row.get('LastUpdate')
                if row.get('LastSchemaUpdate'):
                    db_info['lastSchemaUpdate'] = row.get('LastSchemaUpdate')
                if row.get('EstimatedSize'):
                    db_info['estimatedSize'] = row.get('EstimatedSize')
                if row.get('Language'):
                    db_info['language'] = row.get('Language')

                databases.append(db_info)

            # Build response matching Microsoft MCP format
            return {
                'success': True,
                'message': f'Found {len(databases)} databases on server',
                'operation': 'List',
                'data': databases
            }

        except Exception as e:
            logger.error(f"List databases failed: {e}")
            return {
                'success': False,
                'error': f'List databases failed: {str(e)}'
            }

    def _generate_relationship_diagram(self, relationships: list) -> str:
        """
        Generate ASCII diagram showing table relationships.

        Args:
            relationships: List of relationship dictionaries

        Returns:
            ASCII diagram as a string
        """
        if not relationships:
            return "No relationships found"

        # Group relationships by fromTable
        from collections import defaultdict
        table_rels = defaultdict(list)

        for rel in relationships:
            from_table = rel.get('fromTable', '')
            to_table = rel.get('toTable', '')
            from_card = rel.get('fromCardinality', 'Many')
            to_card = rel.get('toCardinality', 'One')
            is_active = rel.get('isActive', True)
            is_bidir = rel.get('crossFilteringBehavior') == 'BothDirections'

            if from_table:
                table_rels[from_table].append({
                    'to': to_table,
                    'cardinality': f"{from_card}:{to_card}",
                    'active': is_active,
                    'bidirectional': is_bidir
                })

        # Build ASCII diagram
        diagram_lines = []
        diagram_lines.append("=" * 80)
        diagram_lines.append("RELATIONSHIP DIAGRAM")
        diagram_lines.append("=" * 80)
        diagram_lines.append("")

        # Sort tables by number of relationships (descending) - fact tables usually have most
        sorted_tables = sorted(table_rels.items(), key=lambda x: len(x[1]), reverse=True)

        # Show top tables with their relationships
        for idx, (table, rels) in enumerate(sorted_tables[:15]):  # Limit to top 15 tables
            # Determine table type based on naming convention and relationship count
            table_type = ""
            if table.startswith('f_') or table.startswith('fact'):
                table_type = " (Fact)"
            elif table.startswith('d_') or table.startswith('dim'):
                table_type = " (Dimension)"
            elif table.startswith('m_'):
                table_type = " (Measures)"

            diagram_lines.append(f"{table}{table_type}")

            # Sort relationships by active status and table name
            sorted_rels = sorted(rels, key=lambda r: (not r['active'], r['to']))

            for i, rel in enumerate(sorted_rels):
                is_last = (i == len(sorted_rels) - 1)
                # Use ASCII characters instead of Unicode box-drawing for better compatibility
                connector = "'-->" if is_last else "|-->"

                # Build relationship line
                rel_line = f"{connector} {rel['to']:<30} ({rel['cardinality']})"

                # Add indicators
                indicators = []
                if not rel['active']:
                    indicators.append("INACTIVE")
                if rel['bidirectional']:
                    indicators.append("BI-DIRECTIONAL")

                if indicators:
                    rel_line += f" [{', '.join(indicators)}]"

                diagram_lines.append(rel_line)

            diagram_lines.append("")  # Empty line between tables

        diagram_lines.append("=" * 80)

        return "\n".join(diagram_lines)

    def generate_expert_analysis(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate COMPREHENSIVE Power BI expert analysis from all operation results.

        Provides deep technical insights across:
        - Model architecture and patterns
        - Relationship complexity and issues
        - Measure organization and complexity
        - Calculation group implementation
        - Performance implications
        - Security implementation
        - Data quality and best practices

        Args:
            results: Dictionary containing all operation results

        Returns:
            Dictionary with detailed expert analysis and actionable insights
        """
        try:
            analysis = {
                'model_overview': {},
                'architecture_patterns': {},
                'table_analysis': {},
                'relationship_analysis': {},
                'measure_analysis': {},
                'calculation_group_analysis': {},
                'security_analysis': {},
                'performance_assessment': {},
                'data_quality': {},
                'recommendations': []
            }

            ops = results.get('operations', {})

            # 1. Extract database info
            db_op = ops.get('01_database', {})
            if db_op.get('success'):
                db_data = db_op.get('data', [{}])[0]
                analysis['model_overview'] = {
                    'database_id': db_data.get('id', ''),
                    'compatibility_level': db_data.get('compatibilityLevel', 0),
                    'model_format': 'Power BI Desktop' if db_data.get('compatibilityLevel', 0) >= 1600 else 'Analysis Services',
                    'estimated_size_mb': round(db_data.get('estimatedSize', 0) / (1024 * 1024), 2) if db_data.get('estimatedSize') else 0
                }

            # 2. Extract and DEEPLY ANALYZE stats
            stats_op = ops.get('02_stats', {})
            if stats_op.get('success'):
                counts = stats_op.get('counts', {})
                tables_list = stats_op.get('tables', [])

                # Basic counts
                total_tables = counts.get('tables', 0)
                total_columns = counts.get('columns', 0)
                total_measures = counts.get('measures', 0)
                total_relationships = counts.get('relationships', 0)

                analysis['model_overview'].update({
                    'total_tables': total_tables,
                    'total_columns': total_columns,
                    'total_measures': total_measures,
                    'total_relationships': total_relationships,
                    'calculation_groups': counts.get('calculation_groups', 0),
                    'security_roles': counts.get('roles', 0)
                })

                # DETAILED table classification
                measure_tables = [t for t in tables_list if t.get('measure_count', 0) > 10 and t.get('column_count', 0) < 5]
                fact_tables = [t for t in tables_list if t.get('type') == 'fact']
                dim_tables = [t for t in tables_list if t.get('type') == 'dimension']
                support_tables = [t for t in tables_list if t.get('type') == 'support']
                field_param_tables = [t for t in tables_list if t.get('type') == 'field_parameter']
                rls_tables = [t for t in tables_list if t.get('type') == 'rls']
                calc_group_tables = [t for t in tables_list if t.get('type') == 'calculation_group']
                other_tables = [t for t in tables_list if t.get('type') == 'other']

                # Complexity metrics
                avg_columns_per_table = round(total_columns / total_tables, 1) if total_tables > 0 else 0
                avg_measures_per_table = round(total_measures / total_tables, 1) if total_tables > 0 else 0
                measures_to_columns_ratio = round(total_measures / total_columns, 2) if total_columns > 0 else 0

                # Find largest/most complex tables
                large_tables = sorted([t for t in tables_list if t.get('column_count', 0) > 30],
                                     key=lambda x: x.get('column_count', 0), reverse=True)[:10]
                measure_heavy_tables = sorted([t for t in tables_list if t.get('measure_count', 0) > 20],
                                             key=lambda x: x.get('measure_count', 0), reverse=True)[:10]

                analysis['architecture_patterns'] = {
                    'measure_tables': [t['name'] for t in measure_tables],
                    'measure_table_count': len(measure_tables),
                    'fact_tables': [t['name'] for t in fact_tables],
                    'fact_tables_count': len(fact_tables),
                    'dimension_tables': [t['name'] for t in dim_tables][:20],  # Show first 20
                    'dimension_tables_count': len(dim_tables),
                    'support_tables_count': len(support_tables),
                    'field_parameter_count': len(field_param_tables),
                    'field_parameter_tables': [t['name'] for t in field_param_tables][:15],  # Show first 15
                    'rls_tables_count': len(rls_tables),
                    'calc_group_tables_count': len(calc_group_tables),
                    'other_tables_count': len(other_tables),
                    'uses_star_schema': len(fact_tables) > 0 and len(dim_tables) > 0,
                    'has_dedicated_measure_tables': len(measure_tables) > 0,
                    'schema_pattern': 'Star Schema' if (len(fact_tables) > 0 and len(dim_tables) > 0) else 'Unknown Pattern'
                }

                analysis['table_analysis'] = {
                    'complexity_metrics': {
                        'avg_columns_per_table': avg_columns_per_table,
                        'avg_measures_per_table': avg_measures_per_table,
                        'measures_to_columns_ratio': measures_to_columns_ratio,
                        'complexity_score': 'High' if avg_columns_per_table > 50 else 'Medium' if avg_columns_per_table > 20 else 'Low'
                    },
                    'largest_tables': [{'name': t['name'], 'columns': t.get('column_count', 0)} for t in large_tables],
                    'measure_heavy_tables': [{'name': t['name'], 'measures': t.get('measure_count', 0)} for t in measure_heavy_tables],
                    'hidden_tables_count': len([t for t in tables_list if t.get('is_hidden', False)]),
                    'table_type_distribution': {
                        'fact': len(fact_tables),
                        'dimension': len(dim_tables),
                        'measure': len(measure_tables),
                        'support': len(support_tables),
                        'field_parameter': len(field_param_tables),
                        'rls': len(rls_tables),
                        'calc_group': len(calc_group_tables),
                        'other': len(other_tables)
                    }
                }

            # 3. COMPREHENSIVE Measure Analysis
            measures_op = ops.get('04_measures', {})
            if measures_op.get('success'):
                measures_data = measures_op.get('data', [])

                # Analyze display folders hierarchies
                top_folders = {}
                all_folders = set()
                measures_with_folders = 0
                max_folder_depth = 0

                for m in measures_data:
                    folder = m.get('displayFolder', '')
                    if folder:
                        measures_with_folders += 1
                        all_folders.add(folder)

                        # Track folder hierarchy depth
                        depth = len(folder.split('\\'))
                        if depth > max_folder_depth:
                            max_folder_depth = depth

                        # Track top-level folders
                        top_folder = folder.split('\\')[0]
                        if top_folder not in top_folders:
                            top_folders[top_folder] = []
                        top_folders[top_folder].append(m.get('name', ''))

                folder_usage_pct = round(measures_with_folders / len(measures_data) * 100, 1) if measures_data else 0

                # Identify measure patterns by name
                calc_measures = [m for m in measures_data if 'calc' in m.get('name', '').lower() or 'calculated' in m.get('name', '').lower()]
                base_measures = [m for m in measures_data if 'base' in m.get('name', '').lower()]
                ytd_measures = [m for m in measures_data if 'ytd' in m.get('name', '').lower()]
                mtd_measures = [m for m in measures_data if 'mtd' in m.get('name', '').lower()]
                ly_measures = [m for m in measures_data if 'ly' in m.get('name', '').lower() or 'last year' in m.get('name', '').lower()]

                # Analyze folder structure quality
                folder_hierarchy = {folder: len(top_folders[folder]) for folder in top_folders}
                top_folders_by_size = sorted(folder_hierarchy.items(), key=lambda x: x[1], reverse=True)[:15]

                analysis['measure_analysis'] = {
                    'total_measures': len(measures_data),
                    'organization': {
                        'measures_with_folders': measures_with_folders,
                        'folder_usage_percentage': folder_usage_pct,
                        'total_folders': len(all_folders),
                        'top_level_folders_count': len(top_folders),
                        'max_folder_depth': max_folder_depth,
                        'top_folders_by_measure_count': top_folders_by_size,
                        'organization_quality': 'Excellent' if folder_usage_pct > 90 else 'Good' if folder_usage_pct > 70 else 'Fair' if folder_usage_pct > 40 else 'Poor'
                    },
                    'measure_patterns': {
                        'calc_measures': len(calc_measures),
                        'base_measures': len(base_measures),
                        'ytd_measures': len(ytd_measures),
                        'mtd_measures': len(mtd_measures),
                        'ly_measures': len(ly_measures),
                        'uses_time_intelligence': (len(ytd_measures) + len(mtd_measures) + len(ly_measures)) > 5
                    },
                    'measure_distribution': {
                        'avg_measures_per_folder': round(measures_with_folders / len(top_folders), 1) if top_folders else 0,
                        'largest_folder': top_folders_by_size[0][0] if top_folders_by_size else None,
                        'largest_folder_measure_count': top_folders_by_size[0][1] if top_folders_by_size else 0
                    }
                }

            # 4. DEEP Relationship Analysis
            rel_op = ops.get('06_relationships', {})
            if rel_op.get('success'):
                rels = rel_op.get('data', [])

                # Categorize ALL relationship patterns
                many_to_many = [r for r in rels if r.get('fromCardinality') == 'Many' and r.get('toCardinality') == 'Many']
                one_to_many = [r for r in rels if r.get('fromCardinality') == 'One' and r.get('toCardinality') == 'Many']
                many_to_one = [r for r in rels if r.get('fromCardinality') == 'Many' and r.get('toCardinality') == 'One']
                one_to_one = [r for r in rels if r.get('fromCardinality') == 'One' and r.get('toCardinality') == 'One']
                bidirectional = [r for r in rels if r.get('crossFilteringBehavior') == 'BothDirections']
                inactive = [r for r in rels if not r.get('isActive')]

                # Analyze M:M relationship participants (which tables are involved)
                m2m_tables = set()
                m2m_examples = []
                for r in many_to_many[:10]:  # Get first 10 examples
                    from_table = r.get('fromTable', '')
                    to_table = r.get('toTable', '')
                    m2m_tables.add(from_table)
                    m2m_tables.add(to_table)
                    m2m_examples.append({
                        'from': from_table,
                        'to': to_table,
                        'active': r.get('isActive', True),
                        'bidirectional': r.get('crossFilteringBehavior') == 'BothDirections'
                    })

                # Analyze bidirectional relationship participants
                bidir_examples = []
                for r in bidirectional[:10]:
                    bidir_examples.append({
                        'from': r.get('fromTable', ''),
                        'to': r.get('toTable', ''),
                        'cardinality': f"{r.get('fromCardinality', 'Unknown')}:{r.get('toCardinality', 'Unknown')}"
                    })

                # Find tables with most relationships (hub tables)
                table_rel_count = {}
                for r in rels:
                    from_table = r.get('fromTable', '')
                    to_table = r.get('toTable', '')
                    table_rel_count[from_table] = table_rel_count.get(from_table, 0) + 1
                    table_rel_count[to_table] = table_rel_count.get(to_table, 0) + 1

                hub_tables = sorted(table_rel_count.items(), key=lambda x: x[1], reverse=True)[:10]

                # Calculate relationship health metrics
                standard_rels = many_to_one + one_to_many
                standard_pct = round(len(standard_rels) / len(rels) * 100, 1) if rels else 0
                m2m_pct = round(len(many_to_many) / len(rels) * 100, 1) if rels else 0
                bidir_pct = round(len(bidirectional) / len(rels) * 100, 1) if rels else 0

                # Determine complexity level
                if m2m_pct > 25:
                    complexity = 'Very Complex'
                    complexity_score = 'Critical'
                elif m2m_pct > 15:
                    complexity = 'Complex'
                    complexity_score = 'High'
                elif m2m_pct > 5:
                    complexity = 'Moderate'
                    complexity_score = 'Medium'
                else:
                    complexity = 'Standard'
                    complexity_score = 'Low'

                # Generate relationship diagram
                relationship_diagram = self._generate_relationship_diagram(rels)

                analysis['relationship_analysis'] = {
                    'total_relationships': len(rels),
                    'cardinality_breakdown': {
                        'many_to_one': len(many_to_one),
                        'one_to_many': len(one_to_many),
                        'many_to_many': len(many_to_many),
                        'one_to_one': len(one_to_one),
                        'many_to_many_percentage': m2m_pct,
                        'bidirectional_count': len(bidirectional),
                        'bidirectional_percentage': bidir_pct,
                        'inactive_count': len(inactive)
                    },
                    'relationship_health': {
                        'standard_relationships': len(standard_rels),
                        'standard_percentage': standard_pct,
                        'health_score': 'Excellent' if standard_pct >= 95 else 'Good' if standard_pct >= 80 else 'Fair' if standard_pct >= 60 else 'Poor',
                        'complexity_level': complexity,
                        'complexity_score': complexity_score
                    },
                    'problem_relationships': {
                        'many_to_many_examples': m2m_examples,
                        'many_to_many_unique_tables': list(m2m_tables)[:20],
                        'bidirectional_examples': bidir_examples
                    },
                    'hub_analysis': {
                        'hub_tables': [{'table': t[0], 'relationship_count': t[1]} for t in hub_tables],
                        'most_connected_table': hub_tables[0][0] if hub_tables else None,
                        'most_connected_count': hub_tables[0][1] if hub_tables else 0
                    },
                    'diagram': relationship_diagram
                }

            # 5. DETAILED Calculation Group Analysis
            calc_op = ops.get('07_calculation_groups', {})
            if calc_op.get('success'):
                calc_groups = calc_op.get('data', [])

                total_items = sum(len(cg.get('calculationItems', [])) for cg in calc_groups)

                # Analyze calculation group patterns
                time_intel_groups = [cg for cg in calc_groups if any(x in cg.get('name', '').lower() for x in ['time', 'date', 'period', 'ytd', 'mtd'])]
                currency_groups = [cg for cg in calc_groups if any(x in cg.get('name', '').lower() for x in ['currency', 'fx', 'exchange'])]
                scenario_groups = [cg for cg in calc_groups if any(x in cg.get('name', '').lower() for x in ['scenario', 'comparison', 'variance'])]

                # Detailed group information
                group_details = []
                for cg in calc_groups:
                    items = cg.get('calculationItems', [])
                    group_details.append({
                        'name': cg.get('name', ''),
                        'item_count': len(items),
                        'items': [item.get('name', '') for item in items],
                        'pattern': (
                            'Time Intelligence' if cg in time_intel_groups else
                            'Currency Conversion' if cg in currency_groups else
                            'Scenario Analysis' if cg in scenario_groups else
                            'Custom Logic'
                        )
                    })

                analysis['calculation_group_analysis'] = {
                    'total_groups': len(calc_groups),
                    'total_items': total_items,
                    'avg_items_per_group': round(total_items / len(calc_groups), 1) if calc_groups else 0,
                    'patterns': {
                        'time_intelligence_count': len(time_intel_groups),
                        'currency_conversion_count': len(currency_groups),
                        'scenario_analysis_count': len(scenario_groups),
                        'uses_advanced_patterns': len(calc_groups) > 0
                    },
                    'group_details': group_details,
                    'implementation_quality': 'Sophisticated' if len(calc_groups) >= 3 else 'Good' if len(calc_groups) >= 1 else 'None'
                }

            # 6. Security Analysis
            roles_op = ops.get('08_roles', {})
            if roles_op.get('success'):
                roles = roles_op.get('data', [])

                # Analyze RLS implementation
                roles_with_filters = [r for r in roles if r.get('tablePermissionCount', 0) > 0]
                total_table_permissions = sum(r.get('tablePermissionCount', 0) for r in roles)

                analysis['security_analysis'] = {
                    'total_roles': len(roles),
                    'roles_with_filters': len(roles_with_filters),
                    'total_table_permissions': total_table_permissions,
                    'avg_tables_per_role': round(total_table_permissions / len(roles), 1) if roles else 0,
                    'rls_implemented': len(roles_with_filters) > 0,
                    'security_complexity': 'High' if total_table_permissions > 20 else 'Medium' if total_table_permissions > 5 else 'Low',
                    'role_details': [{'name': r.get('name', ''), 'filtered_tables': r.get('tablePermissionCount', 0)} for r in roles]
                }

            # 7. Performance Assessment
            rel_analysis = analysis.get('relationship_analysis', {})
            table_analysis = analysis.get('table_analysis', {})
            size_mb = analysis['model_overview'].get('estimated_size_mb', 0)

            performance_score = 100
            performance_issues = []

            # Relationship complexity impact
            m2m_pct = rel_analysis.get('cardinality_breakdown', {}).get('many_to_many_percentage', 0)
            if m2m_pct > 25:
                performance_score -= 30
                performance_issues.append('Critical: Excessive M:M relationships')
            elif m2m_pct > 15:
                performance_score -= 20
                performance_issues.append('High: Many M:M relationships')
            elif m2m_pct > 5:
                performance_score -= 10
                performance_issues.append('Medium: Some M:M relationships')

            # Bidirectional relationships impact
            bidir_pct = rel_analysis.get('cardinality_breakdown', {}).get('bidirectional_percentage', 0)
            if bidir_pct > 10:
                performance_score -= 15
                performance_issues.append('Excessive bidirectional relationships')

            # Model size impact
            if size_mb > 2000:
                performance_score -= 20
                performance_issues.append('Very large model size')
            elif size_mb > 1000:
                performance_score -= 10
                performance_issues.append('Large model size')

            performance_score = max(0, performance_score)

            analysis['performance_assessment'] = {
                'performance_score': performance_score,
                'performance_grade': 'A' if performance_score >= 90 else 'B' if performance_score >= 75 else 'C' if performance_score >= 60 else 'D' if performance_score >= 40 else 'F',
                'performance_issues': performance_issues,
                'estimated_query_impact': 'Low' if performance_score >= 85 else 'Medium' if performance_score >= 70 else 'High' if performance_score >= 50 else 'Critical'
            }

            # 8. COMPREHENSIVE Recommendations
            recommendations = []

            # Critical M:M relationship issue
            m2m_count = rel_analysis.get('cardinality_breakdown', {}).get('many_to_many', 0)
            if m2m_count > 20:
                m2m_examples = rel_analysis.get('problem_relationships', {}).get('many_to_many_examples', [])[:5]
                examples_text = ', '.join([f"{r['from']} ↔ {r['to']}" for r in m2m_examples])
                recommendations.append({
                    'type': 'architecture',
                    'priority': 'critical',
                    'category': 'Relationship Optimization',
                    'title': f'Critical: {m2m_count} Many-to-Many Relationships ({m2m_pct:.1f}%)',
                    'impact': 'Severe performance degradation, complex filter propagation, ambiguous relationships',
                    'examples': examples_text,
                    'solution': 'Create bridge tables for dimensional relationships. Replace M:M with two M:1 relationships through bridge table.',
                    'expected_benefit': f'30-50% performance improvement for filtered queries',
                    'action_items': [
                        'Identify root cause: Are these field parameters or true M:M dimensions?',
                        'For field parameters: Consider consolidating or using dynamic measures instead',
                        'For dimensions: Design bridge tables with grain matching both sides',
                        'Test filter propagation after implementation'
                    ]
                })
            elif m2m_count > 10:
                recommendations.append({
                    'type': 'architecture',
                    'priority': 'high',
                    'category': 'Relationship Optimization',
                    'title': f'High: {m2m_count} Many-to-Many Relationships',
                    'impact': 'Moderate performance impact, filter complexity',
                    'solution': 'Review and refactor critical M:M relationships to use bridge tables',
                    'expected_benefit': '15-25% performance improvement'
                })

            # Bidirectional relationships warning
            bidir_count = rel_analysis.get('cardinality_breakdown', {}).get('bidirectional_count', 0)
            if bidir_count > 5:
                bidir_examples = rel_analysis.get('problem_relationships', {}).get('bidirectional_examples', [])[:5]
                examples_text = ', '.join([f"{r['from']} ↔ {r['to']} ({r['cardinality']})" for r in bidir_examples])
                recommendations.append({
                    'type': 'architecture',
                    'priority': 'high',
                    'category': 'Filter Propagation',
                    'title': f'Warning: {bidir_count} Bidirectional Relationships',
                    'impact': 'Ambiguous filter paths, potential circular dependencies, performance overhead',
                    'examples': examples_text,
                    'solution': 'Review necessity of bidirectional filters. Consider CROSSFILTER in measures instead.',
                    'action_items': [
                        'Document business reason for each bidirectional filter',
                        'Test if CROSSFILTER() in DAX can replace bidirectional relationships',
                        'Review for potential ambiguity with DAX Studio relationship analyzer'
                    ]
                })

            # Field parameter explosion
            field_param_count = analysis.get('architecture_patterns', {}).get('field_parameter_count', 0)
            if field_param_count > 20:
                field_params = analysis.get('architecture_patterns', {}).get('field_parameter_tables', [])[:10]
                recommendations.append({
                    'type': 'architecture',
                    'priority': 'high',
                    'category': 'Model Complexity',
                    'title': f'Field Parameter Explosion: {field_param_count} Parameter Tables',
                    'impact': 'Model complexity, M:M relationship proliferation, maintenance overhead',
                    'examples': ', '.join(field_params),
                    'solution': 'Consolidate related field parameters. Consider calculation groups or dynamic measures.',
                    'action_items': [
                        'Group related parameters (currency, time intelligence, scenarios)',
                        'Evaluate if calculation groups can replace some parameters',
                        'Consider dynamic measure approach for simpler scenarios',
                        'Document field parameter strategy for team'
                    ]
                })

            # Large model size warning
            if size_mb > 1000:
                recommendations.append({
                    'type': 'performance',
                    'priority': 'high',
                    'category': 'Data Volume',
                    'title': f'Large Model: {size_mb:.1f} MB',
                    'impact': 'Slow refresh, high memory consumption, slower query performance',
                    'solution': 'Implement incremental refresh, optimize column cardinality, review unnecessary columns',
                    'expected_benefit': '40-60% size reduction, faster refresh and queries',
                    'action_items': [
                        'Enable incremental refresh for fact tables',
                        'Review column cardinality - remove high-cardinality text columns',
                        'Consider summarization/aggregation for old data',
                        'Audit and remove unused columns'
                    ]
                })

            # Positive recognitions
            folder_usage = analysis.get('measure_analysis', {}).get('organization', {}).get('folder_usage_percentage', 0)
            if folder_usage > 90:
                recommendations.append({
                    'type': 'best_practice',
                    'priority': 'info',
                    'category': 'Organization',
                    'title': f'Excellent Measure Organization: {folder_usage:.1f}% using display folders',
                    'impact': 'Improved user experience, easier maintenance, professional appearance'
                })

            calc_group_count = analysis.get('calculation_group_analysis', {}).get('total_groups', 0)
            if calc_group_count >= 3:
                group_names = ', '.join([g['name'] for g in analysis.get('calculation_group_analysis', {}).get('group_details', [])[:5]])
                recommendations.append({
                    'type': 'best_practice',
                    'priority': 'info',
                    'category': 'Advanced DAX',
                    'title': f'Sophisticated Calculation Group Implementation: {calc_group_count} groups',
                    'impact': 'Reduced measure count, consistent time intelligence, professional implementation',
                    'examples': group_names
                })

            if analysis.get('architecture_patterns', {}).get('uses_star_schema'):
                fact_count = analysis.get('architecture_patterns', {}).get('fact_tables_count', 0)
                dim_count = analysis.get('architecture_patterns', {}).get('dimension_tables_count', 0)
                recommendations.append({
                    'type': 'architecture',
                    'priority': 'info',
                    'category': 'Schema Design',
                    'title': f'Star Schema Pattern: {fact_count} fact tables, {dim_count} dimensions',
                    'impact': 'Optimal for Power BI, excellent performance foundation'
                })

            # Security implementation
            rls_impl = analysis.get('security_analysis', {}).get('rls_implemented', False)
            if rls_impl:
                role_count = analysis.get('security_analysis', {}).get('total_roles', 0)
                recommendations.append({
                    'type': 'security',
                    'priority': 'info',
                    'category': 'Data Security',
                    'title': f'Row-Level Security Implemented: {role_count} roles',
                    'impact': 'Data access control enforced, compliance-ready'
                })

            analysis['recommendations'] = recommendations

            return {
                'success': True,
                'analysis': analysis,
                'summary': self._generate_summary_text(analysis)
            }

        except Exception as e:
            logger.error(f"Expert analysis generation failed: {e}")
            return {
                'success': False,
                'error': f'Expert analysis failed: {str(e)}'
            }

    def _generate_summary_text(self, analysis: Dict[str, Any]) -> str:
        """
        Generate comprehensive, screenshot-style Power BI expert analysis summary.
        Enhanced with detailed insights and professional formatting.
        """
        overview = analysis.get('model_overview', {})
        insights = analysis.get('data_model_insights', {})
        arch = analysis.get('architecture_patterns', {})
        recommendations = analysis.get('recommendations', [])

        summary_parts = []

        # Header
        summary_parts.append("=" * 80)
        summary_parts.append("POWER BI MODEL ANALYSIS - EXPERT SUMMARY")
        summary_parts.append("=" * 80)
        summary_parts.append("")

        # 1. MODEL OVERVIEW
        summary_parts.append("📊 MODEL OVERVIEW")
        summary_parts.append("-" * 80)
        summary_parts.append(f"Database ID:          {overview.get('database_id', 'N/A')}")
        summary_parts.append(f"Compatibility Level:  {overview.get('compatibility_level', 0)} ({overview.get('model_format', 'Unknown')})")

        size_mb = overview.get('estimated_size_mb', 0)
        if size_mb > 0:
            size_category = "Large (>1GB)" if size_mb > 1024 else "Medium (100MB-1GB)" if size_mb > 100 else "Small (<100MB)"
            summary_parts.append(f"Model Size:           {size_mb:.2f} MB ({size_category})")

        summary_parts.append("")
        summary_parts.append(f"📋 Tables:            {overview.get('total_tables', 0)}")
        summary_parts.append(f"📐 Columns:           {overview.get('total_columns', 0)}")
        summary_parts.append(f"📏 Measures:          {overview.get('total_measures', 0)}")
        summary_parts.append(f"🔗 Relationships:     {overview.get('total_relationships', 0)}")
        summary_parts.append(f"⚡ Calc Groups:       {overview.get('calculation_groups', 0)}")
        summary_parts.append(f"🔒 Security Roles:    {overview.get('security_roles', 0)}")
        summary_parts.append("")

        # 2. ARCHITECTURE PATTERNS
        summary_parts.append("🏗️  ARCHITECTURE PATTERNS")
        summary_parts.append("-" * 80)

        if arch.get('uses_star_schema'):
            summary_parts.append(f"✅ Star Schema Pattern Detected")
            summary_parts.append(f"   • Fact Tables:      {arch.get('fact_tables_count', 0)}")
            summary_parts.append(f"   • Dimension Tables: {arch.get('dimension_tables_count', 0)}")
        else:
            summary_parts.append("⚠️  No clear star schema pattern detected")

        if arch.get('has_dedicated_measure_tables'):
            measure_tables = arch.get('measure_tables', [])
            summary_parts.append(f"✅ Dedicated Measure Tables: {', '.join(measure_tables[:3])}")
        else:
            summary_parts.append("ℹ️  No dedicated measure tables (measures likely in fact tables)")

        summary_parts.append("")

        # 3. RELATIONSHIPS ANALYSIS
        rel_pattern = insights.get('relationship_patterns', {})
        if rel_pattern:
            summary_parts.append("🔗 RELATIONSHIP ANALYSIS")
            summary_parts.append("-" * 80)

            complexity = rel_pattern.get('complexity_level', 'Unknown')
            complexity_icon = "🔴" if complexity == "Complex" else "🟡" if complexity == "Standard" else "🟢"
            summary_parts.append(f"{complexity_icon} Complexity Level: {complexity}")
            summary_parts.append("")

            total_rels = rel_pattern.get('total_relationships', 0)
            m2m = rel_pattern.get('many_to_many_count', 0)
            bidir = rel_pattern.get('bidirectional_count', 0)
            inactive = rel_pattern.get('inactive_count', 0)

            # Cardinality breakdown
            summary_parts.append(f"Total Relationships: {total_rels}")
            if m2m > 0:
                summary_parts.append(f"  ⚠️  Many-to-Many:     {m2m} (requires monitoring)")
            if bidir > 0:
                summary_parts.append(f"  ⚠️  Bi-directional:   {bidir} (potential performance impact)")
            if inactive > 0:
                summary_parts.append(f"  ℹ️  Inactive:         {inactive} (used with USERELATIONSHIP)")

            # Add health score
            standard_rels = total_rels - m2m - bidir
            health_pct = (standard_rels / total_rels * 100) if total_rels > 0 else 100
            health_icon = "✅" if health_pct >= 80 else "⚠️" if health_pct >= 60 else "🔴"
            summary_parts.append("")
            summary_parts.append(f"{health_icon} Relationship Health: {health_pct:.0f}% standard patterns")
            summary_parts.append("")

        # 4. CALCULATION GROUPS
        calc_groups = insights.get('calculation_groups', {})
        if calc_groups.get('count', 0) > 0:
            summary_parts.append("⚡ CALCULATION GROUPS")
            summary_parts.append("-" * 80)
            summary_parts.append(f"✅ Using Calculation Groups - Advanced DAX Pattern")
            summary_parts.append(f"   • Groups:           {calc_groups['count']}")
            summary_parts.append(f"   • Total Items:      {calc_groups.get('total_calculation_items', 0)}")

            group_names = calc_groups.get('group_names', [])
            if group_names:
                summary_parts.append(f"   • Groups:           {', '.join(group_names[:3])}")
                if len(group_names) > 3:
                    summary_parts.append(f"                       ... and {len(group_names) - 3} more")
            summary_parts.append("")

        # 5. MEASURE ORGANIZATION
        measure_org = insights.get('measure_organization', {})
        if measure_org:
            summary_parts.append("📏 MEASURE ORGANIZATION")
            summary_parts.append("-" * 80)

            if measure_org.get('uses_display_folders'):
                summary_parts.append(f"✅ Measures organized with Display Folders")
                folders = measure_org.get('top_level_folders', [])
                if folders:
                    summary_parts.append(f"   • Top Folders: {', '.join(folders[:5])}")
            else:
                summary_parts.append("ℹ️  Measures not organized in display folders")

            summary_parts.append(f"   • Total Measures: {measure_org.get('total_measures_analyzed', 0)}")
            summary_parts.append("")

        # 6. RECOMMENDATIONS
        if recommendations:
            summary_parts.append("💡 RECOMMENDATIONS")
            summary_parts.append("-" * 80)

            # Group by priority
            high_priority = [r for r in recommendations if r.get('priority') == 'high']
            medium_priority = [r for r in recommendations if r.get('priority') == 'medium']
            info_priority = [r for r in recommendations if r.get('priority') == 'info']

            if high_priority:
                summary_parts.append("🔴 HIGH PRIORITY:")
                for rec in high_priority:
                    summary_parts.append(f"   • {rec.get('message', '')}")
                summary_parts.append("")

            if medium_priority:
                summary_parts.append("🟡 MEDIUM PRIORITY:")
                for rec in medium_priority:
                    summary_parts.append(f"   • {rec.get('message', '')}")
                summary_parts.append("")

            if info_priority:
                summary_parts.append("✅ BEST PRACTICES DETECTED:")
                for rec in info_priority:
                    summary_parts.append(f"   • {rec.get('message', '')}")
                summary_parts.append("")

        # Footer
        summary_parts.append("=" * 80)
        summary_parts.append("Analysis completed successfully")
        summary_parts.append("=" * 80)

        return '\n'.join(summary_parts)
