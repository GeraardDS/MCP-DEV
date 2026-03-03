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
from core.config.config_manager import config

logger = logging.getLogger(__name__)

# --- Module-level constants ---
PBIP_FRESHNESS_THRESHOLD_MINUTES = config.get(
    'debug.pbip_freshness_minutes', 5
)
DRILL_DETAIL_LIMIT_MIN = 1
DRILL_DETAIL_LIMIT_MAX = 10000
MAX_MEASURES_SHOWN = config.get('debug.max_measures_shown', 3)
MAX_QUERY_RESULT_ROWS = config.get(
    'debug.max_query_result_rows', 100
)
FILTER_TRUNCATION_CHARS = config.get(
    'debug.filter_truncation_chars', 50
)
VARIABLE_TRUNCATION_CHARS = config.get(
    'debug.variable_truncation_chars', 100
)

# Module-level VQB cache — avoids rebuilding PBIP per call
# Key: pbip_path, Value: (builder, timestamp)
_vqb_cache: Dict[str, tuple] = {}
_VQB_CACHE_TTL = config.get(
    'debug.vqb_cache_ttl_seconds', 300
)


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
    # Return only essential fields: id, friendly_name, type, measures
    return [
        {
            'id': v.get('id'),
            'name': v.get('friendly_name', v.get('type', '?')),
            'type': v.get('type_display', v.get('type', '')),
            'measures': v.get('measures', [])[:MAX_MEASURES_SHOWN]
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
    """Get VisualQueryBuilder instance with TTL cache.

    Caches the builder per pbip_path for _VQB_CACHE_TTL seconds
    to avoid rebuilding the PBIP project on every call (11+ per
    request).  A changed pbip_path evicts the old entry.
    """
    global _vqb_cache

    pbip_folder = connection_state.get_pbip_folder_path()
    if not pbip_folder:
        return None, (
            "PBIP folder not available. Either open a .pbip "
            "project in Power BI Desktop, or use set_pbip_path "
            "to specify the path manually."
        )

    now = time.time()
    cached = _vqb_cache.get(pbip_folder)
    if cached is not None:
        builder, ts = cached
        if (now - ts) < _VQB_CACHE_TTL:
            return builder, None

    # Path changed — clear stale entries for other paths
    if _vqb_cache and pbip_folder not in _vqb_cache:
        _vqb_cache.clear()

    try:
        from core.debug.visual_query_builder import VisualQueryBuilder
        builder = VisualQueryBuilder(pbip_folder)
        _vqb_cache[pbip_folder] = (builder, now)
        return builder, None
    except Exception as e:
        return None, f"Error initializing VisualQueryBuilder: {e}"


def _discover_visuals(
    args: Dict[str, Any],
    builder: Any,
    compact: bool
) -> Optional[Dict[str, Any]]:
    """Handle discovery when page/visual not fully specified.

    Returns a discovery response dict if page or visual is missing,
    or None if both are specified and valid.
    """
    page_name = args.get('page_name')
    visual_id = args.get('visual_id')
    visual_name = args.get('visual_name')

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
    page_exists = any(
        p['name'].lower() == page_name.lower() for p in pages
    )
    if not page_exists:
        return {
            'success': False,
            'error': f"Page '{page_name}' not found",
            'pages': _compact_page_list(pages, compact)
        }

    # If visual_id/visual_name not provided, list visuals on page
    if not visual_id and not visual_name:
        visuals = builder.list_visuals(page_name)
        non_slicer = [
            v for v in visuals if not v.get('is_slicer')
        ]
        slicer = [
            v for v in visuals if v.get('is_slicer')
        ]
        return {
            'success': False,
            'error': 'visual_id or visual_name required',
            'page': page_name,
            'visuals': _compact_visual_list(non_slicer, compact),
            'slicers': [
                {
                    'id': v.get('id'),
                    'field': (
                        v.get('columns', ['?'])[0]
                        if v.get('columns') else '?'
                    )
                }
                for v in slicer
            ] if slicer else None
        }

    return None  # All specified — proceed with main logic


def _build_filter_context(
    builder: Any,
    result: Any,
    page_name: str,
    compact: bool,
    include_slicers: bool,
    pbip_freshness: Optional[Dict]
) -> Dict[str, Any]:
    """Classify filters and assemble the base response dict.

    Returns a dict with keys: response, all_filters, data_filters,
    field_param_filters, ui_control_filters,
    slicers_without_selection.
    """
    from core.debug.filter_to_dax import FilterClassification

    # Check for slicers with no selection
    slicers_without_selection = []
    all_slicers = builder.list_slicers(page_name)
    for slicer in all_slicers:
        if not slicer.selected_values:
            slicers_without_selection.append({
                'field': slicer.field_reference,
                'table': slicer.table,
                'column': slicer.column
            })

    # Classify filters
    all_filters = result.filter_context.all_filters()

    # Reliable detection methods for field parameters
    RELIABLE_FP_METHODS = {
        'nameof_pattern', 'switch_pattern', 'system_flags'
    }

    # Enhance classification with semantic analysis
    if connection_state.is_connected():
        try:
            classifier = builder._init_semantic_classifier()
            if classifier:
                for f in all_filters:
                    if not f.table:
                        continue
                    sc = classifier.classify(f.table, f.column)
                    if sc.classification == 'field_parameter':
                        if (
                            sc.detection_method in RELIABLE_FP_METHODS
                            and sc.confidence > 0.80
                        ):
                            f.classification = (
                                FilterClassification.FIELD_PARAMETER
                            )
                    elif (
                        sc.classification == 'ui_control'
                        and sc.confidence > 0.80
                    ):
                        f.classification = (
                            FilterClassification.UI_CONTROL
                        )
        except (AttributeError, ValueError, TypeError) as se:
            logger.debug(
                f"Semantic classification skipped: {se}"
            )

    data_filters = [
        f for f in all_filters
        if getattr(f, 'classification', 'data')
        == FilterClassification.DATA
    ]
    field_param_filters = [
        f for f in all_filters
        if getattr(f, 'classification', 'data')
        == FilterClassification.FIELD_PARAMETER
    ]
    ui_control_filters = [
        f for f in all_filters
        if getattr(f, 'classification', 'data')
        == FilterClassification.UI_CONTROL
    ]
    filters_with_nulls = [
        f for f in all_filters
        if getattr(f, 'has_null_values', False)
    ]

    # Build base response
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
        'filters': _compact_filter_context(
            result.filter_breakdown, compact
        ),
        'filter_counts': {
            'total': len(all_filters),
            'applied': len(data_filters),
            'excluded': (
                len(field_param_filters) + len(ui_control_filters)
            )
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

    # Verbose-only fields
    if not compact:
        response['pbip_path'] = connection_state.pbip_path
        response['title'] = result.visual_info.title

    if not compact and (field_param_filters or ui_control_filters):
        excluded = []
        for f in field_param_filters:
            excluded.append({
                'table': f.table, 'column': f.column,
                'type': 'field_param'
            })
        for f in ui_control_filters:
            excluded.append({
                'table': f.table, 'column': f.column,
                'type': 'ui_control'
            })
        response['excluded_filters'] = excluded

    if (
        not compact
        and include_slicers
        and result.filter_context.slicer_filters
    ):
        response['slicer_details'] = [
            {
                'field': f"{sf.table}[{sf.column}]",
                'dax': sf.dax,
                'values': sf.values[:5]
            }
            for sf in result.filter_context.slicer_filters
        ]

    if not compact and result.measure_definitions:
        response['measure_definitions'] = [
            {
                'name': m.name,
                'expression': (
                    m.expression[:800] + '... [truncated]'
                    if len(m.expression) > 800
                    else m.expression
                )
            }
            for m in result.measure_definitions
        ]

    if not compact and result.expanded_query:
        response['expanded_query'] = result.expanded_query

    # Always surface detected format string companion measures so the caller
    # knows they are included as IGNORE() args in the trace query.
    fs_measures = getattr(result, 'format_string_measures', [])
    if fs_measures:
        response['format_string_measures'] = fs_measures

    return {
        'response': response,
        'all_filters': all_filters,
        'data_filters': data_filters,
        'field_param_filters': field_param_filters,
        'ui_control_filters': ui_control_filters,
        'slicers_without_selection': slicers_without_selection,
    }


def _apply_manual_filters(
    args: Dict[str, Any],
    result: Any,
    builder: Any,
    response: Dict[str, Any],
    data_filters: List,
    query_to_execute: str
) -> str:
    """Handle manual filter overrides and skip_auto_filters logic.

    Mutates response dict in-place. Returns the (possibly updated)
    query_to_execute string.
    """
    import re
    from core.debug.filter_to_dax import FilterExpression

    manual_filters = args.get('filters', [])
    skip_auto_filters = args.get('skip_auto_filters', False)

    if skip_auto_filters:
        measures = (
            result.visual_info.measures or [result.measure_name]
        )
        measures = [
            m if m.startswith('[') else f'[{m}]'
            for m in measures
        ]
        columns = result.visual_info.columns or []

        if manual_filters:
            manual_objs = [
                FilterExpression(
                    dax=f, source='manual', table='',
                    column='', condition_type='Manual',
                    values=[]
                )
                for f in manual_filters
            ]
            query_to_execute = builder._build_visual_dax_query(
                measures, columns, manual_objs,
                format_string_measures=getattr(result, 'format_string_measures', [])
            )
            response['generated_query'] = query_to_execute
            response['auto_filters_skipped'] = True
            response['manual_filters_applied'] = manual_filters
        else:
            query_to_execute = builder._build_visual_dax_query(
                measures, columns, [],
                format_string_measures=getattr(result, 'format_string_measures', [])
            )
            response['generated_query'] = query_to_execute
            response['auto_filters_skipped'] = True
            response['note'] = (
                'Auto-detected filters skipped. Provide '
                'filters parameter for manual DAX filters.'
            )

    elif manual_filters:
        # Extract table.column refs from manual filters
        manual_filter_columns = set()
        for mf in manual_filters:
            matches = re.findall(
                r"['\"]?([^'\"]+)['\"]?\[([^\]]+)\]", mf
            )
            for table, col in matches:
                table_clean = table.strip("'\"")
                manual_filter_columns.add(
                    (table_clean.lower(), col.lower())
                )

        # Separate conflicting vs non-conflicting auto-filters
        non_conflicting = []
        skipped = []
        for f in data_filters:
            if f.dax:
                if f.table and f.column:
                    key = (f.table.lower(), f.column.lower())
                    if key in manual_filter_columns:
                        skipped.append(f)
                        continue
                non_conflicting.append(f)

        # Combine non-conflicting auto + manual filters
        all_dax = [f.dax for f in non_conflicting]
        all_dax.extend(manual_filters)

        measures = (
            result.visual_info.measures or [result.measure_name]
        )
        measures = [
            m if m.startswith('[') else f'[{m}]'
            for m in measures
        ]
        columns = result.visual_info.columns or []

        combined = [
            FilterExpression(
                dax=f, source='manual', table='',
                column='', condition_type='Manual',
                values=[]
            )
            for f in all_dax
        ]
        query_to_execute = builder._build_visual_dax_query(
            measures, columns, combined,
            format_string_measures=getattr(result, 'format_string_measures', [])
        )

        response['generated_query'] = query_to_execute
        response['query_with_manual_filters'] = query_to_execute
        response['manual_filters_applied'] = manual_filters

        if skipped:
            response['auto_filters_overridden'] = [
                {
                    'table': f.table,
                    'column': f.column,
                    'original_dax': f.dax,
                    'reason': (
                        'Overridden by manual filter '
                        'on same column'
                    )
                }
                for f in skipped
            ]

    return query_to_execute


def _execute_visual_query(
    query_to_execute: str,
    response: Dict[str, Any],
    builder: Any,
    result: Any,
    all_filters: List,
    data_filters: List,
    field_param_filters: List,
    compact: bool,
    slicers_without_selection: List,
    execute_query: bool,
    trace: bool = False,
    clear_cache: bool = True,
) -> None:
    """Execute DAX query with retry, add results to response.

    Also performs relationship analysis, aggregation matching,
    slicer warnings, and anomaly detection. Mutates response
    in-place.

    When trace=True, runs SE/FE timing analysis via NativeTraceRunner
    before the normal query execution (cold cache first, warm rows second).
    """
    # Add warning if slicers have no selection
    if slicers_without_selection:
        if compact:
            response['empty_slicers'] = len(
                slicers_without_selection
            )
        else:
            response['warnings'] = [{
                'type': 'empty_slicers',
                'count': len(slicers_without_selection),
                'slicers': slicers_without_selection
            }]

    # Advanced analysis: relationships and aggregation
    if connection_state.is_connected():
        qe = connection_state.query_executor
        if qe:
            measure_tables = list(set(
                getattr(m, 'table', '')
                for m in (result.measure_definitions or [])
                if getattr(m, 'table', '')
            ))
            filter_tables = list(set(
                f.table for f in all_filters if f.table
            ))
            grouping_tables = list(set(
                col.split('[')[0].strip("'\"")
                for col in (result.visual_info.columns or [])
                if '[' in col
            ))

            # Relationship analysis
            try:
                resolver = (
                    builder._init_relationship_resolver()
                )
                if resolver:
                    hints = resolver.analyze_query_tables(
                        measure_tables, filter_tables,
                        grouping_tables
                    )
                    if hints:
                        response['relationship_hints'] = [
                            {
                                'type': h.type,
                                'tables': (
                                    f"{h.from_table} -> "
                                    f"{h.to_table}"
                                ),
                                'suggestion': (
                                    h.dax_modifier
                                    if h.dax_modifier
                                    else h.reason
                                ),
                                'severity': h.severity
                            }
                            for h in hints[:MAX_MEASURES_SHOWN]
                        ]
            except (
                AttributeError, ValueError, TypeError
            ) as re_err:
                logger.debug(
                    f"Relationship analysis skipped: {re_err}"
                )

            # Aggregation matching
            try:
                agg_matcher = (
                    builder._init_aggregation_matcher()
                )
                if agg_matcher:
                    grp_cols = (
                        result.visual_info.columns or []
                    )
                    flt_cols = [
                        f"'{f.table}'[{f.column}]"
                        for f in data_filters
                        if f.table and f.column
                    ]
                    agg_match = (
                        agg_matcher.find_matching_aggregation(
                            grp_cols, flt_cols
                        )
                    )
                    if agg_match:
                        response['aggregation_info'] = {
                            'available': True,
                            'table': agg_match.agg_table,
                            'confidence': (
                                agg_match.match_confidence
                            ),
                            'recommendation': (
                                agg_match.recommendation
                            )
                        }
            except (
                AttributeError, ValueError, TypeError
            ) as ae:
                logger.debug(
                    f"Aggregation analysis skipped: {ae}"
                )

    # SE/FE trace — runs first (cold cache) so timing is accurate.
    # If execute_query is also True it runs after on warm cache (fast row fetch).
    if trace and connection_state.is_connected():
        try:
            from core.infrastructure.query_trace import NativeTraceRunner
            conn_str = (
                connection_state.connection_manager.connection_string
            )
            if not conn_str:
                response['se_fe_trace'] = {
                    'error': 'No connection string available'
                }
            elif not NativeTraceRunner.is_available():
                response['se_fe_trace'] = {
                    'error': (
                        'DaxExecutor.exe not found. '
                        'Build: cd core/infrastructure/dax_executor '
                        '&& dotnet build -c Release'
                    )
                }
            else:
                runner = NativeTraceRunner(conn_str)
                trace_result = runner.execute_with_trace(
                    query_to_execute, clear_cache
                )
                if '_error' in trace_result:
                    response['se_fe_trace'] = {
                        'error': trace_result['_error']
                    }
                else:
                    perf = {
                        'total_ms': trace_result.get('total_ms', 0),
                        'fe_ms': trace_result.get('fe_ms', 0),
                        'se_ms': trace_result.get('se_ms', 0),
                        'se_cpu_ms': trace_result.get('se_cpu_ms', 0),
                        'se_parallelism': trace_result.get(
                            'se_parallelism', 0.0
                        ),
                        'se_queries': trace_result.get('se_queries', 0),
                        'se_cache_hits': trace_result.get(
                            'se_cache_hits', 0
                        ),
                        'fe_pct': trace_result.get('fe_pct', 0.0),
                        'se_pct': trace_result.get('se_pct', 0.0),
                    }
                    response['se_fe_trace'] = {
                        'runner': 'native',
                        'performance': perf,
                        'se_events': trace_result.get('se_events', []),
                        'cache_cleared': trace_result.get(
                            'cache_cleared', False
                        ),
                        'summary': (
                            f"Total: {perf['total_ms']}ms | "
                            f"FE: {perf['fe_ms']}ms "
                            f"({perf['fe_pct']}%) | "
                            f"SE: {perf['se_ms']}ms "
                            f"({perf['se_pct']}%) | "
                            f"SE queries: {perf['se_queries']} | "
                            f"SE cache: {perf['se_cache_hits']}"
                        ),
                    }
        except Exception as te:
            logger.error(f"SE/FE trace failed: {te}", exc_info=True)
            response['se_fe_trace'] = {'error': str(te)}
    elif trace:
        response['se_fe_trace'] = {'error': 'not_connected'}

    # Execute query if requested and connected
    if execute_query and connection_state.is_connected():
        try:
            qe = connection_state.query_executor
            if qe:
                exec_result = qe.validate_and_execute_dax(
                    query_to_execute,
                    top_n=MAX_QUERY_RESULT_ROWS
                )

                # Smart retry on composite key errors
                if not exec_result.get('success'):
                    error_msg = (
                        exec_result.get('error', '').lower()
                    )
                    retry_patterns = [
                        'composite', 'multiple columns',
                        'ambiguous', 'cannot determine',
                    ]
                    if (
                        any(
                            p in error_msg
                            for p in retry_patterns
                        )
                        and field_param_filters
                    ):
                        logger.info(
                            "Composite key error, retrying "
                            "without "
                            f"{len(field_param_filters)}"
                            " field param filters"
                        )
                        measures = (
                            result.visual_info.measures
                            or [result.measure_name]
                        )
                        measures = [
                            m if m.startswith('[')
                            else f'[{m}]'
                            for m in measures
                        ]
                        columns = (
                            result.visual_info.columns or []
                        )
                        reduced_query = (
                            builder._build_visual_dax_query(
                                measures, columns,
                                data_filters
                            )
                        )
                        retry_result = (
                            qe.validate_and_execute_dax(
                                reduced_query,
                                top_n=MAX_QUERY_RESULT_ROWS
                            )
                        )
                        if retry_result.get('success'):
                            exec_result = retry_result
                            response['retry_info'] = {
                                'retried': True,
                                'original_error': (
                                    error_msg[
                                        :VARIABLE_TRUNCATION_CHARS
                                    ]
                                ),
                                'excluded': [
                                    f"'{f.table}'[{f.column}]"
                                    for f in field_param_filters
                                ],
                                'note': (
                                    'Results may differ from '
                                    'visual due to excluded '
                                    'field parameters'
                                )
                            }

                if exec_result.get('success'):
                    rows = exec_result.get('rows', [])
                    response['result'] = {
                        'rows': rows,
                        'count': len(rows),
                        'ms': exec_result.get(
                            'execution_time_ms'
                        )
                    }
                    if not rows:
                        response['result']['note'] = 'no_rows'
                    elif all(
                        all(v is None for v in row.values())
                        for row in rows
                    ):
                        response['result']['note'] = 'all_null'

                    # Anomaly detection
                    if rows and len(rows) > 1:
                        try:
                            from core.debug.anomaly_detector import (
                                analyze_results,
                            )
                            report = analyze_results(rows)
                            if report:
                                response['anomalies'] = report
                        except (
                            ImportError, KeyError,
                            ValueError, TypeError
                        ) as ae:
                            logger.debug(
                                "Anomaly detection skipped: "
                                f"{ae}"
                            )
                else:
                    response['result'] = {
                        'error': exec_result.get('error')
                    }
        except Exception as e:
            response['result'] = {'error': str(e)}
    elif execute_query:
        response['result'] = {'error': 'not_connected'}


def handle_debug_visual(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Debug a visual: filter context + query execution.

    Combines PBIP analysis (for filter context) with live model
    (for execution). Self-sufficient: lists pages/visuals when
    not found.
    """
    try:
        compact = args.get('compact', True)
        execute_query = args.get('execute_query', True)
        include_slicers = args.get('include_slicers', True)
        trace = args.get('trace', False)
        clear_cache = args.get('clear_cache', True)

        # Get builder — needed for all operations
        builder, error = _get_visual_query_builder()
        if error:
            return {'success': False, 'error': error}

        # Step 1: Discovery — return early if page/visual missing
        discovery = _discover_visuals(args, builder, compact)
        if discovery is not None:
            return discovery

        # Load column types for accurate type detection
        if connection_state.is_connected():
            qe = connection_state.query_executor
            if qe:
                types_loaded = builder.load_column_types(qe)
                if types_loaded > 0:
                    logger.debug(
                        f"Loaded {types_loaded} column types"
                    )

        # Build visual query
        page_name = args.get('page_name')
        result = builder.build_visual_query(
            page_name=page_name,
            visual_id=args.get('visual_id'),
            visual_name=args.get('visual_name'),
            measure_name=args.get('measure_name'),
            include_slicers=include_slicers,
            measures=args.get('measures'),
        )

        if not result:
            visuals = builder.list_visuals(page_name)
            non_slicer = [
                v for v in visuals if not v.get('is_slicer')
            ]
            return {
                'success': False,
                'error': (
                    "Visual not found: "
                    f"id='{args.get('visual_id')}', "
                    f"name='{args.get('visual_name')}'"
                ),
                'visuals': _compact_visual_list(
                    non_slicer, compact
                )
            }

        # Step 2: Build filter context and base response
        pbip_freshness = _check_pbip_freshness(
            connection_state.get_pbip_folder_path()
        )
        ctx = _build_filter_context(
            builder, result, page_name, compact,
            include_slicers, pbip_freshness
        )
        response = ctx['response']

        # Step 3: Apply manual filter overrides
        query_to_execute = _apply_manual_filters(
            args, result, builder, response,
            ctx['data_filters'], result.dax_query
        )

        # Step 4: Execute query + advanced analysis
        _execute_visual_query(
            query_to_execute, response, builder, result,
            ctx['all_filters'], ctx['data_filters'],
            ctx['field_param_filters'], compact,
            ctx['slicers_without_selection'], execute_query,
            trace=trace,
            clear_cache=clear_cache,
        )

        return response

    except Exception as e:
        logger.error(
            f"Error in debug_visual: {e}", exc_info=True
        )
        return ErrorHandler.handle_unexpected_error(
            'debug_visual', e
        )


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
        limit = args.get('limit', MAX_QUERY_RESULT_ROWS)
        limit = max(DRILL_DETAIL_LIMIT_MIN, min(DRILL_DETAIL_LIMIT_MAX, limit))
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


def _resolve_measure_expression(
    measure_name: str,
    table_name: Optional[str],
    qe: Any
) -> Dict[str, Any]:
    """Find measure expression from model via DMV, TMDL, or fallback.

    Returns dict with keys: success, measure_details, expression,
    expression_source. On failure, returns success=False with error.
    """
    clean_name = measure_name.strip('[]')
    measure_details: Dict[str, Any] = {'success': False}
    expression_source = None

    # Try 1: DMV (most reliable for live model)
    info_result = qe.execute_info_query("MEASURES")
    if info_result.get('success') and info_result.get('rows'):
        for row in info_result['rows']:
            name = row.get('Name', row.get('[Name]', ''))
            if name.lower() == clean_name.lower():
                expression = row.get(
                    'Expression', row.get('[Expression]', '')
                )
                table_id = row.get(
                    'TableID', row.get('[TableID]')
                )
                fmt = row.get(
                    'FormatString',
                    row.get('[FormatString]', '')
                )

                found_table = table_name
                if table_id and not found_table:
                    tables_result = qe.execute_info_query(
                        "TABLES"
                    )
                    if (
                        tables_result.get('success')
                        and tables_result.get('rows')
                    ):
                        for trow in tables_result['rows']:
                            tid = trow.get(
                                'ID', trow.get('[ID]', '')
                            )
                            if str(tid) == str(table_id):
                                found_table = trow.get(
                                    'Name',
                                    trow.get('[Name]', '')
                                )
                                break

                measure_details = {
                    'success': True,
                    'measure_name': name,
                    'expression': expression,
                    'table_name': found_table,
                    'table_id': table_id,
                    'format_string': fmt
                }
                expression_source = 'DMV'
                break

    # Try 2: TMDL files
    if (
        not measure_details.get('success')
        or not measure_details.get('expression')
    ):
        builder, error = _get_visual_query_builder()
        if not error and builder:
            builder.load_column_types(qe)
            tmdl_result = builder.get_measure_expression(
                clean_name
            )
            if tmdl_result and tmdl_result.expression:
                measure_details = {
                    'success': True,
                    'measure_name': tmdl_result.name,
                    'expression': tmdl_result.expression,
                    'table_name': (
                        tmdl_result.table or table_name
                    ),
                    'format_string': tmdl_result.format_string
                }
                expression_source = 'TMDL'

    # Try 3: QueryExecutor fallback
    if not measure_details.get('success'):
        measure_details = qe.get_measure_details_with_fallback(
            table_name, measure_name
        )
        if measure_details.get('success'):
            expression_source = 'QueryExecutor fallback'

    if not measure_details.get('success'):
        return {
            'success': False,
            'error': (
                f"Could not find measure '{measure_name}'. "
                "Specify table_name to narrow the search."
            ),
            'hint': (
                'Use measure_operations with operation=list '
                'to see available measures'
            )
        }

    expression = measure_details.get(
        'expression', measure_details.get('Expression', '')
    )
    if not expression:
        return {
            'success': False,
            'error': (
                f"Measure '{measure_name}' found but has no "
                "expression (may be a calculated column or "
                "external measure)"
            )
        }

    return {
        'success': True,
        'measure_details': measure_details,
        'expression': expression,
        'expression_source': expression_source
    }


def _analyze_measure_dax(
    expression: str,
) -> Dict[str, Any]:
    """Run DAX best practices analysis on an expression.

    Returns the analysis result dict.
    """
    try:
        from core.dax.dax_best_practices import (
            DaxBestPracticesAnalyzer,
        )
        analyzer = DaxBestPracticesAnalyzer()
        return analyzer.analyze(expression)
    except (ImportError, ValueError, TypeError) as e:
        logger.warning(f"DAX analysis failed: {e}")
        return {
            'success': False,
            'error': str(e),
            'issues': [],
            'total_issues': 0
        }


def _get_visual_filter_context_for_measure(
    page_name: str,
    visual_id: Optional[str],
    visual_name: Optional[str],
    include_slicers: bool,
    qe: Any
) -> tuple:
    """Get filter context from a visual/page for measure analysis.

    Returns (filter_context_info, filter_dax_parts) tuple.
    filter_context_info is None if no visual context available.
    """
    filter_context_info = None
    filter_dax_parts: List[str] = []

    if not page_name or not (visual_id or visual_name):
        return filter_context_info, filter_dax_parts

    builder, error = _get_visual_query_builder()
    if error or not builder:
        return filter_context_info, filter_dax_parts

    builder.load_column_types(qe)
    visual_info, filter_context = (
        builder.get_visual_filter_context(
            page_name, visual_id, visual_name,
            include_slicers
        )
    )
    filter_dax_parts = [
        f.dax for f in filter_context.all_filters()
    ]
    filter_context_info = {
        'visual': {
            'id': (
                visual_info.visual_id if visual_info
                else None
            ),
            'name': (
                visual_info.visual_name if visual_info
                else None
            ),
            'page': page_name
        },
        'filters_applied': len(filter_dax_parts),
        'filter_summary': {
            'report_filters': len(
                filter_context.report_filters
            ),
            'page_filters': len(
                filter_context.page_filters
            ),
            'visual_filters': len(
                filter_context.visual_filters
            ),
            'slicer_filters': len(
                filter_context.slicer_filters
            )
        },
        'filter_dax': filter_dax_parts
    }

    return filter_context_info, filter_dax_parts


def _execute_measure_with_context(
    measure_name: str,
    filter_dax_parts: List[str],
    qe: Any
) -> Optional[Dict[str, Any]]:
    """Execute a measure with the given filter context.

    Returns execution result dict, or None if not executed.
    """
    measure_ref = f'[{measure_name.strip("[]")}]'
    filter_clause = ', '.join(filter_dax_parts) if filter_dax_parts else ''

    if filter_clause:
        query = (
            f'EVALUATE ROW("Value", '
            f'CALCULATE({measure_ref}, {filter_clause}))'
        )
    else:
        query = f'EVALUATE ROW("Value", {measure_ref})'

    try:
        exec_result = qe.validate_and_execute_dax(
            query, top_n=10
        )
        if (
            exec_result.get('success')
            and exec_result.get('rows')
        ):
            row = exec_result['rows'][0]
            value = row.get('Value', row.get('[Value]'))
            return {
                'success': True,
                'value': value,
                'execution_time_ms': exec_result.get(
                    'execution_time_ms'
                ),
                'query': query
            }
        else:
            return {
                'success': False,
                'error': exec_result.get('error'),
                'query': query
            }
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'query': query
        }


def _build_analyze_response(
    measure_name: str,
    table_name: Optional[str],
    expression: str,
    measure_details: Dict[str, Any],
    expression_source: Optional[str],
    analysis_result: Dict[str, Any],
    fix_suggestions: List[Dict],
    execution_result: Optional[Dict[str, Any]],
    filter_context_info: Optional[Dict[str, Any]],
    compact: bool
) -> Dict[str, Any]:
    """Build the compact or verbose response for analyze_measure."""
    expr_limit = 3 * VARIABLE_TRUNCATION_CHARS
    if compact:
        response: Dict[str, Any] = {
            'success': True,
            'measure': measure_name,
            'expression': (
                expression[:expr_limit] + '...'
                if len(expression) > expr_limit
                else expression
            ),
            'issues': analysis_result.get('total_issues', 0),
            'score': analysis_result.get('overall_score'),
            'fixes': [
                {'issue': s['issue'], 'severity': s['severity']}
                for s in fix_suggestions[:MAX_MEASURES_SHOWN]
            ]
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


def handle_analyze_measure(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Analyze a measure's DAX and suggest fixes/optimizations.

    Gets the DAX code, analyzes for anti-patterns, and optionally
    evaluates with filter context from a visual.
    """
    try:
        table_name = args.get('table_name')
        measure_name = args.get('measure_name')
        compact = args.get('compact', True)

        if not measure_name:
            return {'success': False, 'error': 'measure_name required'}

        if not connection_state.is_connected():
            return {
                'success': False,
                'error': 'Not connected to Power BI model. Use connect_to_powerbi first.'
            }

        qe = connection_state.query_executor
        if not qe:
            return ErrorHandler.handle_manager_unavailable('query_executor')

        # Step 1: Resolve measure expression
        resolved = _resolve_measure_expression(measure_name, table_name, qe)
        if not resolved['success']:
            return resolved

        expression = resolved['expression']
        measure_details = resolved['measure_details']
        expression_source = resolved['expression_source']

        # Step 2: Analyze the DAX expression
        analysis_result = _analyze_measure_dax(expression)

        # Step 3: Get filter context from visual if specified
        filter_context_info, filter_dax_parts = _get_visual_filter_context_for_measure(
            page_name=args.get('page_name'),
            visual_id=args.get('visual_id'),
            visual_name=args.get('visual_name'),
            include_slicers=args.get('include_slicers', True),
            qe=qe
        )

        # Step 4: Execute measure with filter context
        execution_result = None
        if args.get('execute_measure', True):
            execution_result = _execute_measure_with_context(
                measure_name, filter_dax_parts, qe
            )

        # Step 5: Generate fix suggestions from analysis issues
        fix_suggestions = []
        for issue in (analysis_result.get('issues') or [])[:5]:
            suggestion: Dict[str, Any] = {
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

        # Step 6: Build response
        return _build_analyze_response(
            measure_name, table_name, expression,
            measure_details, expression_source,
            analysis_result, fix_suggestions,
            execution_result, filter_context_info, compact
        )

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


def _extract_variables_full(dax: str) -> List[Dict[str, str]]:
    """Extract VAR definitions with full (untruncated) expressions.

    Unlike dax_utilities.extract_variables which truncates to 100 chars,
    this returns the complete expression text needed for query building.

    Returns:
        Ordered list of dicts with 'name' and 'expression' keys,
        preserving declaration order for dependency chaining.
    """
    import re
    var_pattern = re.compile(
        r"\bVAR\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*",
        re.IGNORECASE,
    )
    next_var = re.compile(r"\bVAR\s+", re.IGNORECASE)
    return_kw = re.compile(r"\bRETURN\b", re.IGNORECASE)

    from core.dax.dax_utilities import normalize_dax
    cleaned = normalize_dax(dax)

    variables: List[Dict[str, str]] = []
    for match in var_pattern.finditer(cleaned):
        var_name = match.group(1)
        start_pos = match.end()
        remaining = cleaned[start_pos:]

        nv = next_var.search(remaining)
        nr = return_kw.search(remaining)

        end_pos = len(remaining)
        if nv and nr:
            end_pos = min(nv.start(), nr.start())
        elif nv:
            end_pos = nv.start()
        elif nr:
            end_pos = nr.start()

        expr = remaining[:end_pos].strip()
        variables.append({
            'name': var_name,
            'expression': expr,
        })

    return variables


# DAX functions that typically return tables (not scalars)
_TABLE_RETURNING_FUNCTIONS = {
    'FILTER', 'ALL', 'VALUES', 'SUMMARIZE',
    'ADDCOLUMNS', 'SELECTCOLUMNS', 'TOPN',
    'DISTINCT', 'UNION', 'INTERSECT', 'EXCEPT',
    'DATATABLE', 'GENERATESERIES', 'GENERATE',
    'CROSSJOIN', 'NATURALINNERJOIN',
    'NATURALLEFTOUTERJOIN', 'CALCULATETABLE',
    'TREATAS', 'SUMMARIZECOLUMNS', 'GROUPBY',
    'ROW', 'DETAILROWS', 'SAMPLE',
    'SUBSTITUTEWITHINDEX', 'ROLLUP',
    'ROLLUPADDISSUBTOTAL', 'ROLLUPISSUBTOTAL',
    'ROLLUPGROUP',
}


def _classify_var_type(expression: str) -> str:
    """Determine if a variable expression returns a table or scalar.

    Checks whether the expression starts with a known
    table-returning DAX function.

    Returns:
        'table' or 'scalar'
    """
    stripped = expression.strip()
    # Get leading word (function name before the opening paren)
    import re
    m = re.match(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(", stripped)
    if m:
        func_name = m.group(1).upper()
        if func_name in _TABLE_RETURNING_FUNCTIONS:
            return 'table'
    return 'scalar'


def _build_var_chain_query(
    variables: List[Dict[str, str]],
    target_idx: int,
    var_type: str,
    max_rows: int = 100,
) -> str:
    """Build a DEFINE-based DAX query to evaluate a single variable.

    Includes all VAR definitions from index 0 up to and including
    target_idx so that dependencies are satisfied.

    Args:
        variables: Ordered list of {name, expression} dicts.
        target_idx: Index of the target variable.
        var_type: 'scalar' or 'table'.
        max_rows: Row limit for table variables.

    Returns:
        Complete DAX query string.
    """
    target = variables[target_idx]
    lines = ["DEFINE"]
    for i in range(target_idx + 1):
        v = variables[i]
        lines.append(f"  VAR {v['name']} = {v['expression']}")

    if var_type == 'table':
        lines.append(
            f"EVALUATE TOPN({max_rows}, {target['name']})"
        )
    else:
        lines.append(
            f'EVALUATE ROW("value", {target["name"]})'
        )

    return "\n".join(lines)


def _handle_debug_variable(
    args: Dict[str, Any],
) -> Dict[str, Any]:
    """Debug a single variable inside a measure's DAX expression.

    Evaluates the variable by building a DEFINE query that
    includes the full VAR chain up to the target variable.
    """
    try:
        measure_name = args.get('measure_name')
        table_name = args.get('table_name')
        variable_name = args.get('variable_name')
        max_rows = args.get('max_rows', 100)

        if not measure_name:
            return {
                'success': False,
                'error': 'measure_name is required',
            }
        if not variable_name:
            return {
                'success': False,
                'error': 'variable_name is required',
            }

        if not connection_state.is_connected():
            return {
                'success': False,
                'error': (
                    'Not connected to Power BI model. '
                    'Use connect_to_powerbi first.'
                ),
            }

        qe = connection_state.query_executor
        if not qe:
            return ErrorHandler.handle_manager_unavailable(
                'query_executor'
            )

        # Resolve measure expression
        resolved = _resolve_measure_expression(
            measure_name, table_name, qe
        )
        if not resolved['success']:
            return resolved

        expression = resolved['expression']

        # Parse variables
        variables = _extract_variables_full(expression)
        if not variables:
            return {
                'success': False,
                'error': (
                    f"No VAR definitions found in measure "
                    f"'{measure_name}'"
                ),
                'expression_preview': expression[:200],
            }

        # Find the target variable
        target_idx = None
        for i, v in enumerate(variables):
            if v['name'].lower() == variable_name.lower():
                target_idx = i
                break

        if target_idx is None:
            return {
                'success': False,
                'error': (
                    f"Variable '{variable_name}' not found "
                    f"in measure '{measure_name}'"
                ),
                'available_variables': [
                    v['name'] for v in variables
                ],
            }

        target = variables[target_idx]
        var_type = _classify_var_type(target['expression'])

        # Build and execute query
        query = _build_var_chain_query(
            variables, target_idx, var_type, max_rows
        )

        start = time.monotonic()
        exec_result = qe.validate_and_execute_dax(
            query, top_n=max_rows
        )
        elapsed_ms = round(
            (time.monotonic() - start) * 1000, 1
        )

        if not exec_result.get('success'):
            return {
                'success': False,
                'error': exec_result.get('error'),
                'variable': variable_name,
                'type': var_type,
                'query': query,
            }

        rows = exec_result.get('rows', [])

        result: Dict[str, Any] = {
            'success': True,
            'variable': variable_name,
            'type': var_type,
            'expression': (
                target['expression'][:300] + '...'
                if len(target['expression']) > 300
                else target['expression']
            ),
            'execution_time_ms': elapsed_ms,
            'query': query,
        }

        if var_type == 'scalar':
            value = None
            if rows:
                row = rows[0]
                value = row.get(
                    'value', row.get('[value]')
                )
            result['value'] = value
        else:
            result['rows'] = rows
            result['row_count'] = len(rows)

        return result

    except Exception as e:
        logger.error(
            f"Error in debug_variable: {e}", exc_info=True
        )
        return ErrorHandler.handle_unexpected_error(
            'debug_variable', e
        )


def _handle_step_variables(
    args: Dict[str, Any],
) -> Dict[str, Any]:
    """Step through all variables in a measure, evaluating each.

    Executes each VAR in order, building the full dependency
    chain up to that point, and reports the value and timing
    for each step.
    """
    try:
        measure_name = args.get('measure_name')
        table_name = args.get('table_name')
        page_name = args.get('page_name')
        max_rows = args.get('max_rows', 10)

        if not measure_name:
            return {
                'success': False,
                'error': 'measure_name is required',
            }

        if not connection_state.is_connected():
            return {
                'success': False,
                'error': (
                    'Not connected to Power BI model. '
                    'Use connect_to_powerbi first.'
                ),
            }

        qe = connection_state.query_executor
        if not qe:
            return ErrorHandler.handle_manager_unavailable(
                'query_executor'
            )

        # Resolve measure expression
        resolved = _resolve_measure_expression(
            measure_name, table_name, qe
        )
        if not resolved['success']:
            return resolved

        expression = resolved['expression']

        # Parse variables
        variables = _extract_variables_full(expression)
        if not variables:
            return {
                'success': False,
                'error': (
                    f"No VAR definitions found in measure "
                    f"'{measure_name}'"
                ),
                'expression_preview': expression[:200],
            }

        # Optionally get filter context from page
        filter_dax_parts: List[str] = []
        if page_name:
            _, parts = _get_visual_filter_context_for_measure(
                page_name=page_name,
                visual_id=args.get('visual_id'),
                visual_name=args.get('visual_name'),
                include_slicers=args.get(
                    'include_slicers', True
                ),
                qe=qe,
            )
            filter_dax_parts = parts

        # Step through each variable
        steps: List[Dict[str, Any]] = []
        total_start = time.monotonic()

        for idx, var in enumerate(variables):
            var_type = _classify_var_type(var['expression'])
            rows_limit = (
                max_rows if var_type == 'table' else 1
            )

            query = _build_var_chain_query(
                variables, idx, var_type, rows_limit
            )

            # Wrap in CALCULATETABLE if filter context
            if filter_dax_parts and var_type == 'table':
                filter_clause = ', '.join(filter_dax_parts)
                # Replace EVALUATE line with filtered version
                eval_line = query.split('\n')[-1]
                inner = eval_line.replace('EVALUATE ', '')
                query = (
                    '\n'.join(query.split('\n')[:-1])
                    + f'\nEVALUATE CALCULATETABLE('
                    f'{inner}, {filter_clause})'
                )
            elif filter_dax_parts and var_type == 'scalar':
                filter_clause = ', '.join(filter_dax_parts)
                eval_line = query.split('\n')[-1]
                # Extract the ROW expression
                inner_expr = var['name']
                query = (
                    '\n'.join(query.split('\n')[:-1])
                    + f'\nEVALUATE ROW("value", '
                    f'CALCULATE({inner_expr}, '
                    f'{filter_clause}))'
                )

            step_start = time.monotonic()
            exec_result = qe.validate_and_execute_dax(
                query, top_n=rows_limit
            )
            step_ms = round(
                (time.monotonic() - step_start) * 1000, 1
            )

            step: Dict[str, Any] = {
                'var_name': var['name'],
                'type': var_type,
                'expression': (
                    var['expression'][:200] + '...'
                    if len(var['expression']) > 200
                    else var['expression']
                ),
                'execution_time_ms': step_ms,
            }

            if exec_result.get('success'):
                rows = exec_result.get('rows', [])
                if var_type == 'scalar':
                    value = None
                    if rows:
                        row = rows[0]
                        value = row.get(
                            'value', row.get('[value]')
                        )
                    step['value'] = value
                else:
                    step['row_count'] = len(rows)
                    step['rows'] = rows[:5]
                    if len(rows) > 5:
                        step['truncated'] = True
            else:
                step['error'] = exec_result.get('error')

            steps.append(step)

        total_ms = round(
            (time.monotonic() - total_start) * 1000, 1
        )

        # Find slowest step
        slowest = max(
            steps,
            key=lambda s: s.get('execution_time_ms', 0),
        ) if steps else None

        result: Dict[str, Any] = {
            'success': True,
            'measure': measure_name,
            'variable_count': len(variables),
            'total_execution_time_ms': total_ms,
            'steps': steps,
        }

        if slowest:
            result['slowest_variable'] = {
                'name': slowest['var_name'],
                'ms': slowest['execution_time_ms'],
            }

        if filter_dax_parts:
            result['filter_context'] = {
                'source': page_name,
                'filters_applied': len(filter_dax_parts),
            }

        return result

    except Exception as e:
        logger.error(
            f"Error in step_variables: {e}", exc_info=True
        )
        return ErrorHandler.handle_unexpected_error(
            'step_variables', e
        )


def _handle_run_dax(args: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a raw DAX query, optionally with SE/FE trace analysis."""
    if not connection_state.is_connected():
        return {'success': False, 'error': 'Not connected to Power BI Desktop'}

    query = args.get('query', '').strip()
    if not query:
        return {'success': False, 'error': 'query parameter is required'}

    trace = args.get('trace', False)
    clear_cache = args.get('clear_cache', True)

    response: Dict[str, Any] = {'success': True, 'query': query}

    # SE/FE trace (cold cache first so timing is accurate)
    if trace:
        try:
            from core.infrastructure.query_trace import NativeTraceRunner
            conn_str = connection_state.connection_manager.connection_string
            if not conn_str:
                response['se_fe_trace'] = {'error': 'No connection string available'}
            elif not NativeTraceRunner.is_available():
                response['se_fe_trace'] = {
                    'error': (
                        'DaxExecutor.exe not found. '
                        'Build: cd core/infrastructure/dax_executor '
                        '&& dotnet build -c Release'
                    )
                }
            else:
                runner = NativeTraceRunner(conn_str)
                trace_result = runner.execute_with_trace(query, clear_cache)
                if '_error' in trace_result:
                    response['se_fe_trace'] = {'error': trace_result['_error']}
                else:
                    perf = {
                        'total_ms': trace_result.get('total_ms', 0),
                        'fe_ms': trace_result.get('fe_ms', 0),
                        'se_ms': trace_result.get('se_ms', 0),
                        'se_cpu_ms': trace_result.get('se_cpu_ms', 0),
                        'se_parallelism': trace_result.get('se_parallelism', 0.0),
                        'se_queries': trace_result.get('se_queries', 0),
                        'se_cache_hits': trace_result.get('se_cache_hits', 0),
                        'fe_pct': trace_result.get('fe_pct', 0.0),
                        'se_pct': trace_result.get('se_pct', 0.0),
                    }
                    response['se_fe_trace'] = {
                        'runner': 'native',
                        'performance': perf,
                        'se_events': trace_result.get('se_events', []),
                        'cache_cleared': trace_result.get('cache_cleared', False),
                        'summary': (
                            f"Total: {perf['total_ms']}ms | "
                            f"FE: {perf['fe_ms']}ms ({perf['fe_pct']}%) | "
                            f"SE: {perf['se_ms']}ms ({perf['se_pct']}%) | "
                            f"SE queries: {perf['se_queries']} | "
                            f"SE cache: {perf['se_cache_hits']}"
                        ),
                    }
        except Exception as te:
            logger.error(f"SE/FE trace failed: {te}", exc_info=True)
            response['se_fe_trace'] = {'error': str(te)}

    # Execute query and return rows
    try:
        qe = connection_state.query_executor
        if not qe:
            response['result'] = {'error': 'Query executor not available'}
        else:
            exec_result = qe.validate_and_execute_dax(query, top_n=0)
            response['result'] = exec_result
            if not exec_result.get('success'):
                response['success'] = False
    except Exception as e:
        logger.error(f"DAX execution failed: {e}", exc_info=True)
        response['result'] = {'error': str(e)}
        response['success'] = False

    return response


# =============================================================================
# OPTIMIZE OPERATION — SE/FE trace + DAX analysis + suggestions
# =============================================================================

def _analyze_se_callbacks(se_events: list) -> dict:
    """Detect CallbackDataID in SE events — the #1 performance anti-pattern."""
    callback_queries = []
    for evt in se_events:
        q = evt.get('query', '')
        if 'CallbackDataID' in q or 'PFDATAID' in q:
            callback_queries.append({
                'line': evt.get('line'),
                'duration_ms': evt.get('duration_ms'),
                'snippet': q[:300]
            })
    return {
        'detected': bool(callback_queries),
        'count': len(callback_queries),
        'queries': callback_queries
    }


def _diagnose_timing(perf: dict) -> dict:
    """Convert raw SE/FE metrics into a human-readable diagnosis."""
    fe_pct = perf.get('fe_pct', 0)
    se_queries = perf.get('se_queries', 0)
    se_ms = perf.get('se_ms', 0)
    se_par = perf.get('se_parallelism', 0)
    notes = []

    if fe_pct > 80:
        profile = 'FE-bound'
        notes.append(
            f'Formula Engine consumed {fe_pct}% of total time. '
            'The FE is single-threaded and uncached — this is the bottleneck. '
            'Focus on reducing iterators, context transitions, and pushing work to SE.'
        )
    elif fe_pct > 50:
        profile = 'FE-heavy'
        notes.append(
            f'Formula Engine consumed {fe_pct}% of time. '
            'DAX complexity is dominant. Consider simplifying filter arguments and reducing iterator scope.'
        )
    elif fe_pct < 20:
        profile = 'SE-bound'
        notes.append(
            f'Storage Engine consumed {100 - fe_pct}% of time. '
            'Check for large table scans, high-cardinality DISTINCTCOUNT, or missing aggregation tables.'
        )
    else:
        profile = 'balanced'
        notes.append(
            f'Good FE/SE balance ({fe_pct}% FE, {100 - fe_pct:.0f}% SE). '
            'Query performance is likely acceptable at this complexity level.'
        )

    if se_queries > 256:
        notes.append(
            f'CRITICAL: SE query count ({se_queries}) exceeds the datacache limit of 256. '
            'Cache provides no benefit. Redesign required to reduce SE fan-out.'
        )
    elif se_queries > 50:
        notes.append(
            f'High SE query count ({se_queries}). Investigate iterator structure — '
            'repeated sub-expressions should be captured in VAR to avoid re-evaluation.'
        )

    if se_ms > 20 and se_par < 2.0:
        notes.append(
            f'Low SE parallelism ({se_par}x). SE queries are not scaling across CPU cores. '
            'This can indicate small result sets or FE serialization forcing sequential SE calls.'
        )

    return {'profile': profile, 'notes': notes}


def _build_optimize_suggestions(
    bpa_result: dict,
    rewriter_result: dict,
    callback_info: dict,
    static_callbacks: dict,
    perf: dict,
) -> list:
    """
    Merge runtime CallbackDataID findings, static callback detections, BPA issues,
    and rewriter suggestions into a single prioritized optimization list.

    Priority order:
      0. Runtime CallbackDataID in SE trace (confirmed, always critical)
      1. Static callback detections from DAX analysis
      2. Timing-correlated high/critical BPA issues
      3. Non-timing-correlated high/critical BPA issues
      4. Timing-correlated medium BPA issues
      5. High-confidence rewriter suggestions
      6. Non-timing-correlated medium/low BPA issues
      7. Medium-confidence rewriter suggestions
    """
    suggestions = []
    fe_pct = perf.get('fe_pct', 0) if perf else 0

    # --- Source 1: Runtime CallbackDataID in SE trace ---
    if callback_info.get('detected'):
        for cb in callback_info.get('queries', []):
            suggestions.append({
                'priority': 0,
                'severity': 'critical',
                'category': 'callback_elimination',
                'title': 'CallbackDataID detected in Storage Engine query (runtime)',
                'description': (
                    'A CallbackDataID forces the Formula Engine (single-threaded, uncached) '
                    'to be invoked for every row during SE scan. '
                    'This can increase query time by 100x–260x compared to a pure SE query. '
                    f"Triggered in SE event line {cb.get('line')} ({cb.get('duration_ms')}ms). "
                    'Common causes: ROUND/TRUNC/INT/CEILING/FLOOR inside SUMX, '
                    'DIVIDE() anywhere, IF() inside iterators, text functions in row context.'
                ),
                'code_before': cb.get('snippet', ''),
                'code_after': (
                    '-- Pre-group by distinct values to minimize callback invocations:\n'
                    'SUMX(\n'
                    '    SUMMARIZE(FactTable, FactTable[ColumnWithLowCardinality]),\n'
                    '    CALCULATE(SUM(FactTable[Qty])) * callback_function(FactTable[ColumnWithLowCardinality])\n'
                    ')'
                ),
                'estimated_improvement': '10x–260x reduction in SE CPU time',
                'confidence': 'high',
                'timing_correlated': True
            })

    # --- Source 2: Static callback detections from CallbackDetector ---
    for cb_det in (static_callbacks.get('callback_detections') or []):
        sev = cb_det.get('severity', 'high')
        suggestions.append({
            'priority': 1,
            'severity': sev,
            'category': 'callback_elimination',
            'title': f"Callback risk [{cb_det.get('rule_id')}]: {cb_det.get('description', '')[:80]}",
            'description': cb_det.get('description', ''),
            'code_before': cb_det.get('match_text', ''),
            'code_after': cb_det.get('fix_suggestion', ''),
            'estimated_improvement': 'Eliminates per-row FE invocation from SE scan',
            'confidence': 'high',
            'timing_correlated': fe_pct > 50
        })

    # --- FE-bound timing context — which BPA categories to boost ---
    fe_correlated_categories = set()
    if fe_pct > 50:
        fe_correlated_categories = {'performance', 'anti_pattern'}

    # --- Source 3: BPA issues ---
    severity_rank = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3, 'info': 4}

    for issue in (bpa_result.get('issues') or []):
        sev = issue.get('severity', 'low')
        cat = issue.get('category', '')
        is_timing_correlated = (
            cat in fe_correlated_categories
            or sev in ('critical', 'high')
        )

        sev_rank = severity_rank.get(sev, 3)
        priority_base = sev_rank * 10
        if is_timing_correlated:
            priority_base -= 3

        suggestions.append({
            'priority': 10 + priority_base,
            'severity': sev,
            'category': cat,
            'title': issue.get('title', ''),
            'description': issue.get('description', ''),
            'code_before': issue.get('code_example_before'),
            'code_after': issue.get('code_example_after'),
            'estimated_improvement': issue.get('estimated_improvement'),
            'confidence': 'high',
            'timing_correlated': is_timing_correlated
        })

    # --- Source 4: Code rewriter transformations ---
    confidence_rank = {'high': 0, 'medium': 1, 'low': 2}
    for t in (rewriter_result.get('transformations') or []):
        conf = t.get('confidence', 'low')
        if conf == 'low':
            continue
        suggestions.append({
            'priority': 50 + confidence_rank.get(conf, 2),
            'severity': 'medium' if conf == 'high' else 'low',
            'category': 'code_rewrite',
            'title': f"Code rewrite: {t.get('type', 'optimization')}",
            'description': t.get('explanation', ''),
            'code_before': t.get('original', ''),
            'code_after': t.get('transformed', ''),
            'estimated_improvement': t.get('estimated_improvement'),
            'confidence': conf,
            'timing_correlated': False
        })

    suggestions.sort(key=lambda x: x['priority'])
    for s in suggestions:
        s.pop('priority', None)
    return suggestions


def _build_next_steps(
    optimizations: list,
    perf: dict,
    callback_info: dict,
    static_callbacks: dict,
) -> list:
    """Generate 2–4 actionable next steps based on findings."""
    steps = []
    fe_pct = perf.get('fe_pct', 0) if perf else 0
    se_queries = perf.get('se_queries', 0) if perf else 0
    has_rewrites = any(o.get('category') == 'code_rewrite' for o in optimizations)
    has_static_callbacks = bool(static_callbacks.get('summary', {}).get('total', 0))

    if callback_info.get('detected'):
        steps.append(
            'PRIORITY: Eliminate CallbackDataID — open DAX Studio Server Timings, '
            'locate the SE query containing CallbackDataID, identify the triggering '
            'function (ROUND/IF/DIVIDE inside iterator), and restructure using SUMMARIZE '
            'to pre-group by distinct values.'
        )
    elif has_static_callbacks:
        steps.append(
            'Callback risk detected in DAX expression. '
            'Use operation=visual with trace=true on a visual using this measure '
            'to confirm whether CallbackDataID appears in SE events at runtime.'
        )

    if fe_pct > 60:
        steps.append(
            'FE-bound query: focus on pushing filter predicates to SE. '
            'Replace FILTER(table, condition) with Boolean expression CALCULATE arguments. '
            'Use KEEPFILTERS instead of FILTER(VALUES(...), ...).'
        )

    if se_queries > 50:
        steps.append(
            f'High SE query count ({se_queries}): introduce VAR to capture repeated '
            'sub-expressions (e.g., prior-year CALCULATE blocks used in both numerator '
            'and denominator of DIVIDE).'
        )

    if has_rewrites:
        steps.append(
            'A recommended_rewrite is available. Test it using '
            'operation=compare with original_measure and optimized_expression '
            'to benchmark the improvement.'
        )

    if not steps:
        steps.append(
            'No critical issues detected. This measure has good SE/FE balance. '
            'Monitor performance if data volume increases significantly.'
        )

    return steps


def handle_optimize_measure(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    SE/FE trace + DAX analysis + optimization suggestions for a single measure.

    Accepts a measure name, resolves its expression, runs a cold-cache
    SE/FE trace, detects anti-patterns (both runtime and static), and
    returns prioritized optimization suggestions with before/after code examples.
    """
    try:
        measure_name = (args.get('measure_name') or '').strip()
        table_name = args.get('table_name')
        clear_cache = args.get('clear_cache', True)
        compact = args.get('compact', True)

        if not measure_name:
            return {
                'success': False,
                'error': 'measure_name is required for optimize operation',
                'hint': 'Example: {"operation": "optimize", "measure_name": "Net Asset Value"}'
            }

        if not connection_state.is_connected():
            return {
                'success': False,
                'error': 'Not connected to Power BI model. Use connect_to_powerbi first.'
            }

        qe = connection_state.query_executor
        if not qe:
            return ErrorHandler.handle_manager_unavailable('query_executor')

        # ── Step 1: Resolve measure expression ───────────────────────────────
        resolved = _resolve_measure_expression(measure_name, table_name, qe)
        if not resolved.get('success'):
            return resolved

        expression = resolved['expression']
        measure_details = resolved['measure_details']
        resolved_table = measure_details.get('table_name') or table_name or 'm Measure'
        expression_source = resolved.get('expression_source', 'unknown')

        # ── Step 2: SE/FE trace ───────────────────────────────────────────────
        perf: dict = {}
        se_events: list = []
        trace_error: Optional[str] = None
        trace_available = False

        try:
            from core.infrastructure.query_trace import NativeTraceRunner
            conn_str = connection_state.connection_manager.connection_string

            if not conn_str:
                trace_error = 'No connection string available'
            elif not NativeTraceRunner.is_available():
                trace_error = 'DaxExecutor.exe not found — DAX analysis will proceed without timing data'
            else:
                clean_measure = measure_name.strip('[]')
                trace_query = f"EVALUATE ROW(\"Value\", '{resolved_table}'[{clean_measure}])"

                runner = NativeTraceRunner(conn_str)
                tr = runner.execute_with_trace(trace_query, clear_cache=clear_cache)

                if '_error' in tr:
                    trace_error = tr['_error']
                else:
                    perf = {
                        'total_ms': tr.get('total_ms', 0),
                        'fe_ms': tr.get('fe_ms', 0),
                        'se_ms': tr.get('se_ms', 0),
                        'se_cpu_ms': tr.get('se_cpu_ms', 0),
                        'se_parallelism': tr.get('se_parallelism', 0.0),
                        'se_queries': tr.get('se_queries', 0),
                        'se_cache_hits': tr.get('se_cache_hits', 0),
                        'fe_pct': tr.get('fe_pct', 0.0),
                        'se_pct': tr.get('se_pct', 0.0),
                        'cache_cleared': tr.get('cache_cleared', False),
                    }
                    se_events = tr.get('se_events', [])
                    trace_available = True

        except Exception as te:
            logger.warning(f'SE/FE trace failed for optimize: {te}')
            trace_error = str(te)

        # ── Step 3: Runtime SE callback detection ─────────────────────────────
        callback_info = _analyze_se_callbacks(se_events)

        # ── Step 4: Static callback detection (DAX expression analysis) ───────
        try:
            from core.dax.callback_detector import CallbackDetector
            static_callbacks = CallbackDetector().detect_dict(expression)
        except Exception as ce:
            logger.warning(f'Static callback detection failed: {ce}')
            static_callbacks = {'callback_detections': [], 'summary': {'total': 0}}

        # ── Step 5: Timing diagnosis ──────────────────────────────────────────
        timing_diagnosis = _diagnose_timing(perf) if trace_available else None

        # ── Step 6: DAX best practices analysis ──────────────────────────────
        from core.dax.dax_best_practices import DaxBestPracticesAnalyzer
        bpa_result = DaxBestPracticesAnalyzer().analyze(expression)

        # ── Step 7: Code rewriter ─────────────────────────────────────────────
        from core.dax.code_rewriter import DaxCodeRewriter
        rewriter_result = DaxCodeRewriter().rewrite_dax(expression)

        # ── Step 8: Synthesize suggestions ───────────────────────────────────
        optimizations = _build_optimize_suggestions(
            bpa_result, rewriter_result, callback_info, static_callbacks, perf
        )

        # ── Step 9: Next steps ────────────────────────────────────────────────
        next_steps = _build_next_steps(optimizations, perf, callback_info, static_callbacks)

        # ── Step 10: Build response ───────────────────────────────────────────
        response: Dict[str, Any] = {
            'success': True,
            'measure': {
                'name': measure_name,
                'table': resolved_table,
                'expression': expression,
                'source': expression_source,
            },
            'dax_analysis': {
                'score': bpa_result.get('overall_score'),
                'complexity': bpa_result.get('complexity_level'),
                'total_issues': bpa_result.get('total_issues', 0),
                'critical': bpa_result.get('critical_issues', 0),
                'high': bpa_result.get('high_issues', 0),
                'medium': bpa_result.get('medium_issues', 0),
                'low': sum(1 for i in bpa_result.get('issues', [])
                           if i.get('severity') in ('low', 'info')),
            },
            'callback_analysis': {
                'runtime_detected': callback_info.get('detected', False),
                'runtime_count': callback_info.get('count', 0),
                'static_total': static_callbacks.get('summary', {}).get('total', 0),
                'static_critical': static_callbacks.get('summary', {}).get('critical', 0),
            },
            'optimizations': optimizations,
            'next_steps': next_steps,
        }

        if trace_available:
            response['timing'] = perf
            response['timing_diagnosis'] = timing_diagnosis
            if not compact:
                response['se_events'] = se_events
        elif trace_error:
            response['trace_unavailable'] = trace_error

        if rewriter_result.get('has_changes'):
            response['recommended_rewrite'] = rewriter_result.get('rewritten_code')

        return _compact_response(response, compact)

    except Exception as e:
        logger.error(f'Error in handle_optimize_measure: {e}', exc_info=True)
        return ErrorHandler.handle_unexpected_error('optimize_measure', e)


def handle_debug_operations(args: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatch debug operations."""
    operation = args.get('operation', 'visual')

    dispatch = {
        'visual': handle_debug_visual,
        'compare': handle_compare_measures,
        'drill': handle_drill_to_detail,
        'analyze': handle_analyze_measure,
        'debug_variable': _handle_debug_variable,
        'step_variables': _handle_step_variables,
        'run_dax': _handle_run_dax,
        'optimize': handle_optimize_measure,
    }

    handler = dispatch.get(operation)
    if handler:
        return handler(args)

    return {
        'success': False,
        'error': (
            f'Unknown operation: {operation}. '
            f'Valid: {", ".join(dispatch.keys())}'
        ),
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
            description="Visual debugger (visual), compare measures (compare), drill to detail (drill), analyze measure DAX (analyze), debug_variable (evaluate single VAR), step_variables (step through all VARs), run_dax (execute raw DEFINE…EVALUATE query), optimize (measure_name → cold-cache SE/FE trace + static CallbackDataID detection + DAX anti-pattern analysis + prioritized optimization suggestions with before/after code). Use trace=true on visual to get SE/FE timing analysis with the visual's real filter context; supply measures[] to override which measures are tested against that context.",
            handler=handle_debug_operations,
            input_schema={
                "type": "object",
                "properties": {
                    "operation": {"type": "string", "enum": ["visual", "compare", "drill", "analyze", "debug_variable", "step_variables", "run_dax", "optimize"], "default": "visual"},
                    "query": {"type": "string", "description": "Raw DAX query (DEFINE…EVALUATE) to execute (run_dax)"},
                    "page_name": {"type": "string"},
                    "visual_id": {"type": "string"},
                    "visual_name": {"type": "string"},
                    "measure_name": {"type": "string"},
                    "measures": {"type": "array", "items": {"type": "string"}, "description": "Explicit measure names to use (visual) — overrides auto-discovery. Use with trace=true to get SE/FE analysis for specific measures with the visual's real filter context."},
                    "table_name": {"type": "string", "description": "Table (analyze)"},
                    "include_slicers": {"type": "boolean"},
                    "execute_query": {"type": "boolean", "description": "Execute query and return rows (visual)"},
                    "execute_measure": {"type": "boolean", "description": "Execute measure (analyze)"},
                    "trace": {"type": "boolean", "default": False, "description": "Run SE/FE trace analysis on the visual query (visual) or raw query (run_dax). Cold cache by default; combine with execute_query=true to also get row results."},
                    "clear_cache": {"type": "boolean", "default": True, "description": "Clear VertiPaq cache before trace run for cold-cache timings (visual/run_dax, requires trace=true)"},
                    "filters": {"type": "array", "items": {"type": "string"}, "description": "Manual DAX filters"},
                    "skip_auto_filters": {"type": "boolean"},
                    "compact": {"type": "boolean"},
                    "original_measure": {"type": "string", "description": "Original measure (compare)"},
                    "optimized_expression": {"type": "string", "description": "Optimized DAX (compare)"},
                    "fact_table": {"type": "string", "description": "Fact table (drill)"},
                    "limit": {"type": "integer", "description": "Max rows (drill, default: 100)"},
                    "variable_name": {"type": "string", "description": "Variable name (debug_variable)"},
                    "max_rows": {"type": "integer", "default": 100, "description": "Max rows (debug_variable/step_variables)"}
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
                    "pbip_path": {"type": "string", "description": "PBIP folder path"},
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
