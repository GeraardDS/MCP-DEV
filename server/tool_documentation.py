"""
Tool Documentation Reference System
Maps tool names to their detailed documentation and examples.
Examples are kept separate for token optimization - retrieved on-demand.
"""

# Tool examples - extracted from tool_schemas.py for token optimization
TOOL_EXAMPLES = {
    'run_dax': [
        {"_description": "Simple table preview", "query": "EVALUATE TOPN(10, 'Sales')", "top_n": 10},
        {"_description": "Aggregation with grouping", "query": "EVALUATE SUMMARIZECOLUMNS('Product'[Category], \"TotalSales\", SUM('Sales'[Amount]))"},
        {"_description": "Measure with profiling", "query": "EVALUATE ROW(\"Result\", [Total Sales])", "mode": "profile"},
        {"_description": "Filter table", "query": "EVALUATE FILTER('Customer', 'Customer'[Country] = \"USA\")", "top_n": 50}
    ],
    'get_column_value_distribution': [
        {"_description": "Top countries", "table": "Customer", "column": "Country", "top_n": 10},
        {"_description": "Category distribution", "table": "Product", "column": "Category"}
    ],
    'get_column_summary': [
        {"_description": "CustomerID stats", "table": "Customer", "column": "CustomerID"},
        {"_description": "Analyze blanks", "table": "Sales", "column": "Amount"}
    ],
    'validate_dax_query': [
        {"_description": "Validate EVALUATE", "query": "EVALUATE SUMMARIZE('Sales', 'Product'[Category])"},
        {"_description": "Validate measure", "query": "CALCULATE(SUM(Sales[Amount]), FILTER(ALL(Date), Date[Year] = 2024))"}
    ],
    'list_measures': [
        {"_description": "All measures"},
        {"_description": "Sales table only", "table": "Sales"},
        {"_description": "Paginated", "page_size": 50}
    ],
    'get_measure_details': [
        {"_description": "Get Total Revenue", "table": "Sales", "measure": "Total Revenue"}
    ],
    'bulk_create_measures': [
        {"_description": "Create sales measures", "measures": [
            {"table": "Sales", "measure": "Total Sales", "expression": "SUM(Sales[Amount])"},
            {"table": "Sales", "measure": "Avg Sales", "expression": "AVERAGE(Sales[Amount])"}
        ]}
    ],
    'create_calculation_group': [
        {"_description": "Time Intelligence group", "name": "Time Intelligence", "items": [
            {"name": "Current", "expression": "SELECTEDMEASURE()"},
            {"name": "YTD", "expression": "CALCULATE(SELECTEDMEASURE(), DATESYTD('Date'[Date]))"},
            {"name": "PY", "expression": "CALCULATE(SELECTEDMEASURE(), SAMEPERIODLASTYEAR('Date'[Date]))"}
        ], "precedence": 10}
    ],
    'simple_analysis': [
        {"_description": "Complete analysis (recommended)", "mode": "all"},
        {"_description": "Quick table list", "mode": "tables"},
        {"_description": "Specific measure", "mode": "measure", "table": "Sales", "measure_name": "Total Revenue"},
        {"_description": "Columns in table", "mode": "columns", "table": "Customer", "max_results": 50}
    ],
    'full_analysis': [
        {"_description": "Complete analysis", "scope": "all", "depth": "balanced"},
        {"_description": "Quick BPA scan", "scope": "best_practices", "depth": "fast"},
        {"_description": "Skip BPA", "scope": "all", "include_bpa": False},
        {"_description": "Time-limited", "scope": "all", "max_seconds": 30}
    ],
    'analyze_measure_dependencies': [
        {"_description": "Analyze with diagram", "table": "Sales", "measure": "Profit Margin"},
        {"_description": "No diagram", "table": "_Measures", "measure": "YTD Revenue", "include_diagram": False}
    ],
    'get_measure_impact': [
        {"_description": "Impact analysis", "table": "Sales", "measure": "Total Sales"}
    ],
    'dax_intelligence': [
        {"_description": "Analyze by measure name", "expression": "Total Revenue"},
        {"_description": "Full DAX analysis", "expression": "CALCULATE(SUM(Sales[Amount]), Date[Year]=2024)", "analysis_mode": "all"},
        {"_description": "Debug mode", "expression": "Profit Margin", "analysis_mode": "debug", "output_format": "friendly"},
        {"_description": "Report mode", "expression": "VAR _Total = SUM(Sales[Amount]) RETURN _Total", "analysis_mode": "report"}
    ],
    'analyze_pbip_repository': [
        {"_description": "Analyze PBIP", "pbip_path": "C:/repos/MyModel/MyModel.pbip"},
        {"_description": "Custom output", "pbip_path": "C:/repos/MyModel/MyModel.pbip", "output_path": "C:/reports"}
    ],
    'pbip_dependency_analysis': [
        {"_description": "Generate analysis", "pbip_folder_path": "C:/repos/MyProject/MyModel.SemanticModel"},
        {"_description": "Select specific item", "pbip_folder_path": "C:/repos/MyProject", "main_item": "Measures[Total Sales]"}
    ],
    'slicer_operations': [
        {"_description": "List slicers", "pbip_path": "C:/repos/MyProject.Report", "operation": "list"},
        {"_description": "Filter by entity", "pbip_path": "C:/repos/MyProject", "operation": "list", "entity": "d Assetinstrument"},
        {"_description": "Configure single-select", "pbip_path": "C:/repos/MyProject", "operation": "configure_single_select", "display_name": "Choose an asset", "dry_run": True},
        {"_description": "List interactions", "pbip_path": "C:/repos/MyProject", "operation": "list_interactions"},
        {"_description": "Set interaction", "pbip_path": "C:/repos/MyProject", "operation": "set_interaction", "page_name": "Dashboard", "source_visual": "Slicer A", "target_visual": "Chart B", "interaction_type": "NoFilter"}
    ],
    'visual_operations': [
        {"_description": "List visuals", "pbip_path": "C:/repos/MyProject.Report", "operation": "list"},
        {"_description": "Find by title", "pbip_path": "C:/repos/MyProject", "operation": "list", "display_title": "Sales Chart"},
        {"_description": "Update position", "pbip_path": "C:/repos/MyProject", "operation": "update_position", "display_title": "My Visual", "x": 100, "y": 200, "dry_run": True},
        {"_description": "Replace measure", "pbip_path": "C:/repos/MyProject", "operation": "replace_measure", "source_entity": "m Measure", "source_property": "Amount", "target_entity": "d Attr", "target_property": "New Amount"},
        {"_description": "Sync visual", "pbip_path": "C:/repos/MyProject", "operation": "sync_visual", "display_title": "Revenue Chart", "source_page": "Dashboard", "dry_run": True}
    ],
    'report_info': [
        {"_description": "Full report info", "pbip_path": "C:/repos/MyProject.Report"},
        {"_description": "Compact single page", "pbip_path": "C:/repos/MyProject", "page_name": "Dashboard", "summary_only": True},
        {"_description": "Filters only", "pbip_path": "C:/repos/MyProject", "include_visuals": False},
        {"_description": "Summary of all pages", "pbip_path": "C:/repos/MyProject", "summary_only": True}
    ],
    'analyze_aggregation': [
        {"_description": "Quick summary", "pbip_path": "C:/repos/MyModel", "output_format": "summary"},
        {"_description": "Detailed text", "pbip_path": "C:/repos/MyModel", "output_format": "detailed"},
        {"_description": "HTML report", "pbip_path": "C:/repos/MyModel", "output_format": "html"}
    ],
    'analyze_bookmarks': [
        {"_description": "Analyze bookmarks", "pbip_path": "C:/repos/MyProject.Report"},
        {"_description": "No auto-open", "pbip_path": "C:/repos/MyProject", "auto_open": False}
    ],
    'analyze_theme_compliance': [
        {"_description": "Analyze theme", "pbip_path": "C:/repos/MyProject.Report"},
        {"_description": "Custom theme", "pbip_path": "C:/repos/MyProject", "theme_path": "C:/themes/corporate.json"}
    ]
}

TOOL_DOCS = {
    # Analysis Tools
    'simple_analysis': {
        'doc_url': 'docs/AGENTIC_ROUTING_GUIDE.md#simple-analysis',
        'summary': 'Quick model analysis (2-5s)',
        'key_points': ['Use mode="all" for complete overview', 'Fast: tables (<500ms), stats (<1s)'],
        'operations': {
            'all': 'Run ALL operations + expert analysis',
            'tables': 'List tables (<500ms)',
            'stats': 'Model statistics (<1s)',
            'measures': 'List measures',
            'measure': 'Get measure details (requires table, measure_name)',
            'columns': 'List columns',
            'relationships': 'List relationships',
            'calculation_groups': 'List calculation groups',
            'roles': 'List security roles'
        }
    },

    'full_analysis': {
        'doc_url': 'docs/AGENTIC_ROUTING_GUIDE.md#full-analysis',
        'summary': 'Comprehensive analysis with BPA, performance, integrity',
        'key_points': ['Use scope="all", depth="balanced"'],
        'scopes': {'all': 'All analyses', 'best_practices': 'BPA focus', 'performance': 'Cardinality', 'integrity': 'Validation'},
        'depths': {'fast': 'Quick', 'balanced': 'Recommended', 'deep': 'Thorough'}
    },

    'dax_intelligence': {
        'doc_url': 'docs/DAX_INTELLIGENCE_GUIDE.md',
        'summary': 'DAX validation, analysis, debugging with VertiPaq',
        'key_points': [
            'Accepts measure name OR DAX expression (auto-detects)',
            'Default mode="all" runs analyze+debug+report',
            'Auto-fetches measure DAX when name provided',
            '11 anti-pattern detectors with SQLBI references'
        ],
        'modes': {
            'all': 'All modes combined',
            'analyze': 'Context transitions + anti-patterns',
            'debug': 'Step-by-step with friendly output',
            'report': '8 analysis modules + VertiPaq'
        }
    },

    'run_dax': {
        'summary': 'Execute DAX queries',
        'modes': {'auto': 'Smart choice', 'analyze': 'With timing', 'profile': 'With timing', 'simple': 'Preview only'},
        'defaults': {'top_n': 100, 'mode': 'auto'}
    },

    'tmdl_operations': {
        'summary': 'TMDL export, find/replace, bulk rename, scripts',
        'operations': {'export': 'Export TMDL', 'find_replace': 'Regex find/replace', 'bulk_rename': 'Rename with refs', 'generate_script': 'Generate script'}
    },

    'table_operations': {
        'summary': 'Table CRUD: list|describe|preview|create|update|delete|rename|refresh',
        'operations': {'list': 'List tables', 'describe': 'Table details', 'preview': 'Sample data', 'create': 'New table', 'update': 'Update props', 'delete': 'Delete', 'rename': 'Rename', 'refresh': 'Refresh data'}
    },

    'column_operations': {
        'summary': 'Column CRUD: list|get|statistics|distribution|create|update|delete|rename',
        'operations': {'list': 'List columns', 'get': 'Column metadata', 'statistics': 'Stats', 'distribution': 'Top N values', 'create': 'New column', 'update': 'Update props', 'delete': 'Delete', 'rename': 'Rename'}
    },

    'measure_operations': {
        'summary': 'Measure CRUD: list|get|create|update|delete|rename|move',
        'operations': {'list': 'List names', 'get': 'Get with DAX', 'create': 'New measure', 'update': 'Update', 'delete': 'Delete', 'rename': 'Rename', 'move': 'Move to table'}
    },

    'relationship_operations': {
        'summary': 'Relationship CRUD: list|get|find|create|update|delete|activate|deactivate',
        'operations': {'list': 'List all', 'get': 'Details', 'find': 'Find for table', 'create': 'New', 'update': 'Update', 'delete': 'Delete', 'activate': 'Activate', 'deactivate': 'Deactivate'}
    },

    'calculation_group_operations': {
        'summary': 'Calc group CRUD: list|list_items|create|delete',
        'operations': {'list': 'List groups', 'list_items': 'Items in group', 'create': 'New group', 'delete': 'Delete'}
    },

    'role_operations': {
        'summary': 'RLS/OLS role operations',
        'operations': {'list': 'List security roles'}
    }
}


def get_tool_documentation(tool_name: str) -> dict:
    """Get detailed documentation for a tool."""
    return TOOL_DOCS.get(tool_name, {'summary': 'Documentation not available', 'key_points': []})


def get_tool_examples(tool_name: str) -> list:
    """
    Get examples for a tool. Examples are stored separately for token optimization.

    Args:
        tool_name: Name of the tool

    Returns:
        List of example dictionaries, or empty list if not found
    """
    return TOOL_EXAMPLES.get(tool_name, [])


def get_operation_details(tool_name: str, operation: str) -> str:
    """Get details for a specific operation of a tool."""
    tool_doc = TOOL_DOCS.get(tool_name, {})
    operations = tool_doc.get('operations', {})
    return operations.get(operation, f'Operation: {operation}')


def list_available_docs() -> list:
    """Get list of tools with available documentation."""
    return list(TOOL_DOCS.keys())


def list_available_examples() -> list:
    """Get list of tools with available examples."""
    return list(TOOL_EXAMPLES.keys())
