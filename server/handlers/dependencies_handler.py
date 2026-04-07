"""
INTERNAL HELPER — Not a registered MCP tool.
Provides helper functions consumed by active handlers.

Handles measure dependency analysis; consumed by dax_context_handler.py (05_DAX_Intelligence).
"""
from typing import Dict, Any, List, Tuple
import logging
import threading
from core.infrastructure.connection_state import connection_state
from core.validation.error_handler import ErrorHandler
from core.utilities.diagram_html_generator import generate_dependency_html
from core.utilities.dependency_cache import DependencyCache, compute_all_dependencies
from core.dax.dax_reference_parser import normalize_dax_name

logger = logging.getLogger(__name__)

# Global cache instance for sidebar data (protected by lock)
_sidebar_cache = {
    'all_measures': [],
    'all_columns': [],
    'all_dependencies': {}
}
_sidebar_cache_lock = threading.Lock()


def _load_sidebar_data(force_refresh: bool = True) -> dict:
    """
    Load sidebar data by computing ALL dependencies fresh.
    Returns dict with all_measures, all_columns, all_dependencies.
    All dependencies are pre-computed so the HTML can switch items instantly.

    Note: force_refresh defaults to True to ensure fresh data with correct limits.
    """
    global _sidebar_cache

    with _sidebar_cache_lock:
        # Check if we already have COMPLETE data in memory (including dependencies)
        # Only use memory cache if not forcing refresh
        if not force_refresh and _sidebar_cache.get('all_measures') and _sidebar_cache.get('all_dependencies'):
            logger.debug("Using in-memory sidebar cache with dependencies")
            return dict(_sidebar_cache)

    # Always delete old cache file and recompute to ensure we have all data
    # This fixes issues where old cache had limited data (100 row default)
    cache = DependencyCache()
    cache.clear_cache()  # Delete old cache file
    logger.info("Cleared old cache - will recompute all dependencies")

    # If no cache, compute ALL dependencies for ALL items
    # This enables instant switching in the HTML without re-running analysis
    query_executor = connection_state.query_executor
    dependency_analyzer = connection_state.dependency_analyzer

    if not query_executor or not dependency_analyzer:
        logger.warning("Query executor or dependency analyzer not available for sidebar data")
        with _sidebar_cache_lock:
            return dict(_sidebar_cache)

    logger.info("Computing all dependencies for sidebar (this may take a moment)...")

    # Use the compute_all_dependencies function from dependency_cache
    result = compute_all_dependencies(
        query_executor=query_executor,
        dependency_analyzer=dependency_analyzer,
        model_name="default",
        save_to_cache=True  # Save to file for faster loads next time
    )

    with _sidebar_cache_lock:
        _sidebar_cache = {
            'all_measures': result.get('all_measures', []),
            'all_columns': result.get('all_columns', []),
            'all_dependencies': result.get('all_dependencies', {})
        }

        logger.info(f"Computed sidebar data: {len(_sidebar_cache['all_measures'])} measures, "
                   f"{len(_sidebar_cache['all_columns'])} columns, {len(_sidebar_cache['all_dependencies'])} dependencies")
        return dict(_sidebar_cache)


def _format_dependency_analysis_output(
    table: str,
    measure: str,
    deps_result: Dict[str, Any],
    diagram_result: Dict[str, Any] = None
) -> str:
    """
    Format dependency analysis into a professional, readable output.

    Returns a formatted string with clear sections for:
    - Header with measure identification
    - Summary statistics
    - Dependencies breakdown by category
    - Mermaid diagram (if available)
    """
    lines = []

    # ═══════════════════════════════════════════════════════════════════════════
    # HEADER
    # ═══════════════════════════════════════════════════════════════════════════
    lines.append("═" * 80)
    lines.append("  MEASURE DEPENDENCY ANALYSIS")
    lines.append("═" * 80)
    lines.append("")
    lines.append(f"  Measure: {table}[{measure}]")
    lines.append("")

    # ───────────────────────────────────────────────────────────────────────────
    # SUMMARY STATISTICS
    # ───────────────────────────────────────────────────────────────────────────
    ref_measures = deps_result.get('referenced_measures', [])
    ref_columns = deps_result.get('referenced_columns', [])
    ref_tables = deps_result.get('referenced_tables', [])
    used_by_measures = deps_result.get('used_by_measures', [])

    lines.append("─" * 80)
    lines.append("  SUMMARY")
    lines.append("─" * 80)
    lines.append("")
    lines.append(f"  ┌─────────────────────────────────────────────────────────────────┐")
    lines.append(f"  │  DEPENDS ON (upstream):                                         │")
    lines.append(f"  │    Measures:           {len(ref_measures):>4}                                      │")
    lines.append(f"  │    Columns:            {len(ref_columns):>4}                                      │")
    lines.append(f"  │    Tables:             {len(ref_tables):>4}                                      │")
    lines.append(f"  ├─────────────────────────────────────────────────────────────────┤")
    lines.append(f"  │  USED BY (downstream):                                          │")
    lines.append(f"  │    Measures:           {len(used_by_measures):>4}                                      │")
    lines.append(f"  └─────────────────────────────────────────────────────────────────┘")
    lines.append("")

    # ───────────────────────────────────────────────────────────────────────────
    # MEASURE EXPRESSION
    # ───────────────────────────────────────────────────────────────────────────
    expression = deps_result.get('expression', '')
    if expression:
        lines.append("─" * 80)
        lines.append("  DAX EXPRESSION")
        lines.append("─" * 80)
        lines.append("")
        # Format expression with indentation
        for expr_line in expression.split('\n'):
            lines.append(f"    {expr_line}")
        lines.append("")

    # ───────────────────────────────────────────────────────────────────────────
    # REFERENCED MEASURES
    # ───────────────────────────────────────────────────────────────────────────
    if ref_measures:
        lines.append("─" * 80)
        lines.append(f"  REFERENCED MEASURES ({len(ref_measures)})")
        lines.append("─" * 80)
        lines.append("")

        # Group by table
        measures_by_table: Dict[str, List[str]] = {}
        for tbl, msr in ref_measures:
            if tbl not in measures_by_table:
                measures_by_table[tbl] = []
            measures_by_table[tbl].append(msr)

        for tbl, measures in sorted(measures_by_table.items()):
            lines.append(f"    {tbl}")
            for msr in sorted(measures):
                lines.append(f"      ├── [{msr}]")
        lines.append("")

    # ───────────────────────────────────────────────────────────────────────────
    # REFERENCED COLUMNS
    # ───────────────────────────────────────────────────────────────────────────
    if ref_columns:
        lines.append("─" * 80)
        lines.append(f"  REFERENCED COLUMNS ({len(ref_columns)})")
        lines.append("─" * 80)
        lines.append("")

        # Group by table
        columns_by_table: Dict[str, List[str]] = {}
        for tbl, col in ref_columns:
            if tbl not in columns_by_table:
                columns_by_table[tbl] = []
            columns_by_table[tbl].append(col)

        for tbl, columns in sorted(columns_by_table.items()):
            lines.append(f"    {tbl}")
            for col in sorted(columns):
                lines.append(f"      ├── [{col}]")
        lines.append("")

    # ───────────────────────────────────────────────────────────────────────────
    # REFERENCED TABLES
    # ───────────────────────────────────────────────────────────────────────────
    if ref_tables:
        lines.append("─" * 80)
        lines.append(f"  REFERENCED TABLES ({len(ref_tables)})")
        lines.append("─" * 80)
        lines.append("")
        for tbl in sorted(ref_tables):
            lines.append(f"    • {tbl}")
        lines.append("")

    # ───────────────────────────────────────────────────────────────────────────
    # USED BY MEASURES (Reverse Dependencies)
    # ───────────────────────────────────────────────────────────────────────────
    if used_by_measures:
        lines.append("─" * 80)
        lines.append(f"  USED BY MEASURES ({len(used_by_measures)}) - What depends on this measure")
        lines.append("─" * 80)
        lines.append("")

        # Group by table
        used_by_by_table: Dict[str, List[str]] = {}
        for item in used_by_measures:
            tbl = item.get('table', '')
            msr = item.get('measure', '')
            if tbl not in used_by_by_table:
                used_by_by_table[tbl] = []
            used_by_by_table[tbl].append(msr)

        for tbl, measures in sorted(used_by_by_table.items()):
            lines.append(f"    {tbl}")
            for msr in sorted(measures):
                lines.append(f"      ├── [{msr}]")
        lines.append("")
    else:
        lines.append("─" * 80)
        lines.append("  USED BY MEASURES (0) - What depends on this measure")
        lines.append("─" * 80)
        lines.append("")
        lines.append("    (No other measures reference this measure)")
        lines.append("")

    # ───────────────────────────────────────────────────────────────────────────
    # DEPENDENCY TREE PREVIEW
    # ───────────────────────────────────────────────────────────────────────────
    dep_tree = deps_result.get('dependency_tree')
    if dep_tree:
        lines.append("─" * 80)
        lines.append("  DEPENDENCY TREE (depth: 3)")
        lines.append("─" * 80)
        lines.append("")
        _format_tree_node(dep_tree, lines, indent=4, is_last=True)
        lines.append("")

    # ═══════════════════════════════════════════════════════════════════════════
    # FOOTER
    # ═══════════════════════════════════════════════════════════════════════════
    lines.append("═" * 80)

    return "\n".join(lines)


def _format_tree_node(node: Dict[str, Any], lines: List[str], indent: int = 0, is_last: bool = True) -> None:
    """Recursively format a dependency tree node."""
    prefix = " " * indent
    connector = "└── " if is_last else "├── "

    tbl = node.get('table', '')
    msr = node.get('measure', '')

    # Add node
    node_str = f"{tbl}[{msr}]"
    if node.get('circular'):
        node_str += " (circular reference)"
    if node.get('max_depth_reached'):
        node_str += " (max depth)"
    if node.get('error'):
        node_str += f" (error: {node['error']})"

    lines.append(f"{prefix}{connector}{node_str}")

    # Process children
    children = node.get('dependencies', [])
    for i, child in enumerate(children):
        is_last_child = (i == len(children) - 1)
        child_indent = indent + 4
        _format_tree_node(child, lines, child_indent, is_last_child)


def _generate_mermaid_markdown(diagram_result: Dict[str, Any], table: str, measure: str) -> str:
    """
    Generate a complete Mermaid diagram in markdown format.
    This is returned as a SEPARATE response item for proper rendering.
    """
    if not diagram_result or not diagram_result.get('success'):
        return ""

    mermaid_code = diagram_result.get('mermaid', '')
    if not mermaid_code:
        return ""

    lines = []
    lines.append("")
    lines.append("═" * 80)
    lines.append("  DEPENDENCY DIAGRAM")
    lines.append("═" * 80)
    lines.append("")
    lines.append(f"  Measure: {table}[{measure}]")
    lines.append(f"  Direction: {diagram_result.get('direction', 'upstream')}")
    lines.append(f"  Depth: {diagram_result.get('depth', 3)}")
    lines.append(f"  Nodes: {diagram_result.get('node_count', 0)}")
    lines.append(f"  Edges: {diagram_result.get('edge_count', 0)}")
    lines.append("")
    lines.append("─" * 80)
    lines.append("")
    lines.append("```mermaid")
    lines.append(mermaid_code)
    lines.append("```")
    lines.append("")
    lines.append("─" * 80)
    lines.append("  Legend:")
    lines.append("    • Blue box = Target measure (center)")
    lines.append("    • Green boxes = Dependencies (upstream - what this measure uses)")
    lines.append("    • Orange boxes = Dependents (downstream - what uses this measure)")
    lines.append("    • Arrows show dependency flow (dependency → consumer)")
    lines.append("─" * 80)

    return "\n".join(lines)


def handle_analyze_measure_dependencies(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Analyze measure dependencies tree with professional formatted output.

    Returns a structured response with:
    - formatted_output: Professional text-based analysis summary
    - mermaid_diagram_output: Separate markdown block with Mermaid diagram
    - Raw data fields for programmatic access
    - used_by_measures: List of measures that USE this measure (reverse dependencies)
    """
    if not connection_state.is_connected():
        return ErrorHandler.handle_not_connected()

    dependency_analyzer = connection_state.dependency_analyzer
    if not dependency_analyzer:
        return ErrorHandler.handle_manager_unavailable('dependency_analyzer')

    table = args.get('table')
    measure = args.get('measure')
    include_diagram = args.get('include_diagram', True)  # Default to True

    if not table or not measure:
        return {
            'success': False,
            'error': 'table and measure parameters are required'
        }

    # Get the base dependency analysis (what this measure depends on)
    deps_result = dependency_analyzer.analyze_dependencies(table, measure, include_diagram=False)

    if not deps_result.get('success'):
        return deps_result

    # Enrich referenced_measures with proper table names when they come back empty
    # This happens when unqualified references like [MeasureName] are parsed
    referenced_measures = deps_result.get('referenced_measures', [])
    if referenced_measures:
        # Check if any have empty table names
        needs_lookup = any(not tbl for tbl, _ in referenced_measures)
        if needs_lookup:
            # Get all measures to build lookup
            query_executor = connection_state.query_executor
            if query_executor:
                measures_result = query_executor.execute_info_query("MEASURES")
                if measures_result.get('success'):
                    measures_rows = measures_result.get('rows', [])
                    # Build lookup by normalized measure name (using same normalization as DAX parser)
                    measure_name_to_info = {}
                    for m in measures_rows:
                        m_table = m.get('Table', '') or ''
                        m_name = m.get('Name', '') or ''
                        m_folder = m.get('DisplayFolder', '') or ''
                        if m_name:
                            name_key = normalize_dax_name(m_name)
                            # Only store if not already present (first match wins)
                            if name_key not in measure_name_to_info:
                                measure_name_to_info[name_key] = {'table': m_table, 'display_folder': m_folder}

                    logger.debug(f"Built measure lookup with {len(measure_name_to_info)} entries")

                    # Enrich the referenced measures
                    enriched_measures = []
                    for tbl, msr in referenced_measures:
                        if not tbl and msr:
                            # Look up by measure name
                            name_key = normalize_dax_name(msr)
                            if name_key in measure_name_to_info:
                                info = measure_name_to_info[name_key]
                                enriched_measures.append((info['table'] or 'Unknown', msr))
                                logger.debug(f"Enriched measure [{msr}] -> {info['table']}[{msr}]")
                            else:
                                logger.warning(f"Could not find table for measure [{msr}] (normalized: {name_key})")
                                enriched_measures.append(('Unknown', msr))
                        else:
                            enriched_measures.append((tbl, msr))

                    # Update deps_result with enriched measures
                    deps_result['referenced_measures'] = enriched_measures

    # Get "used by" analysis (what measures depend on THIS measure)
    usage_result = dependency_analyzer.find_measure_usage(table, measure)
    used_by_measures = []
    if usage_result.get('success'):
        used_by_measures = usage_result.get('used_by', [])

    # Add used_by to deps_result for formatting
    deps_result['used_by_measures'] = used_by_measures

    # Get the Mermaid diagram separately if requested - use BIDIRECTIONAL to show both directions
    diagram_result = None
    if include_diagram:
        diagram_result = dependency_analyzer.generate_impact_mermaid(
            table, measure
        )

    # Generate formatted outputs
    formatted_analysis = _format_dependency_analysis_output(table, measure, deps_result, diagram_result)
    mermaid_output = _generate_mermaid_markdown(diagram_result, table, measure) if include_diagram else ""

    # Build the response with clear separation
    response = {
        'success': True,
        'measure': {'table': table, 'name': measure},

        # PRIMARY OUTPUT - Text analysis (display this first)
        'formatted_output': formatted_analysis,

        # DIAGRAM OUTPUT - Separate markdown with Mermaid (display after analysis)
        'mermaid_diagram_output': mermaid_output,

        # Instruction for AI/client on how to display
        'display_instructions': 'Display formatted_output first, then mermaid_diagram_output as a separate code block.',

        # Raw data for programmatic access
        'expression': deps_result.get('expression', ''),
        'referenced_measures': deps_result.get('referenced_measures', []),
        'referenced_columns': deps_result.get('referenced_columns', []),
        'referenced_tables': deps_result.get('referenced_tables', []),
        'dependency_tree': deps_result.get('dependency_tree'),

        # USED BY - Reverse dependencies (what measures use this measure)
        'used_by_measures': used_by_measures,

        # Summary stats
        'summary': {
            'measure_count': len(deps_result.get('referenced_measures', [])),
            'column_count': len(deps_result.get('referenced_columns', [])),
            'table_count': len(deps_result.get('referenced_tables', [])),
            'total_dependencies': len(deps_result.get('referenced_measures', [])) + len(deps_result.get('referenced_columns', [])),
            'used_by_count': len(used_by_measures)
        }
    }

    # Include raw mermaid code for clients that want to render it themselves
    if diagram_result and diagram_result.get('success'):
        mermaid_code = diagram_result.get('mermaid', '')
        response['mermaid_raw'] = mermaid_code
        response['diagram_metadata'] = {
            'direction': 'bidirectional',
            'depth': diagram_result.get('depth', 3),
            'node_count': diagram_result.get('node_count', 0),
            'edge_count': diagram_result.get('edge_count', 0),
            'upstream_count': diagram_result.get('upstream_count', len(deps_result.get('referenced_measures', []))),
            'downstream_count': diagram_result.get('downstream_count', len(used_by_measures))
        }

        # Always generate interactive HTML diagram (works for any size)
        # This provides a consistent experience regardless of diagram complexity
        if mermaid_code:
            # Load sidebar data for the Model Browser
            sidebar_data = _load_sidebar_data()
            main_item_key = f"{table}[{measure}]"

            html_path = generate_dependency_html(
                mermaid_code=mermaid_code,
                measure_table=table,
                measure_name=measure,
                metadata=response.get('diagram_metadata', {}),
                auto_open=True,
                referenced_measures=deps_result.get('referenced_measures', []),
                referenced_columns=deps_result.get('referenced_columns', []),
                used_by_measures=used_by_measures,
                # Sidebar data for Model Browser
                all_measures=sidebar_data.get('all_measures', []),
                all_columns=sidebar_data.get('all_columns', []),
                all_dependencies=sidebar_data.get('all_dependencies', {}),
                main_item=main_item_key
            )
            if html_path:
                response['diagram_rendered'] = True
                response['html_diagram_path'] = html_path
                response['display_instructions'] = f'Interactive diagram opened in browser: {html_path}'
                # Remove text-based mermaid since HTML is better
                if 'mermaid_diagram_output' in response:
                    del response['mermaid_diagram_output']
                if 'mermaid_raw' in response:
                    del response['mermaid_raw']
                logger.info(f"Generated HTML diagram: {html_path}")
            else:
                logger.warning("Failed to generate HTML diagram")
                response['diagram_render_error'] = "Failed to generate HTML diagram"

    return response

def handle_get_measure_impact(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get measure usage impact"""
    if not connection_state.is_connected():
        return ErrorHandler.handle_not_connected()

    dependency_analyzer = connection_state.dependency_analyzer
    if not dependency_analyzer:
        return ErrorHandler.handle_manager_unavailable('dependency_analyzer')

    table = args.get('table')
    measure = args.get('measure')

    if not table or not measure:
        return {
            'success': False,
            'error': 'table and measure parameters are required'
        }

    return dependency_analyzer.get_measure_impact(table, measure)

def handle_dax_operations(args: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatch DAX operations: dependencies, impact, export"""
    operation = args.get('operation', 'dependencies')

    if operation == 'dependencies':
        return handle_analyze_measure_dependencies(args)
    elif operation == 'impact':
        return handle_get_measure_impact(args)
    elif operation == 'export':
        from server.handlers.column_usage_handler import handle_export_dax_measures
        return handle_export_dax_measures(args)
    else:
        return {
            'success': False,
            'error': f'Unknown operation: {operation}. Valid: dependencies, impact, export'
        }


