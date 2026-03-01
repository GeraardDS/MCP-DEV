"""
Debug Handler

MCP tools for visual debugging, filter analysis, and measure comparison.
Combines PBIP analysis with live model query execution.
"""

import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from server.registry import ToolDefinition
from core.infrastructure.connection_state import connection_state
from core.validation.error_handler import ErrorHandler

logger = logging.getLogger(__name__)

# --- Module-level constants ---
PBIP_FRESHNESS_THRESHOLD_MINUTES = 5  # Warn if PBIP files are older than this
DRILL_DETAIL_LIMIT_MIN = 1
DRILL_DETAIL_LIMIT_MAX = 10000


def _compact_response(data: Dict[str, Any], compact: bool = True) -> Dict[str, Any]:
    """Optimize response for token usage. Delegates to middleware.compact_response."""
    if not compact:
        return data
    from server.middleware import compact_response
    return compact_response(data, compact=True, remove_empty=True, remove_nulls=True)


def _compact_visual_list(visuals: List[Dict], compact: bool = True) -> List[Dict]:
    """Return compact visual list for discovery responses."""
    if not compact:
        return visuals
    # Return only essential fields: id, friendly_name, type, measures (first 3)
    return [
        {
            'id': v.get('id'),
            'name': v.get('friendly_name', v.get('type', '?')),
            'type': v.get('type_display', v.get('type', '')),
            'measures': v.get('measures', [])[:3]  # Limit measures shown
        }
        for v in visuals
    ]


def _compact_page_list(pages: List[Dict], compact: bool = True) -> List[Dict]:
    """Return compact page list."""
    if not compact:
        return pages
    return [{'name': p.get('name')} for p in pages]


def _compact_filter_context(filter_breakdown: Dict, compact: bool = True) -> Dict:
    """Return compact filter context - just the DAX expressions."""
    if not compact:
        return filter_breakdown
    # Return only dax strings grouped by level
    result = {}
    for level, filters in filter_breakdown.items():
        if filters:
            dax_list = [f.get('dax') for f in filters if f.get('dax')]
            if dax_list:
                result[level] = dax_list
    return result


def _check_pbip_freshness(pbip_folder: str, threshold_minutes: int = PBIP_FRESHNESS_THRESHOLD_MINUTES) -> Optional[Dict[str, Any]]:
    """
    Check if PBIP files have been modified recently.

    Args:
        pbip_folder: Path to the PBIP folder
        threshold_minutes: Warn if files are older than this (default 5 minutes)

    Returns:
        Warning dict if stale, None if fresh
    """
    if not pbip_folder or not os.path.exists(pbip_folder):
        return None

    pbip_path = Path(pbip_folder)
    latest_mtime = 0

    # Check key PBIP files for most recent modification
    # Use rglob which already searches recursively, so just use the extension pattern
    patterns = ['*.json', '*.tmdl']

    for pattern in patterns:
        for file_path in pbip_path.rglob(pattern):
            try:
                mtime = file_path.stat().st_mtime
                if mtime > latest_mtime:
                    latest_mtime = mtime
            except OSError:
                continue

    if latest_mtime == 0:
        return None

    age_seconds = time.time() - latest_mtime
    age_minutes = age_seconds / 60

    if age_minutes > threshold_minutes:
        return {
            'stale': True,
            'age_minutes': round(age_minutes, 1),
            'message': f'PBIP files are {round(age_minutes, 1)} minutes old. Save your report for accurate slicer state.',
            'hint': 'Use filters parameter to override with current values if needed.'
        }

    return None


def _get_visual_query_builder():
    """Get VisualQueryBuilder instance with auto-detected PBIP path."""
    pbip_folder = connection_state.get_pbip_folder_path()
    if not pbip_folder:
        return None, "PBIP folder not available. Either open a .pbip project in Power BI Desktop, or use set_pbip_path to specify the path manually."

    try:
        from core.debug.visual_query_builder import VisualQueryBuilder
        return VisualQueryBuilder(pbip_folder), None
    except Exception as e:
        return None, f"Error initializing VisualQueryBuilder: {e}"


def handle_debug_visual(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Debug a visual by showing its complete filter context and executing the query.

    Combines PBIP analysis (for filter context) with live model (for execution).
    Self-sufficient: lists available pages/visuals when not found.
    """
    try:
        page_name = args.get('page_name')
        visual_id = args.get('visual_id')
        visual_name = args.get('visual_name')
        measure_name = args.get('measure_name')
        include_slicers = args.get('include_slicers', True)
        execute_query = args.get('execute_query', True)
        manual_filters = args.get('filters', [])  # Manual DAX filter expressions
        skip_auto_filters = args.get('skip_auto_filters', False)  # Skip auto-detected filters
        compact = args.get('compact', True)  # Token optimization: compact output (default True)

        # Get builder first - needed for discovery
        builder, error = _get_visual_query_builder()
        if error:
            return {'success': False, 'error': error}

        # Check PBIP freshness
        pbip_freshness = _check_pbip_freshness(connection_state.get_pbip_folder_path())

        # If page_name not provided, list available pages
        if not page_name:
            pages = builder.list_pages()
            return {
                'success': False,
                'error': 'page_name required',
                'pages': _compact_page_list(pages, compact)
            }

        # Check if page exists
        pages = builder.list_pages()
        page_exists = any(p['name'].lower() == page_name.lower() for p in pages)

        if not page_exists:
            return {
                'success': False,
                'error': f"Page '{page_name}' not found",
                'pages': _compact_page_list(pages, compact)
            }

        # If visual_id/visual_name not provided, list available visuals on the page
        if not visual_id and not visual_name:
            visuals = builder.list_visuals(page_name)
            non_slicer_visuals = [v for v in visuals if not v.get('is_slicer')]
            slicer_visuals = [v for v in visuals if v.get('is_slicer')]

            return {
                'success': False,
                'error': 'visual_id or visual_name required',
                'page': page_name,
                'visuals': _compact_visual_list(non_slicer_visuals, compact),
                'slicers': [{'id': v.get('id'), 'field': v.get('columns', ['?'])[0] if v.get('columns') else '?'} for v in slicer_visuals] if slicer_visuals else None
            }

        # Load column types from model for accurate type detection
        # This ensures string columns get string filter values (e.g., "0" not 0)
        if connection_state.is_connected():
            qe = connection_state.query_executor
            if qe:
                types_loaded = builder.load_column_types(qe)
                if types_loaded > 0:
                    logger.debug(f"Loaded {types_loaded} column types for filter generation")

        # Build query
        result = builder.build_visual_query(
            page_name=page_name,
            visual_id=visual_id,
            visual_name=visual_name,
            measure_name=measure_name,
            include_slicers=include_slicers
        )

        if not result:
            # Visual not found - list available visuals
            visuals = builder.list_visuals(page_name)
            non_slicer_visuals = [v for v in visuals if not v.get('is_slicer')]

            return {
                'success': False,
                'error': f"Visual not found: id='{visual_id}', name='{visual_name}'",
                'visuals': _compact_visual_list(non_slicer_visuals, compact)
            }

        # Check for slicers with no selection (potential issue)
        slicers_without_selection = []
        all_slicers = builder.list_slicers(page_name)
        for slicer in all_slicers:
            if not slicer.selected_values:
                slicers_without_selection.append({
                    'field': slicer.field_reference,
                    'table': slicer.table,
                    'column': slicer.column
                })

        # Classify filters using the new classification system
        all_filters = result.filter_context.all_filters()

        # Use classification attribute for proper categorization
        from core.debug.filter_to_dax import FilterClassification

        # Enhance classification with semantic analysis when connected
        # Only upgrade to field_parameter if detected via RELIABLE methods:
        # - nameof_pattern: Table contains NAMEOF() expressions (definitive)
        # - switch_pattern: Measures use SWITCH(SELECTEDVALUE(...)) (definitive)
        # - system_flags: SystemFlags=2 from DMV (definitive)
        # NOT composite_key (many dimension tables have composite keys legitimately)
        RELIABLE_FIELD_PARAM_METHODS = {'nameof_pattern', 'switch_pattern', 'system_flags'}

        if connection_state.is_connected():
            try:
                semantic_classifier = builder._init_semantic_classifier()
                if semantic_classifier:
                    for f in all_filters:
                        if f.table:
                            sc = semantic_classifier.classify(f.table, f.column)
                            # Only upgrade to field_parameter if detected via reliable methods
                            if sc.classification == 'field_parameter':
                                if sc.detection_method in RELIABLE_FIELD_PARAM_METHODS and sc.confidence > 0.80:
                                    f.classification = FilterClassification.FIELD_PARAMETER
                                # Skip composite_key and naming_convention - too many false positives
                            elif sc.classification == 'ui_control' and sc.confidence > 0.80:
                                f.classification = FilterClassification.UI_CONTROL
            except (AttributeError, ValueError, TypeError) as se:
                logger.debug(f"Semantic classification enhancement skipped: {se}")

        data_filters = [f for f in all_filters if getattr(f, 'classification', 'data') == FilterClassification.DATA]
        field_param_filters = [f for f in all_filters if getattr(f, 'classification', 'data') == FilterClassification.FIELD_PARAMETER]
        ui_control_filters = [f for f in all_filters if getattr(f, 'classification', 'data') == FilterClassification.UI_CONTROL]

        # Count filters with null values
        filters_with_nulls = [f for f in all_filters if getattr(f, 'has_null_values', False)]

        # Build response - compact mode removes verbose/redundant fields
        response = {
            'success': True,
            'visual': {
                'id': result.visual_info.visual_id,
                'name': result.visual_info.visual_name,
                'type': result.visual_info.visual_type,
                'page': result.visual_info.page_name,
                'measures': result.visual_info.measures,
                'columns': result.visual_info.columns
            },
            'filters': _compact_filter_context(result.filter_breakdown, compact),
            'filter_counts': {
                'total': len(all_filters),
                'applied': len(data_filters),
                'excluded': len(field_param_filters) + len(ui_control_filters)
            } if compact else {
                'report': len(result.filter_context.report_filters),
                'page': len(result.filter_context.page_filters),
                'visual': len(result.filter_context.visual_filters),
                'slicer': len(result.filter_context.slicer_filters),
                'total': len(all_filters),
                'data_applied': len(data_filters),
                'field_params_excluded': len(field_param_filters),
                'ui_controls_excluded': len(ui_control_filters),
                'with_nulls': len(filters_with_nulls)
            },
            'query': result.dax_query,
            'measure': result.measure_name
        }

        # Add PBIP freshness warning if applicable
        if pbip_freshness:
            response['pbip_warning'] = pbip_freshness

        # Only include pbip_path in verbose mode
        if not compact:
            response['pbip_path'] = connection_state.pbip_path
            response['title'] = result.visual_info.title

        # Show excluded filters only in verbose mode (they rarely matter for debugging)
        if not compact and (field_param_filters or ui_control_filters):
            excluded_filters = []
            if field_param_filters:
                excluded_filters.extend([
                    {'table': f.table, 'column': f.column, 'type': 'field_param'}
                    for f in field_param_filters
                ])
            if ui_control_filters:
                excluded_filters.extend([
                    {'table': f.table, 'column': f.column, 'type': 'ui_control'}
                    for f in ui_control_filters
                ])
            response['excluded_filters'] = excluded_filters

        # Include slicer details only in verbose mode (already in filters)
        if not compact and include_slicers and result.filter_context.slicer_filters:
            response['slicer_details'] = [
                {'field': f"{sf.table}[{sf.column}]", 'dax': sf.dax, 'values': sf.values[:5]}
                for sf in result.filter_context.slicer_filters
            ]

        # Include measure definitions only in verbose mode
        if not compact and result.measure_definitions:
            response['measure_definitions'] = [
                {'name': m.name, 'expression': m.expression[:800] + '... [truncated]' if len(m.expression) > 800 else m.expression}
                for m in result.measure_definitions
            ]

        # Include expanded query only in verbose mode
        if not compact and result.expanded_query:
            response['expanded_query'] = result.expanded_query

        # Handle filters based on skip_auto_filters setting
        query_to_execute = result.dax_query

        if skip_auto_filters:
            # Use ONLY manual filters, skip all auto-detected filters
            if manual_filters:
                measures = result.visual_info.measures or [result.measure_name]
                measures = [m if m.startswith('[') else f'[{m}]' for m in measures]
                columns = result.visual_info.columns or []

                from core.debug.filter_to_dax import FilterExpression
                manual_filter_objects = [FilterExpression(dax=f, source='manual', table='', column='', condition_type='Manual', values=[])
                                         for f in manual_filters]
                query_to_execute = builder._build_visual_dax_query(measures, columns, manual_filter_objects)
                response['generated_query'] = query_to_execute  # Update the main query
                response['auto_filters_skipped'] = True
                response['manual_filters_applied'] = manual_filters
            else:
                # No filters at all
                measures = result.visual_info.measures or [result.measure_name]
                measures = [m if m.startswith('[') else f'[{m}]' for m in measures]
                columns = result.visual_info.columns or []

                query_to_execute = builder._build_visual_dax_query(measures, columns, [])
                response['generated_query'] = query_to_execute
                response['auto_filters_skipped'] = True
                response['note'] = 'Auto-detected filters skipped. Provide filters parameter for manual DAX filters.'
        elif manual_filters:
            # Combine detected filters with manual filters, but skip auto-filters that conflict
            # with manual filters on the same table.column

            # Extract table.column references from manual filters
            import re
            manual_filter_columns = set()
            for mf in manual_filters:
                # Match patterns like 'Table'[Column] or "Table"[Column]
                matches = re.findall(r"['\"]?([^'\"]+)['\"]?\[([^\]]+)\]", mf)
                for table, col in matches:
                    # Normalize table name (remove quotes if present)
                    table_clean = table.strip("'\"")
                    manual_filter_columns.add((table_clean.lower(), col.lower()))

            # Filter out auto-detected filters that conflict with manual filters
            non_conflicting_auto_filters = []
            skipped_auto_filters = []
            for f in data_filters:
                if f.dax:
                    # Check if this auto-filter targets the same column as a manual filter
                    if f.table and f.column:
                        if (f.table.lower(), f.column.lower()) in manual_filter_columns:
                            skipped_auto_filters.append(f)
                            continue
                    non_conflicting_auto_filters.append(f)

            # Combine non-conflicting auto filters with manual filters
            all_filter_dax = [f.dax for f in non_conflicting_auto_filters]
            all_filter_dax.extend(manual_filters)

            # Rebuild the query with combined filters
            measures = result.visual_info.measures or [result.measure_name]
            measures = [m if m.startswith('[') else f'[{m}]' for m in measures]
            columns = result.visual_info.columns or []

            # Build the enhanced query
            from core.debug.filter_to_dax import FilterExpression
            combined_filters = [FilterExpression(dax=f, source='manual', table='', column='', condition_type='Manual', values=[])
                                for f in all_filter_dax]
            query_to_execute = builder._build_visual_dax_query(measures, columns, combined_filters)

            response['generated_query'] = query_to_execute  # Update main query too
            response['query_with_manual_filters'] = query_to_execute
            response['manual_filters_applied'] = manual_filters

            # Report skipped filters if any
            if skipped_auto_filters:
                response['auto_filters_overridden'] = [
                    {
                        'table': f.table,
                        'column': f.column,
                        'original_dax': f.dax,
                        'reason': 'Overridden by manual filter on same column'
                    }
                    for f in skipped_auto_filters
                ]

        # Add warning if slicers have no selection (compact: just count, verbose: details)
        if slicers_without_selection:
            if compact:
                response['empty_slicers'] = len(slicers_without_selection)
            else:
                response['warnings'] = [{
                    'type': 'empty_slicers',
                    'count': len(slicers_without_selection),
                    'slicers': slicers_without_selection
                }]

        # Advanced analysis: relationship hints and aggregation recommendations
        if connection_state.is_connected():
            qe = connection_state.query_executor
            if qe:
                # Get tables involved in the query
                measure_tables = list(set(
                    getattr(m, 'table', '') for m in (result.measure_definitions or [])
                    if getattr(m, 'table', '')
                ))
                filter_tables = list(set(f.table for f in all_filters if f.table))
                grouping_tables = list(set(
                    col.split('[')[0].strip("'\"") for col in (result.visual_info.columns or [])
                    if '[' in col
                ))

                # Relationship analysis
                try:
                    relationship_resolver = builder._init_relationship_resolver()
                    if relationship_resolver:
                        hints = relationship_resolver.analyze_query_tables(
                            measure_tables, filter_tables, grouping_tables
                        )
                        if hints:
                            response['relationship_hints'] = [
                                {
                                    'type': h.type,
                                    'tables': f"{h.from_table} -> {h.to_table}",
                                    'suggestion': h.dax_modifier if h.dax_modifier else h.reason,
                                    'severity': h.severity
                                }
                                for h in hints[:3]  # Limit to 3 most relevant
                            ]
                except (AttributeError, ValueError, TypeError) as re:
                    logger.debug(f"Relationship analysis skipped: {re}")

                # Aggregation matching
                try:
                    aggregation_matcher = builder._init_aggregation_matcher()
                    if aggregation_matcher:
                        grouping_cols = result.visual_info.columns or []
                        filter_cols = [f"'{f.table}'[{f.column}]" for f in data_filters if f.table and f.column]
                        agg_match = aggregation_matcher.find_matching_aggregation(grouping_cols, filter_cols)
                        if agg_match:
                            response['aggregation_info'] = {
                                'available': True,
                                'table': agg_match.agg_table,
                                'confidence': agg_match.match_confidence,
                                'recommendation': agg_match.recommendation
                            }
                except (AttributeError, ValueError, TypeError) as ae:
                    logger.debug(f"Aggregation analysis skipped: {ae}")

        # Execute query if requested and connected
        if execute_query and connection_state.is_connected():
            try:
                qe = connection_state.query_executor
                if qe:
                    # First attempt
                    exec_result = qe.validate_and_execute_dax(query_to_execute, top_n=100)

                    # Smart retry on composite key errors
                    if not exec_result.get('success'):
                        error_msg = exec_result.get('error', '').lower()
                        retry_patterns = ['composite', 'multiple columns', 'ambiguous', 'cannot determine']

                        if any(p in error_msg for p in retry_patterns) and field_param_filters:
                            # Retry without field parameter filters
                            logger.info(f"Composite key error, retrying without {len(field_param_filters)} field param filters")

                            measures = result.visual_info.measures or [result.measure_name]
                            measures = [m if m.startswith('[') else f'[{m}]' for m in measures]
                            columns = result.visual_info.columns or []

                            reduced_query = builder._build_visual_dax_query(measures, columns, data_filters)
                            retry_result = qe.validate_and_execute_dax(reduced_query, top_n=100)

                            if retry_result.get('success'):
                                exec_result = retry_result
                                response['retry_info'] = {
                                    'retried': True,
                                    'original_error': error_msg[:100],
                                    'excluded': [f"'{f.table}'[{f.column}]" for f in field_param_filters],
                                    'note': 'Results may differ from visual due to excluded field parameters'
                                }

                    if exec_result.get('success'):
                        rows = exec_result.get('rows', [])
                        response['result'] = {
                            'rows': rows,
                            'count': len(rows),
                            'ms': exec_result.get('execution_time_ms')
                        }
                        # Compact warnings for empty/null results
                        if not rows:
                            response['result']['note'] = 'no_rows'
                        elif all(all(v is None for v in row.values()) for row in rows):
                            response['result']['note'] = 'all_null'

                        # Anomaly detection on results
                        if rows and len(rows) > 1:
                            try:
                                from core.debug.anomaly_detector import analyze_results
                                anomaly_report = analyze_results(rows)
                                if anomaly_report:
                                    response['anomalies'] = anomaly_report
                            except (ImportError, KeyError, ValueError, TypeError) as ae:
                                logger.debug(f"Anomaly detection skipped: {ae}")
                    else:
                        response['result'] = {'error': exec_result.get('error')}
            except Exception as e:
                response['result'] = {'error': str(e)}
        elif execute_query:
            response['result'] = {'error': 'not_connected'}

        return response

    except Exception as e:
        logger.error(f"Error in debug_visual: {e}", exc_info=True)
        return ErrorHandler.handle_unexpected_error('debug_visual', e)


def handle_compare_measures(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compare original measure vs optimized version with same filter context.

    Can use filter context from a specific visual or manually specified.
    """
    try:
        original_measure = args.get('original_measure')
        optimized_expression = args.get('optimized_expression')
        page_name = args.get('page_name')
        visual_id = args.get('visual_id')
        visual_name = args.get('visual_name')
        manual_filters = args.get('filters', [])
        include_slicers = args.get('include_slicers', True)

        if not original_measure:
            return {'success': False, 'error': 'original_measure is required'}

        if not optimized_expression:
            return {'success': False, 'error': 'optimized_expression is required'}

        if not connection_state.is_connected():
            return {'success': False, 'error': 'Not connected to Power BI model'}

        qe = connection_state.query_executor
        if not qe:
            return ErrorHandler.handle_manager_unavailable('query_executor')

        # Build filter context
        filter_dax_parts = []

        if page_name and (visual_id or visual_name):
            # Get filter context from visual
            builder, error = _get_visual_query_builder()
            if not error and builder:
                # Load column types for accurate filter generation
                builder.load_column_types(qe)
                visual_info, filter_context = builder.get_visual_filter_context(
                    page_name, visual_id, visual_name, include_slicers
                )
                # Filter out field parameters and UI controls (they cause composite key errors)
                from core.debug.filter_to_dax import FilterClassification
                all_filters = filter_context.all_filters()
                data_filters = [f for f in all_filters if getattr(f, 'classification', FilterClassification.DATA) == FilterClassification.DATA]
                filter_dax_parts = [f.dax for f in data_filters if f.dax]

        # Add manual filters
        filter_dax_parts.extend(manual_filters)

        # Ensure measure has brackets
        if not original_measure.startswith('['):
            original_measure = f'[{original_measure}]'

        # Build queries
        filter_clause = ', '.join(filter_dax_parts) if filter_dax_parts else ''

        if filter_clause:
            original_query = f'EVALUATE ROW("Original", CALCULATE({original_measure}, {filter_clause}))'
            optimized_query = f'EVALUATE ROW("Optimized", CALCULATE({optimized_expression}, {filter_clause}))'
        else:
            original_query = f'EVALUATE ROW("Original", {original_measure})'
            optimized_query = f'EVALUATE ROW("Optimized", {optimized_expression})'

        # Execute both queries
        original_result = qe.validate_and_execute_dax(original_query, top_n=10)
        optimized_result = qe.validate_and_execute_dax(optimized_query, top_n=10)

        # Extract values
        original_value = None
        optimized_value = None
        original_time = original_result.get('execution_time_ms', 0)
        optimized_time = optimized_result.get('execution_time_ms', 0)

        if original_result.get('success') and original_result.get('rows'):
            row = original_result['rows'][0]
            original_value = row.get('Original', row.get('[Original]'))

        if optimized_result.get('success') and optimized_result.get('rows'):
            row = optimized_result['rows'][0]
            optimized_value = row.get('Optimized', row.get('[Optimized]'))

        # Compare
        values_match = False
        difference = None

        if original_value is not None and optimized_value is not None:
            try:
                orig_num = float(original_value)
                opt_num = float(optimized_value)
                difference = opt_num - orig_num
                values_match = abs(difference) < 0.001  # Small tolerance for floating point
            except (ValueError, TypeError):
                values_match = str(original_value) == str(optimized_value)
                difference = 'N/A (non-numeric)'

        # Performance comparison
        perf_improvement_ms = original_time - optimized_time
        perf_improvement_pct = (perf_improvement_ms / original_time * 100) if original_time > 0 else 0

        return {
            'success': True,
            'original': {
                'measure': original_measure,
                'query': original_query,
                'value': original_value,
                'execution_time_ms': original_time,
                'success': original_result.get('success', False),
                'error': original_result.get('error')
            },
            'optimized': {
                'expression': optimized_expression,
                'query': optimized_query,
                'value': optimized_value,
                'execution_time_ms': optimized_time,
                'success': optimized_result.get('success', False),
                'error': optimized_result.get('error')
            },
            'comparison': {
                'values_match': values_match,
                'difference': difference,
                'performance_improvement_ms': perf_improvement_ms,
                'performance_improvement_pct': round(perf_improvement_pct, 1)
            },
            'filter_context': {
                'source': f"visual:{visual_id or visual_name}" if page_name else 'manual',
                'filters_applied': len(filter_dax_parts),
                'filter_dax': filter_dax_parts
            }
        }

    except Exception as e:
        logger.error(f"Error in compare_measures: {e}", exc_info=True)
        return ErrorHandler.handle_unexpected_error('compare_measures', e)


def handle_list_slicers(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    List all slicers and their current saved selections.

    Shows which values are selected in each slicer (from saved PBIP state).
    """
    try:
        page_name = args.get('page_name')
        compact = args.get('compact', True)

        builder, error = _get_visual_query_builder()
        if error:
            return {'success': False, 'error': error}

        slicers = builder.list_slicers(page_name)

        if compact:
            # Compact mode: minimal info per slicer
            slicer_list = [
                {
                    'field': s.field_reference,
                    'values': s.selected_values[:5] if s.selected_values else [],  # Limit to 5 values
                    'count': len(s.selected_values) if len(s.selected_values) > 5 else None
                }
                for s in slicers
            ]
            return {
                'success': True,
                'slicers': slicer_list,
                'total': len(slicer_list)
            }
        else:
            # Verbose mode: full details
            slicer_list = [
                {
                    'id': s.slicer_id,
                    'page': s.page_name,
                    'field': s.field_reference,
                    'table': s.table,
                    'column': s.column,
                    'selection_mode': s.selection_mode,
                    'is_inverted': s.is_inverted,
                    'selected_values': s.selected_values,
                    'value_count': len(s.selected_values)
                }
                for s in slicers
            ]
            return {
                'success': True,
                'slicers': slicer_list,
                'count': len(slicer_list),
                'pbip_path': connection_state.pbip_path
            }

    except Exception as e:
        logger.error(f"Error in list_slicers: {e}", exc_info=True)
        return ErrorHandler.handle_unexpected_error('list_slicers', e)


def handle_drill_to_detail(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Show the underlying rows that make up an aggregated value.

    Uses the visual's filter context to query the fact table.
    """
    try:
        page_name = args.get('page_name')
        visual_id = args.get('visual_id')
        visual_name = args.get('visual_name')
        fact_table = args.get('fact_table')
        limit = args.get('limit', 100)
        limit = max(DRILL_DETAIL_LIMIT_MIN, min(DRILL_DETAIL_LIMIT_MAX, limit))  # Clamp to valid range
        include_slicers = args.get('include_slicers', True)

        if not connection_state.is_connected():
            return {'success': False, 'error': 'Not connected to Power BI model'}

        qe = connection_state.query_executor
        if not qe:
            return ErrorHandler.handle_manager_unavailable('query_executor')

        builder, error = _get_visual_query_builder()
        if error:
            return {'success': False, 'error': error}

        # Load column types for accurate filter generation
        builder.load_column_types(qe)

        # Build detail query
        query = builder.build_detail_rows_query(
            page_name=page_name or '',
            visual_id=visual_id,
            visual_name=visual_name,
            fact_table=fact_table,
            limit=limit,
            include_slicers=include_slicers
        )

        if not query:
            return {
                'success': False,
                'error': 'Could not build detail query. Specify fact_table if visual cannot be found.'
            }

        # Execute
        result = qe.validate_and_execute_dax(query, top_n=limit)

        if not result.get('success'):
            return {
                'success': False,
                'error': result.get('error'),
                'query_attempted': query
            }

        return {
            'success': True,
            'query': query,
            'row_count': result.get('row_count', len(result.get('rows', []))),
            'rows': result.get('rows', []),
            'columns': result.get('columns', []),
            'execution_time_ms': result.get('execution_time_ms')
        }

    except Exception as e:
        logger.error(f"Error in drill_to_detail: {e}", exc_info=True)
        return ErrorHandler.handle_unexpected_error('drill_to_detail', e)


def handle_set_pbip_path(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Manually set the PBIP folder path for visual debugging.

    Use this if auto-detection didn't work or you want to analyze a different project.
    """
    try:
        pbip_path = args.get('pbip_path')

        if not pbip_path:
            return {'success': False, 'error': 'pbip_path is required'}

        import os
        if not os.path.exists(pbip_path):
            return {'success': False, 'error': f'Path does not exist: {pbip_path}'}

        # Validate it looks like a PBIP folder
        definition_path = os.path.join(pbip_path, 'definition')
        report_path = os.path.join(pbip_path, 'report.json')

        if not os.path.exists(definition_path) and not os.path.exists(report_path):
            return {
                'success': False,
                'error': 'Path does not appear to be a valid PBIP folder. Expected definition/ folder or report.json.'
            }

        # Set the path
        result = connection_state.set_pbip_info(
            pbip_folder_path=pbip_path,
            file_full_path=pbip_path,
            file_type='pbip',
            source='manual'
        )

        return {
            'success': True,
            'pbip_info': result,
            'message': f'PBIP path set to: {pbip_path}'
        }

    except Exception as e:
        logger.error(f"Error in set_pbip_path: {e}", exc_info=True)
        return ErrorHandler.handle_unexpected_error('set_pbip_path', e)


def handle_get_debug_status(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get the current debug capabilities status.

    Shows whether PBIP and model connection are available.
    """
    try:
        compact = args.get('compact', True)
        pbip_info = connection_state.get_pbip_info()
        is_connected = connection_state.is_connected()
        pbip_available = pbip_info.get('pbip_available', False)

        builder = None
        pages = []
        if pbip_available:
            builder, _ = _get_visual_query_builder()
            if builder:
                pages = builder.list_pages()

        if compact:
            return {
                'success': True,
                'connected': is_connected,
                'pbip': pbip_available,
                'ready': is_connected and pbip_available,
                'pages': [p.get('name') for p in pages]
            }
        else:
            return {
                'success': True,
                'connection': {
                    'is_connected': is_connected,
                    'info': connection_state._connection_info
                },
                'pbip': pbip_info,
                'capabilities': {
                    'analyze_filters': pbip_available,
                    'execute_queries': is_connected,
                    'debug_visuals': pbip_available and is_connected,
                    'compare_measures': is_connected
                },
                'pages': pages,
                'recommendations': _get_recommendations(pbip_info, is_connected)
            }

    except Exception as e:
        logger.error(f"Error in get_debug_status: {e}", exc_info=True)
        return ErrorHandler.handle_unexpected_error('get_debug_status', e)


def _get_recommendations(pbip_info: Dict, is_connected: bool) -> List[str]:
    """Generate recommendations based on current status."""
    recommendations = []

    if not is_connected:
        recommendations.append("Connect to Power BI Desktop using connect_to_powerbi for query execution")

    if not pbip_info.get('pbip_available'):
        if pbip_info.get('file_type') == 'pbix':
            recommendations.append("You have a .pbix file open. Convert to PBIP (Save As > Power BI Project) for visual debugging")
        else:
            recommendations.append("Use set_pbip_path to specify your PBIP folder path for visual debugging")

    if is_connected and pbip_info.get('pbip_available'):
        recommendations.append("Full debugging available! Use debug_visual to analyze any visual")

    return recommendations


def handle_analyze_measure(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Analyze a measure's DAX expression and suggest fixes/optimizations.

    Gets the measure's DAX code, analyzes it for anti-patterns and issues,
    and optionally evaluates it with the filter context from a visual.
    """
    try:
        table_name = args.get('table_name')
        measure_name = args.get('measure_name')
        page_name = args.get('page_name')
        visual_id = args.get('visual_id')
        visual_name = args.get('visual_name')
        include_slicers = args.get('include_slicers', True)
        execute_measure = args.get('execute_measure', True)
        compact = args.get('compact', True)

        if not measure_name:
            return {'success': False, 'error': 'measure_name required'}

        if not connection_state.is_connected():
            return {'success': False, 'error': 'Not connected to Power BI model. Use connect_to_powerbi first.'}

        qe = connection_state.query_executor
        if not qe:
            return ErrorHandler.handle_manager_unavailable('query_executor')

        # Step 1: Get measure expression from model - try multiple sources
        # Priority: DMV (live model) -> TMDL files (offline) -> QueryExecutor fallback
        measure_details = {'success': False}
        clean_measure_name = measure_name.strip('[]')
        expression_source = None

        # Try 1: Query DMV for measure expression (most reliable for live model)
        info_result = qe.execute_info_query("MEASURES")
        if info_result.get('success') and info_result.get('rows'):
            for row in info_result['rows']:
                name = row.get('Name', row.get('[Name]', ''))
                if name.lower() == clean_measure_name.lower():
                    expression = row.get('Expression', row.get('[Expression]', ''))
                    table_id = row.get('TableID', row.get('[TableID]'))
                    format_string = row.get('FormatString', row.get('[FormatString]', ''))

                    # Get table name from TableID
                    found_table_name = table_name
                    if table_id and not found_table_name:
                        tables_result = qe.execute_info_query("TABLES")
                        if tables_result.get('success') and tables_result.get('rows'):
                            for table_row in tables_result['rows']:
                                tid = table_row.get('ID', table_row.get('[ID]', ''))
                                if str(tid) == str(table_id):
                                    found_table_name = table_row.get('Name', table_row.get('[Name]', ''))
                                    break

                    measure_details = {
                        'success': True,
                        'measure_name': name,
                        'expression': expression,
                        'table_name': found_table_name,
                        'table_id': table_id,
                        'format_string': format_string
                    }
                    expression_source = 'DMV'
                    break

        # Try 2: Search TMDL files if DMV didn't return expression
        if not measure_details.get('success') or not measure_details.get('expression'):
            builder, error = _get_visual_query_builder()
            if not error and builder:
                builder.load_column_types(qe)  # Initialize query executor reference
                tmdl_result = builder.get_measure_expression(clean_measure_name)
                if tmdl_result and tmdl_result.expression:
                    measure_details = {
                        'success': True,
                        'measure_name': tmdl_result.name,
                        'expression': tmdl_result.expression,
                        'table_name': tmdl_result.table or table_name,
                        'format_string': tmdl_result.format_string
                    }
                    expression_source = 'TMDL'

        # Try 3: Fallback to get_measure_details_with_fallback if above didn't work
        if not measure_details.get('success'):
            measure_details = qe.get_measure_details_with_fallback(table_name, measure_name)
            if measure_details.get('success'):
                expression_source = 'QueryExecutor fallback'

        if not measure_details.get('success'):
            return {
                'success': False,
                'error': f"Could not find measure '{measure_name}'. Specify table_name to narrow the search.",
                'hint': 'Use measure_operations with operation=list to see available measures'
            }

        expression = measure_details.get('expression', measure_details.get('Expression', ''))
        if not expression:
            return {
                'success': False,
                'error': f"Measure '{measure_name}' found but has no expression (may be a calculated column or external measure)"
            }

        # Step 2: Analyze the DAX expression
        try:
            from core.dax.dax_best_practices import DaxBestPracticesAnalyzer
            analyzer = DaxBestPracticesAnalyzer()
            analysis_result = analyzer.analyze(expression)
        except (ImportError, ValueError, TypeError) as e:
            logger.warning(f"DAX analysis failed: {e}")
            analysis_result = {
                'success': False,
                'error': str(e),
                'issues': [],
                'total_issues': 0
            }

        # Step 3: Get filter context from visual if specified
        filter_context_info = None
        filter_dax_parts = []

        if page_name and (visual_id or visual_name):
            builder, error = _get_visual_query_builder()
            if not error and builder:
                # Load column types for accurate filter generation
                builder.load_column_types(qe)
                visual_info, filter_context = builder.get_visual_filter_context(
                    page_name, visual_id, visual_name, include_slicers
                )
                filter_dax_parts = [f.dax for f in filter_context.all_filters()]
                filter_context_info = {
                    'visual': {
                        'id': visual_info.visual_id if visual_info else None,
                        'name': visual_info.visual_name if visual_info else None,
                        'page': page_name
                    },
                    'filters_applied': len(filter_dax_parts),
                    'filter_summary': {
                        'report_filters': len(filter_context.report_filters),
                        'page_filters': len(filter_context.page_filters),
                        'visual_filters': len(filter_context.visual_filters),
                        'slicer_filters': len(filter_context.slicer_filters)
                    },
                    'filter_dax': filter_dax_parts
                }

        # Step 4: Execute measure with filter context
        execution_result = None
        if execute_measure:
            measure_ref = f'[{measure_name.strip("[]")}]'
            filter_clause = ', '.join(filter_dax_parts) if filter_dax_parts else ''

            if filter_clause:
                query = f'EVALUATE ROW("Value", CALCULATE({measure_ref}, {filter_clause}))'
            else:
                query = f'EVALUATE ROW("Value", {measure_ref})'

            try:
                exec_result = qe.validate_and_execute_dax(query, top_n=10)
                if exec_result.get('success') and exec_result.get('rows'):
                    row = exec_result['rows'][0]
                    value = row.get('Value', row.get('[Value]'))
                    execution_result = {
                        'success': True,
                        'value': value,
                        'execution_time_ms': exec_result.get('execution_time_ms'),
                        'query': query
                    }
                else:
                    execution_result = {
                        'success': False,
                        'error': exec_result.get('error'),
                        'query': query
                    }
            except Exception as e:
                execution_result = {
                    'success': False,
                    'error': str(e),
                    'query': query
                }

        # Step 5: Generate fix suggestions based on analysis
        fix_suggestions = []
        if analysis_result.get('issues'):
            for issue in analysis_result['issues'][:5]:  # Top 5 issues
                suggestion = {
                    'issue': issue.get('title'),
                    'severity': issue.get('severity'),
                    'description': issue.get('description'),
                    'category': issue.get('category')
                }
                if issue.get('code_example_before') and issue.get('code_example_after'):
                    suggestion['example_fix'] = {
                        'before': issue.get('code_example_before'),
                        'after': issue.get('code_example_after')
                    }
                if issue.get('estimated_improvement'):
                    suggestion['estimated_improvement'] = issue.get('estimated_improvement')
                fix_suggestions.append(suggestion)

        # Build response - compact or verbose
        if compact:
            response = {
                'success': True,
                'measure': measure_name,
                'expression': expression[:300] + '...' if len(expression) > 300 else expression,
                'issues': analysis_result.get('total_issues', 0),
                'score': analysis_result.get('overall_score'),
                'fixes': [{'issue': s['issue'], 'severity': s['severity']} for s in fix_suggestions[:3]]
            }
            if execution_result and execution_result.get('success'):
                response['value'] = execution_result.get('value')
                response['ms'] = execution_result.get('execution_time_ms')
            elif execution_result:
                response['exec_error'] = execution_result.get('error')
        else:
            response = {
                'success': True,
                'measure': {
                    'name': measure_name,
                    'table': table_name or measure_details.get('table_name', 'Unknown'),
                    'expression': expression,
                    'format_string': measure_details.get('format_string'),
                    'source': expression_source
                },
                'analysis': {
                    'total_issues': analysis_result.get('total_issues', 0),
                    'critical': analysis_result.get('critical_issues', 0),
                    'high': analysis_result.get('high_issues', 0),
                    'score': analysis_result.get('overall_score'),
                    'complexity': analysis_result.get('complexity_level'),
                    'summary': analysis_result.get('summary')
                },
                'fix_suggestions': fix_suggestions
            }
            if filter_context_info:
                response['filter_context'] = filter_context_info
            if execution_result:
                response['execution'] = execution_result

        return response

    except Exception as e:
        logger.error(f"Error in analyze_measure: {e}", exc_info=True)
        return ErrorHandler.handle_unexpected_error('analyze_measure', e)


def _get_debug_operations():
    """Get DebugOperations instance with builder and query executor."""
    builder, error = _get_visual_query_builder()
    if error:
        return None, error

    qe = connection_state.query_executor if connection_state.is_connected() else None

    # Load column types if connected
    if qe:
        builder.load_column_types(qe)

    try:
        from core.debug.debug_operations import DebugOperations
        return DebugOperations(builder, qe), None
    except Exception as e:
        return None, f"Error initializing DebugOperations: {e}"


def handle_validate(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Consolidated validation operations for visual debugging.

    Operations:
    - cross_visual: Compare same measure across multiple visuals
    - expected_value: Assert visual returns expected value
    - filter_permutation: Test visual with different slicer combinations
    """
    try:
        operation = args.get('operation', 'cross_visual')

        ops, error = _get_debug_operations()
        if error:
            return {'success': False, 'error': error}

        if operation == 'cross_visual':
            measure_name = args.get('measure_name')
            if not measure_name:
                return {'success': False, 'error': 'measure_name is required for cross_visual validation'}
            return ops.cross_visual_validation(
                measure_name=measure_name,
                page_names=args.get('page_names'),
                tolerance=args.get('tolerance', 0.001)
            )

        elif operation == 'expected_value':
            page_name = args.get('page_name')
            if not page_name:
                return {'success': False, 'error': 'page_name is required for expected_value test'}
            return ops.expected_value_test(
                page_name=page_name,
                visual_id=args.get('visual_id'),
                visual_name=args.get('visual_name'),
                expected_value=args.get('expected_value'),
                filters=args.get('filters'),
                tolerance=args.get('tolerance', 0.001)
            )

        elif operation == 'filter_permutation':
            page_name = args.get('page_name')
            if not page_name:
                return {'success': False, 'error': 'page_name is required for filter_permutation test'}
            return ops.filter_permutation_test(
                page_name=page_name,
                visual_id=args.get('visual_id'),
                visual_name=args.get('visual_name'),
                max_permutations=args.get('max_permutations', 20)
            )

        else:
            return {
                'success': False,
                'error': f'Unknown operation: {operation}',
                'available_operations': ['cross_visual', 'expected_value', 'filter_permutation']
            }

    except Exception as e:
        logger.error(f"Error in validate: {e}", exc_info=True)
        return ErrorHandler.handle_unexpected_error('validate', e)


def handle_profile(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Consolidated profiling operations for performance analysis.

    Operations:
    - page: Profile all visuals on a page, rank by execution time
    - filter_matrix: Test measure performance with different filter combinations
    """
    try:
        operation = args.get('operation', 'page')
        page_name = args.get('page_name')

        if not page_name:
            # List available pages
            builder, error = _get_visual_query_builder()
            if error:
                return {'success': False, 'error': error}
            pages = builder.list_pages()
            return {
                'success': False,
                'error': 'page_name required',
                'pages': [p.get('name') for p in pages]
            }

        ops, error = _get_debug_operations()
        if error:
            return {'success': False, 'error': error}

        if operation == 'page':
            return ops.profile_page(
                page_name=page_name,
                iterations=args.get('iterations', 3),
                include_slicers=args.get('include_slicers', True)
            )

        elif operation == 'filter_matrix':
            return ops.filter_performance_matrix(
                page_name=page_name,
                visual_id=args.get('visual_id'),
                visual_name=args.get('visual_name'),
                filter_columns=args.get('filter_columns'),
                max_combinations=args.get('max_combinations', 15)
            )

        else:
            return {
                'success': False,
                'error': f'Unknown operation: {operation}',
                'available_operations': ['page', 'filter_matrix']
            }

    except Exception as e:
        logger.error(f"Error in profile: {e}", exc_info=True)
        return ErrorHandler.handle_unexpected_error('profile', e)


def handle_document(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Consolidated documentation operations.

    Operations:
    - page: Document all visuals on a page (data visuals only by default)
    - report: Document entire report
    - measure_lineage: Show which visuals use which measures
    - filter_lineage: Show which filters affect which visuals
    """
    try:
        operation = args.get('operation', 'page')
        # Lightweight mode (default True) skips expensive operations for faster documentation
        lightweight = args.get('lightweight', True)
        # Include UI elements (shapes, buttons, visual groups) - default False for cleaner output
        include_ui_elements = args.get('include_ui_elements', False)

        ops, error = _get_debug_operations()
        if error:
            return {'success': False, 'error': error}

        if operation == 'page':
            page_name = args.get('page_name')
            if not page_name:
                # List available pages
                builder, _ = _get_visual_query_builder()
                if builder:
                    pages = builder.list_pages()
                    return {
                        'success': False,
                        'error': 'page_name required',
                        'pages': [p.get('name') for p in pages]
                    }
            return ops.document_page(page_name, lightweight=lightweight, include_ui_elements=include_ui_elements)

        elif operation == 'report':
            return ops.document_report(lightweight=lightweight)

        elif operation == 'measure_lineage':
            return ops.measure_lineage(args.get('measure_name'))

        elif operation == 'filter_lineage':
            return ops.filter_lineage(args.get('page_name'))

        else:
            return {
                'success': False,
                'error': f'Unknown operation: {operation}',
                'available_operations': ['page', 'report', 'measure_lineage', 'filter_lineage']
            }

    except Exception as e:
        logger.error(f"Error in document: {e}", exc_info=True)
        return ErrorHandler.handle_unexpected_error('document', e)


def handle_advanced_analysis(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Consolidated advanced analysis operations.

    Operations:
    - decompose: Break down aggregated value by dimensions
    - contribution: Identify top contributors (Pareto analysis)
    - trend: Analyze value trend over time
    - root_cause: Analyze why a value changed
    - export: Export debug report as markdown/JSON
    """
    try:
        operation = args.get('operation', 'decompose')
        page_name = args.get('page_name')

        ops, error = _get_debug_operations()
        if error:
            return {'success': False, 'error': error}

        if operation == 'decompose':
            if not page_name:
                return {'success': False, 'error': 'page_name is required for decompose'}
            return ops.decompose_value(
                page_name=page_name,
                visual_id=args.get('visual_id'),
                visual_name=args.get('visual_name'),
                dimension=args.get('dimension'),
                top_n=args.get('top_n', 10)
            )

        elif operation == 'contribution':
            if not page_name:
                return {'success': False, 'error': 'page_name is required for contribution analysis'}
            return ops.contribution_analysis(
                page_name=page_name,
                visual_id=args.get('visual_id'),
                visual_name=args.get('visual_name'),
                dimension=args.get('dimension'),
                top_n=args.get('top_n', 10)
            )

        elif operation == 'trend':
            if not page_name:
                return {'success': False, 'error': 'page_name is required for trend analysis'}
            return ops.trend_analysis(
                page_name=page_name,
                visual_id=args.get('visual_id'),
                visual_name=args.get('visual_name'),
                date_column=args.get('date_column'),
                granularity=args.get('granularity', 'month')
            )

        elif operation == 'root_cause':
            if not page_name:
                return {'success': False, 'error': 'page_name is required for root_cause analysis'}
            return ops.root_cause_analysis(
                page_name=page_name,
                visual_id=args.get('visual_id'),
                visual_name=args.get('visual_name'),
                baseline_filters=args.get('baseline_filters'),
                comparison_filters=args.get('comparison_filters'),
                dimensions=args.get('dimensions'),
                top_n=args.get('top_n', 5)
            )

        elif operation == 'export':
            return ops.export_debug_report(
                page_name=page_name,
                visual_id=args.get('visual_id'),
                visual_name=args.get('visual_name'),
                format=args.get('format', 'markdown')
            )

        else:
            return {
                'success': False,
                'error': f'Unknown operation: {operation}',
                'available_operations': ['decompose', 'contribution', 'trend', 'root_cause', 'export']
            }

    except Exception as e:
        logger.error(f"Error in advanced_analysis: {e}", exc_info=True)
        return ErrorHandler.handle_unexpected_error('advanced_analysis', e)


def handle_debug_operations(args: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatch debug operations: visual, compare, drill, analyze"""
    operation = args.get('operation', 'visual')

    if operation == 'visual':
        return handle_debug_visual(args)
    elif operation == 'compare':
        return handle_compare_measures(args)
    elif operation == 'drill':
        return handle_drill_to_detail(args)
    elif operation == 'analyze':
        return handle_analyze_measure(args)
    else:
        return {
            'success': False,
            'error': f'Unknown operation: {operation}. Valid: visual, compare, drill, analyze'
        }


def handle_debug_config(args: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatch debug config operations: set_path, status"""
    operation = args.get('operation', 'status')

    if operation == 'set_path':
        return handle_set_pbip_path(args)
    elif operation == 'status':
        return handle_get_debug_status(args)
    else:
        return {
            'success': False,
            'error': f'Unknown operation: {operation}. Valid: set_path, status'
        }


def register_debug_handlers(registry):
    """Register debug handlers with the tool registry."""
    tools = [
        ToolDefinition(
            name="09_Debug_Operations",
            description="Visual debugger (visual), compare measures (compare), drill to detail (drill), analyze measure DAX (analyze).",
            handler=handle_debug_operations,
            input_schema={
                "type": "object",
                "properties": {
                    "operation": {"type": "string", "enum": ["visual", "compare", "drill", "analyze"], "default": "visual"},
                    "page_name": {"type": "string"},
                    "visual_id": {"type": "string"},
                    "visual_name": {"type": "string"},
                    "measure_name": {"type": "string"},
                    "table_name": {"type": "string", "description": "Table (analyze)"},
                    "include_slicers": {"type": "boolean"},
                    "execute_query": {"type": "boolean", "description": "Execute query (visual)"},
                    "execute_measure": {"type": "boolean", "description": "Execute measure (analyze)"},
                    "filters": {"type": "array", "items": {"type": "string"}, "description": "Manual DAX filters"},
                    "skip_auto_filters": {"type": "boolean"},
                    "compact": {"type": "boolean"},
                    "original_measure": {"type": "string", "description": "Original measure (compare)"},
                    "optimized_expression": {"type": "string", "description": "Optimized DAX (compare)"},
                    "fact_table": {"type": "string", "description": "Fact table (drill)"},
                    "limit": {"type": "integer", "description": "Max rows (drill, default: 100)"}
                },
                "required": []
            },
            category="debug",
            sort_order=90
        ),
        ToolDefinition(
            name="09_Debug_Config",
            description="Config: set_path (set PBIP path), status (debug capabilities).",
            handler=handle_debug_config,
            input_schema={
                "type": "object",
                "properties": {
                    "operation": {"type": "string", "enum": ["set_path", "status"], "default": "status"},
                    "pbip_path": {"type": "string", "description": "PBIP folder path (set_path)"},
                    "compact": {"type": "boolean"}
                },
                "required": []
            },
            category="debug",
            sort_order=91
        ),
        ToolDefinition(
            name="09_Validate",
            description="Validation: cross_visual, expected_value, filter_permutation.",
            handler=handle_validate,
            input_schema={
                "type": "object",
                "properties": {
                    "operation": {"type": "string", "enum": ["cross_visual", "expected_value", "filter_permutation"]},
                    "measure_name": {"type": "string"},
                    "page_name": {"type": "string"},
                    "page_names": {"type": "array", "items": {"type": "string"}},
                    "visual_id": {"type": "string"},
                    "visual_name": {"type": "string"},
                    "expected_value": {"type": ["number", "string"]},
                    "filters": {"type": "array", "items": {"type": "string"}},
                    "tolerance": {"type": "number"},
                    "max_permutations": {"type": "integer"}
                },
                "required": ["operation"]
            },
            category="debug",
            sort_order=92
        ),
        ToolDefinition(
            name="09_Profile",
            description="Profiling: page (rank visuals by time), filter_matrix (test filter combos).",
            handler=handle_profile,
            input_schema={
                "type": "object",
                "properties": {
                    "operation": {"type": "string", "enum": ["page", "filter_matrix"]},
                    "page_name": {"type": "string"},
                    "visual_id": {"type": "string"},
                    "visual_name": {"type": "string"},
                    "iterations": {"type": "integer"},
                    "include_slicers": {"type": "boolean"},
                    "filter_columns": {"type": "array", "items": {"type": "string"}},
                    "max_combinations": {"type": "integer"}
                },
                "required": ["page_name"]
            },
            category="debug",
            sort_order=93
        ),
        ToolDefinition(
            name="09_Document",
            description="Documentation: page, report, measure_lineage, filter_lineage. Data visuals only by default.",
            handler=handle_document,
            input_schema={
                "type": "object",
                "properties": {
                    "operation": {"type": "string", "enum": ["page", "report", "measure_lineage", "filter_lineage"]},
                    "page_name": {"type": "string"},
                    "measure_name": {"type": "string"},
                    "lightweight": {"type": "boolean"},
                    "include_ui_elements": {"type": "boolean"}
                },
                "required": ["operation"]
            },
            category="debug",
            sort_order=94
        ),
        ToolDefinition(
            name="09_Advanced_Analysis",
            description="Advanced: decompose, contribution, trend, root_cause, export.",
            handler=handle_advanced_analysis,
            input_schema={
                "type": "object",
                "properties": {
                    "operation": {"type": "string", "enum": ["decompose", "contribution", "trend", "root_cause", "export"]},
                    "page_name": {"type": "string"},
                    "visual_id": {"type": "string"},
                    "visual_name": {"type": "string"},
                    "dimension": {"type": "string"},
                    "date_column": {"type": "string"},
                    "granularity": {"type": "string", "enum": ["day", "week", "month", "quarter", "year"]},
                    "baseline_filters": {"type": "array", "items": {"type": "string"}},
                    "comparison_filters": {"type": "array", "items": {"type": "string"}},
                    "dimensions": {"type": "array", "items": {"type": "string"}},
                    "top_n": {"type": "integer"},
                    "format": {"type": "string", "enum": ["markdown", "json"]}
                },
                "required": ["operation"]
            },
            category="debug",
            sort_order=95
        )
    ]

    for tool in tools:
        registry.register(tool)

    logger.info(f"Registered {len(tools)} debug handlers")
