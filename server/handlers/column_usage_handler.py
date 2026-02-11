"""
Column Usage Handler

MCP handler for column-measure usage mapping.
Provides tools to answer:
- Which measures use columns from specific tables?
- What columns does a measure reference?
- What measures reference a specific column?
"""

import logging
import threading
from typing import Dict, Any, List, Optional
from server.registry import ToolDefinition
from core.infrastructure.connection_state import connection_state
from core.validation.error_handler import ErrorHandler
from core.analysis.column_usage_analyzer import ColumnUsageAnalyzer

logger = logging.getLogger(__name__)

# Singleton analyzer instance (created on first use) - thread-safe
_analyzer_instance: Optional[ColumnUsageAnalyzer] = None
_analyzer_lock = threading.Lock()


def _get_analyzer() -> Optional[ColumnUsageAnalyzer]:
    """Get or create the column usage analyzer instance (thread-safe)"""
    global _analyzer_instance

    if not connection_state.is_connected():
        return None

    query_executor = connection_state.query_executor
    if not query_executor:
        return None

    if _analyzer_instance is None:
        with _analyzer_lock:
            # Double-checked locking
            if _analyzer_instance is None:
                _analyzer_instance = ColumnUsageAnalyzer(query_executor)
                logger.info("Created ColumnUsageAnalyzer instance")

    return _analyzer_instance


def _format_measures_by_table_output(result: Dict[str, Any], include_dax: bool = True) -> str:
    """Format the measures-by-table result for display"""
    lines = []

    lines.append("=" * 80)
    lines.append("  COLUMN USAGE ANALYSIS - Measures Using Tables")
    lines.append("=" * 80)
    lines.append("")

    tables_requested = result.get('tables_requested', [])
    lines.append(f"  Tables analyzed: {', '.join(tables_requested)}")
    lines.append("")

    summary = result.get('summary', {})
    lines.append("-" * 80)
    lines.append("  SUMMARY")
    lines.append("-" * 80)
    lines.append(f"  Tables with usage: {summary.get('tables_found', 0)}")
    lines.append(f"  Columns with usage: {summary.get('columns_with_usage', 0)}")
    lines.append(f"  Unique measures: {summary.get('unique_measures', 0)}")
    lines.append("")

    results = result.get('results', {})

    for table_name, columns in sorted(results.items()):
        lines.append("-" * 80)
        lines.append(f"  TABLE: {table_name}")
        lines.append("-" * 80)
        lines.append("")

        for col_name, measures in sorted(columns.items()):
            lines.append(f"    [{col_name}] - {len(measures)} measure(s)")
            for m in measures[:10]:  # Limit to first 10
                folder = f" ({m.get('display_folder', '')})" if m.get('display_folder') else ""
                lines.append(f"      -> {m['table']}[{m['measure']}]{folder}")
                # Include DAX if available and requested
                if include_dax and m.get('dax'):
                    dax = m['dax'].replace('\n', '\n          ')  # Indent multiline DAX
                    lines.append(f"          DAX: {dax}")
            if len(measures) > 10:
                lines.append(f"      ... and {len(measures) - 10} more")
            lines.append("")

    lines.append("=" * 80)
    return "\n".join(lines)


def _format_measures_flat_output(result: Dict[str, Any], include_dax: bool = True) -> str:
    """Format the flat measures list for display"""
    lines = []

    lines.append("=" * 80)
    lines.append("  MEASURES USING TABLES")
    lines.append("=" * 80)
    lines.append("")

    tables_requested = result.get('tables_requested', [])
    lines.append(f"  Tables analyzed: {', '.join(tables_requested)}")
    lines.append("")

    measures = result.get('measures', [])
    summary = result.get('summary', {})

    lines.append(f"  Total unique measures: {summary.get('unique_measures', len(measures))}")
    lines.append("")

    lines.append("-" * 80)
    lines.append("  MEASURES")
    lines.append("-" * 80)
    lines.append("")

    # Group by display folder for better organization
    by_folder: Dict[str, List[Dict]] = {}
    for m in measures:
        folder = m.get('display_folder', '') or '(No folder)'
        if folder not in by_folder:
            by_folder[folder] = []
        by_folder[folder].append(m)

    for folder, folder_measures in sorted(by_folder.items()):
        lines.append(f"  {folder}")
        for m in sorted(folder_measures, key=lambda x: x['measure']):
            lines.append(f"    - {m['table']}[{m['measure']}]")
            # Include DAX if available and requested
            if include_dax and m.get('dax'):
                dax = m['dax'].replace('\n', '\n        ')  # Indent multiline DAX
                lines.append(f"        DAX: {dax}")
        lines.append("")

    lines.append("=" * 80)
    return "\n".join(lines)


def _format_measure_columns_output(result: Dict[str, Any], include_dax: bool = True) -> str:
    """Format measure-to-columns output"""
    lines = []

    measure_info = result.get('measure', {})
    columns = result.get('columns', [])
    dax_expression = result.get('dax', '')

    lines.append("=" * 80)
    lines.append(f"  COLUMNS USED BY MEASURE: {measure_info.get('table', '')}[{measure_info.get('measure', '')}]")
    lines.append("=" * 80)
    lines.append("")
    lines.append(f"  Total columns: {len(columns)}")
    lines.append("")

    # Include DAX expression if available
    if include_dax and dax_expression:
        lines.append("-" * 80)
        lines.append("  DAX EXPRESSION")
        lines.append("-" * 80)
        lines.append("")
        for dax_line in dax_expression.split('\n'):
            lines.append(f"    {dax_line}")
        lines.append("")

    # Group by table
    by_table: Dict[str, List[str]] = {}
    for col in columns:
        table = col.get('table', '')
        column = col.get('column', '')
        if table not in by_table:
            by_table[table] = []
        by_table[table].append(column)

    lines.append("-" * 80)
    lines.append("  REFERENCED COLUMNS")
    lines.append("-" * 80)
    for table, cols in sorted(by_table.items()):
        lines.append(f"  {table}")
        for col in sorted(cols):
            lines.append(f"    - [{col}]")
        lines.append("")

    lines.append("=" * 80)
    return "\n".join(lines)


def _format_unused_columns_output(result: Dict[str, Any]) -> str:
    """Format unused columns output - COMPLETE analysis, no other tools needed"""
    lines = []

    lines.append("=" * 80)
    lines.append("  COLUMN USAGE ANALYSIS - COMPLETE REPORT")
    lines.append("=" * 80)
    lines.append("")

    tables_filter = result.get('tables_filter')
    if tables_filter:
        lines.append(f"  Tables analyzed: {', '.join(tables_filter)}")
    else:
        lines.append("  Tables analyzed: ALL TABLES")
    lines.append("")

    # Summary with complete breakdown
    summary = result.get('summary', {})
    total = summary.get('total_columns_analyzed', 0)
    used_measures = summary.get('used_by_measures', 0)
    used_rels = summary.get('used_by_relationships_only', 0)
    unused = summary.get('unused', 0)

    lines.append("-" * 80)
    lines.append("  SUMMARY")
    lines.append("-" * 80)
    lines.append(f"  Total columns analyzed: {total}")
    lines.append(f"  [+] Used by measures: {used_measures}")
    lines.append(f"  [+] Used by relationships only: {used_rels}")
    lines.append(f"  [-] UNUSED (not in measures or relationships): {unused}")
    lines.append("")

    # Show unused columns (the main result)
    unused_by_table = result.get('unused_by_table', {})
    if unused_by_table:
        lines.append("-" * 80)
        lines.append("  [-] UNUSED COLUMNS (can potentially be removed)")
        lines.append("-" * 80)
        lines.append("")

        for table_name, columns in sorted(unused_by_table.items()):
            lines.append(f"  {table_name} ({len(columns)} unused)")
            for col in sorted(columns):
                lines.append(f"    - [{col}]")
            lines.append("")
    else:
        lines.append("-" * 80)
        lines.append("  [+] No unused columns found - all columns are in use!")
        lines.append("-" * 80)
        lines.append("")

    # Show relationship-only columns
    rel_by_table = result.get('used_by_relationships_only_by_table', {})
    if rel_by_table:
        lines.append("-" * 80)
        lines.append("  [+] COLUMNS USED BY RELATIONSHIPS ONLY")
        lines.append("      (Not in measures, but required for model relationships)")
        lines.append("-" * 80)
        lines.append("")

        for table_name, columns in sorted(rel_by_table.items()):
            lines.append(f"  {table_name} ({len(columns)} relationship keys)")
            for col in sorted(columns):
                lines.append(f"    - [{col}]")
            lines.append("")

    # Show columns used by measures (for completeness)
    used_by_table = result.get('used_by_measures_by_table', {})
    if used_by_table:
        lines.append("-" * 80)
        lines.append("  [+] COLUMNS USED BY MEASURES")
        lines.append("-" * 80)
        lines.append("")

        for table_name, columns in sorted(used_by_table.items()):
            lines.append(f"  {table_name} ({len(columns)} used)")
            for col in sorted(columns):
                lines.append(f"    - [{col}]")
            lines.append("")

    lines.append("=" * 80)
    return "\n".join(lines)


def _format_full_mapping_output(result: Dict[str, Any]) -> str:
    """Format full mapping as a summary - avoid dumping raw JSON"""
    lines = []

    lines.append("=" * 80)
    lines.append("  COLUMN-MEASURE MAPPING SUMMARY")
    lines.append("=" * 80)
    lines.append("")

    stats = result.get('statistics', {})
    lines.append("-" * 80)
    lines.append("  STATISTICS")
    lines.append("-" * 80)
    lines.append(f"  Total columns: {stats.get('total_columns', 0)}")
    lines.append(f"  Total measures: {stats.get('total_measures', 0)}")
    lines.append(f"  Columns with usage: {stats.get('columns_with_usage', 0)}")
    lines.append(f"  Columns without usage: {stats.get('columns_without_usage', 0)}")
    lines.append("")

    # Show top columns by measure count
    col_to_measures = result.get('column_to_measures', {})
    if col_to_measures:
        # Sort by number of measures using each column
        sorted_cols = sorted(
            [(k, len(v)) for k, v in col_to_measures.items() if v],
            key=lambda x: x[1],
            reverse=True
        )[:20]  # Top 20

        lines.append("-" * 80)
        lines.append("  TOP 20 MOST-USED COLUMNS (by measure count)")
        lines.append("-" * 80)
        lines.append("")

        for col_key, count in sorted_cols:
            lines.append(f"  {col_key}: {count} measures")
        lines.append("")

    # Show measures with most column dependencies
    measure_to_cols = result.get('measure_to_columns', {})
    if measure_to_cols:
        sorted_measures = sorted(
            [(k, len(v)) for k, v in measure_to_cols.items() if v],
            key=lambda x: x[1],
            reverse=True
        )[:20]  # Top 20

        lines.append("-" * 80)
        lines.append("  TOP 20 MEASURES WITH MOST COLUMN DEPENDENCIES")
        lines.append("-" * 80)
        lines.append("")

        for msr_key, count in sorted_measures:
            lines.append(f"  {msr_key}: {count} columns")
        lines.append("")

    lines.append("-" * 80)
    lines.append("  TIP: Use 'get_unused_columns' for unused column analysis")
    lines.append("       Use 'export_to_csv' for complete data export to Excel")
    lines.append("-" * 80)

    lines.append("=" * 80)
    return "\n".join(lines)


def _format_column_measures_output(result: Dict[str, Any], include_dax: bool = True) -> str:
    """Format column-to-measures output"""
    lines = []

    column_info = result.get('column', {})
    measures = result.get('measures', [])

    lines.append("=" * 80)
    lines.append(f"  MEASURES USING COLUMN: {column_info.get('table', '')}[{column_info.get('column', '')}]")
    lines.append("=" * 80)
    lines.append("")
    lines.append(f"  Total measures: {len(measures)}")
    lines.append("")

    lines.append("-" * 80)
    for m in measures:
        folder = f" ({m.get('display_folder', '')})" if m.get('display_folder') else ""
        lines.append(f"  - {m['table']}[{m['measure']}]{folder}")
        # Include DAX if available and requested
        if include_dax and m.get('dax'):
            dax = m['dax'].replace('\n', '\n      ')  # Indent multiline DAX
            lines.append(f"      DAX: {dax}")
            lines.append("")

    lines.append("=" * 80)
    return "\n".join(lines)


def handle_column_usage_mapping(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle column usage mapping operations.

    Operations:
    - get_measures_for_tables: Get all measures that use columns from specified tables
    - get_columns_for_measure: Get all columns used by a specific measure
    - get_measures_for_column: Get all measures that use a specific column
    - get_full_mapping: Get complete bidirectional mapping
    - get_unused_columns: Get columns not referenced by any measure
    """
    if not connection_state.is_connected():
        return ErrorHandler.handle_not_connected()

    analyzer = _get_analyzer()
    if not analyzer:
        return ErrorHandler.handle_manager_unavailable('column_usage_analyzer')

    operation = args.get('operation', 'get_measures_for_tables')
    force_refresh = args.get('force_refresh', False)
    include_dax = args.get('include_dax', False)  # Default to False for size optimization

    try:
        if operation == 'get_measures_for_tables':
            # Main use case: What measures use columns from these tables?
            tables = args.get('tables', [])
            if not tables:
                return {
                    'success': False,
                    'error': 'tables parameter is required (list of table names)'
                }

            group_by = args.get('group_by', 'table')
            result = analyzer.get_measures_using_tables(tables, force_refresh, group_by, include_dax)

            # Add formatted output
            if group_by == 'table':
                result['formatted_output'] = _format_measures_by_table_output(result, include_dax)
            elif group_by == 'flat':
                result['formatted_output'] = _format_measures_flat_output(result, include_dax)

            return result

        elif operation == 'get_columns_for_measure':
            # What columns does this measure use?
            table = args.get('table')
            measure = args.get('measure')

            if not table or not measure:
                return {
                    'success': False,
                    'error': 'table and measure parameters are required'
                }

            result = analyzer.get_columns_used_by_measure(table, measure, force_refresh, include_dax)
            result['formatted_output'] = _format_measure_columns_output(result, include_dax)
            return result

        elif operation == 'get_measures_for_column':
            # What measures use this column?
            table = args.get('table')
            column = args.get('column')

            if not table or not column:
                return {
                    'success': False,
                    'error': 'table and column parameters are required'
                }

            result = analyzer.get_measures_using_column(table, column, force_refresh, include_dax)
            result['formatted_output'] = _format_column_measures_output(result, include_dax)
            return result

        elif operation == 'get_full_mapping':
            # Get complete bidirectional mapping with all data
            return analyzer.get_full_mapping(force_refresh, include_dax)

        elif operation == 'get_unused_columns':
            # Get columns not used by any measure or relationship
            tables = args.get('tables')  # Optional filter
            result = analyzer.get_unused_columns(tables, force_refresh)
            result['formatted_output'] = _format_unused_columns_output(result)
            return result

        elif operation == 'export_to_csv':
            # Export to CSV files for Excel
            tables = args.get('tables')  # Optional filter
            output_path = args.get('output_path')
            return analyzer.export_to_csv(tables, output_path, include_dax, force_refresh)

        else:
            return {
                'success': False,
                'error': f'Unknown operation: {operation}',
                'valid_operations': [
                    'get_measures_for_tables',
                    'get_columns_for_measure',
                    'get_measures_for_column',
                    'get_full_mapping',
                    'get_unused_columns',
                    'export_to_csv'
                ]
            }

    except Exception as e:
        logger.error(f"Error in column usage mapping: {e}", exc_info=True)
        return ErrorHandler.handle_unexpected_error('column_usage_mapping', e)


def handle_export_dax_measures(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Export all DAX measures to CSV with table, name, display folder, and DAX expression.
    """
    import csv
    import os
    from datetime import datetime

    if not connection_state.is_connected():
        return ErrorHandler.handle_not_connected()

    query_executor = connection_state.query_executor
    if not query_executor:
        return ErrorHandler.handle_manager_unavailable('query_executor')

    try:
        # Get all measures
        measures_result = query_executor.execute_info_query("MEASURES")
        if not measures_result.get('success'):
            return {
                'success': False,
                'error': f"Failed to get measures: {measures_result.get('error')}"
            }

        all_measures = measures_result.get('rows', [])

        # Determine output directory
        output_path = args.get('output_path')
        if output_path is None:
            output_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'exports')

        os.makedirs(output_path, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_path = os.path.join(output_path, f"all_dax_measures_{timestamp}.csv")

        row_count = 0
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['Table', 'Measure_Name', 'Display_Folder', 'DAX_Expression'])

            for m in all_measures:
                m_table = m.get('Table', '') or m.get('[Table]', '')
                m_name = m.get('Name', '') or m.get('[Name]', '')
                m_expression = m.get('Expression', '') or m.get('[Expression]', '')
                m_folder = m.get('DisplayFolder', '') or m.get('[DisplayFolder]', '') or ''

                if m_table and m_name:
                    writer.writerow([m_table, m_name, m_folder, m_expression])
                    row_count += 1

        logger.info(f"Exported {row_count} DAX measures to CSV: {csv_path}")

        return {
            "success": True,
            "file_path": csv_path,
            "statistics": {
                "measures_exported": row_count
            },
            "message": f"Exported {row_count} DAX measures to:\n  {csv_path}"
        }

    except Exception as e:
        logger.error(f"Error exporting DAX measures: {e}", exc_info=True)
        return ErrorHandler.handle_unexpected_error('export_dax_measures', e)


def register_export_dax_measures_handler(registry):
    """Register the export DAX measures handler"""

    input_schema = {
        "type": "object",
        "description": "Export all DAX measures to a CSV file with table, name, display folder, and DAX expression.",
        "properties": {
            "output_path": {
                "type": "string",
                "description": "Directory path for CSV export (default: exports/)"
            }
        },
        "required": []
    }

    tool = ToolDefinition(
        name="05_Export_DAX_Measures",
        description="""Export all DAX measures to CSV file.

Creates a CSV with columns: Table, Measure_Name, Display_Folder, DAX_Expression

Use this to get a complete list of all measures in the model with their DAX definitions.""",
        handler=handle_export_dax_measures,
        input_schema=input_schema,
        category="dax",
        sort_order=53  # 05 = DAX Intelligence
    )

    registry.register(tool)
    logger.info("Registered export_dax_measures handler")


def register_column_usage_handler(registry):
    """Register the column usage mapping handler"""

    input_schema = {
        "type": "object",
        "description": """Analyze column usage in the Power BI model.

PRIMARY USE CASES:
1. **get_unused_columns**: Find columns not used by measures OR relationships (single call!)
2. get_measures_for_tables: Which measures use columns from these tables?
3. get_columns_for_measure: What columns does a measure reference?
4. get_measures_for_column: What measures reference a specific column?
5. export_to_csv: Export mappings to CSV for Excel analysis

Operations:
- get_unused_columns: Find unused columns (checks measures AND relationships)
- get_measures_for_tables: Which measures use columns from these tables?
- get_columns_for_measure: What columns does this measure use?
- get_measures_for_column: What measures use this column?
- get_full_mapping: Complete bidirectional mapping
- export_to_csv: Export to CSV files for Excel""",
        "properties": {
            "operation": {
                "type": "string",
                "description": "Operation to perform. Use 'get_unused_columns' to find columns not used by measures or relationships.",
                "enum": [
                    "get_unused_columns",
                    "get_measures_for_tables",
                    "get_columns_for_measure",
                    "get_measures_for_column",
                    "get_full_mapping",
                    "export_to_csv"
                ],
                "default": "get_unused_columns"
            },
            "tables": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of table names to filter (optional - if not provided, includes all tables)"
            },
            "table": {
                "type": "string",
                "description": "Table name (for get_columns_for_measure, get_measures_for_column)"
            },
            "measure": {
                "type": "string",
                "description": "Measure name (for get_columns_for_measure)"
            },
            "column": {
                "type": "string",
                "description": "Column name (for get_measures_for_column)"
            },
            "group_by": {
                "type": "string",
                "description": "How to group results for get_measures_for_tables: 'table' (by table then column), 'column' (by column key), 'measure' (by measure), 'flat' (unique measure list)",
                "enum": ["table", "column", "measure", "flat"],
                "default": "flat"
            },
            "output_path": {
                "type": "string",
                "description": "Directory path for CSV export (default: exports/)"
            },
            "include_dax": {
                "type": "boolean",
                "description": "Include DAX expressions (default: false - smaller output)",
                "default": False
            },
            "force_refresh": {
                "type": "boolean",
                "description": "Force refresh of cached mapping (default: false)",
                "default": False
            }
        },
        "required": ["operation"],
        "examples": [
            {
                "_description": "Find ALL unused columns in the model (not used by measures or relationships)",
                "operation": "get_unused_columns"
            },
            {
                "_description": "Find unused columns in specific tables",
                "operation": "get_unused_columns",
                "tables": ["f Valtrans", "f Sales"]
            },
            {
                "_description": "Find measures using specific tables",
                "operation": "get_measures_for_tables",
                "tables": ["f Valtrans"],
                "group_by": "flat"
            },
            {
                "_description": "Find what columns a measure uses",
                "operation": "get_columns_for_measure",
                "table": "Measures",
                "measure": "Total Sales"
            },
            {
                "_description": "Find what measures use a specific column",
                "operation": "get_measures_for_column",
                "table": "f Sales",
                "column": "Amount"
            },
            {
                "_description": "Export to CSV for Excel analysis",
                "operation": "export_to_csv"
            }
        ]
    }

    tool = ToolDefinition(
        name="05_Column_Usage_Mapping",
        description="""Analyze column usage - find unused columns, check measure dependencies.

SIMPLE USAGE:
- Find unused columns: operation: get_unused_columns (checks measures AND relationships!)
- Find unused in specific tables: operation: get_unused_columns, tables: ["f Valtrans"]

OTHER USE CASES:
- Which measures use a table's columns: get_measures_for_tables
- What columns does a measure use: get_columns_for_measure
- Export to CSV for Excel: export_to_csv

Returns CSV file paths or compact JSON results.""",
        handler=handle_column_usage_mapping,
        input_schema=input_schema,
        category="dax",
        sort_order=54  # 05 = DAX Intelligence
    )

    registry.register(tool)
    logger.info("Registered column_usage_mapping handler")
