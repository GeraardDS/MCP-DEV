"""
Suggested Actions Utility
Provides context-aware next action suggestions for tool responses

Enhanced in v6.5.0:
- Added suggestions for dax_intelligence, analyze_pbip_repository, export_hybrid_analysis
- Added intelligent branching based on result content
- Added workflow suggestions for common patterns
- Improved context mapping between tools
"""
from typing import Dict, Any, List, Optional

# Enable suggested actions - but AI should ALWAYS ask user before executing them
ENABLE_SUGGESTED_ACTIONS = True

def add_suggested_actions(
    result: Dict[str, Any],
    tool_name: str,
    context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Add suggested next actions to tool response based on tool name and context

    Args:
        result: The tool response dictionary
        tool_name: Name of the tool that generated this response
        context: Optional context information (e.g., table name, measure count)

    Returns:
        Updated result dictionary with suggested_actions field
    """
    if not ENABLE_SUGGESTED_ACTIONS:
        return result

    if not result.get('success'):
        return result

    context = context or {}
    suggestions = _get_suggestions_for_tool(tool_name, result, context)

    if suggestions:
        # Add clear notice that these are suggestions only - DO NOT auto-execute
        result['suggested_actions'] = {
            '_notice': '⚠️ SUGGESTIONS ONLY - Do not execute without explicit user approval',
            'suggestions': suggestions
        }
        result['workflow_hint'] = _get_workflow_hint(tool_name, result, context)

    return result


def _get_suggestions_for_tool(
    tool_name: str,
    result: Dict[str, Any],
    context: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Generate suggestions based on tool name and result"""

    suggestions_map = {
        'list_tables': _suggest_after_list_tables,
        'describe_table': _suggest_after_describe_table,
        'list_measures': _suggest_after_list_measures,
        'list_columns': _suggest_after_list_columns,
        'get_measure_details': _suggest_after_measure_details,
        'preview_table_data': _suggest_after_preview_data,
        'run_dax': _suggest_after_run_dax,
        'search_objects': _suggest_after_search_objects,
        'list_relationships': _suggest_after_list_relationships,
        'comprehensive_analysis': _suggest_after_analysis,
        'connect_to_powerbi': _suggest_after_connection,
        # NEW v6.5.0 additions
        'dax_intelligence': _suggest_after_dax_intelligence,
        'analyze_measure_dependencies': _suggest_after_dependencies,
        'get_measure_impact': _suggest_after_impact,
        'simple_analysis': _suggest_after_simple_analysis,
        'full_analysis': _suggest_after_full_analysis,
        'analyze_pbip_repository': _suggest_after_pbip_analysis,
        'export_hybrid_analysis': _suggest_after_hybrid_export,
        'analyze_hybrid_model': _suggest_after_hybrid_analysis,
        'batch_operations': _suggest_after_batch_operations,
        'tmdl_operations': _suggest_after_tmdl_operations,
    }

    suggest_fn = suggestions_map.get(tool_name)
    if suggest_fn:
        return suggest_fn(result, context)

    return []


def _suggest_after_list_tables(result: Dict[str, Any], context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Suggestions after listing tables"""
    rows = result.get('rows', [])
    if not rows:
        return []

    first_table = rows[0].get('TABLE_NAME') or rows[0].get('[TABLE_NAME]', 'Sales')

    return [
        {
            'action': 'explore_table',
            'description': 'Get detailed information about a specific table including columns, measures, and relationships',
            'tool': 'describe_table',
            'example': {'table': first_table}
        },
        {
            'action': 'preview_data',
            'description': 'Preview sample data from a table',
            'tool': 'preview_table_data',
            'example': {'table': first_table, 'max_rows': 10}
        },
        {
            'action': 'search_for_measures',
            'description': 'Find all measures in a table or across the model',
            'tool': 'list_measures',
            'example': {'table': first_table}
        },
        {
            'action': 'analyze_model',
            'description': 'Run comprehensive analysis to check for issues and optimization opportunities',
            'tool': 'comprehensive_analysis',
            'example': {'scope': 'all', 'depth': 'balanced'}
        }
    ]


def _suggest_after_describe_table(result: Dict[str, Any], context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Suggestions after describing a table"""
    table_name = context.get('table') or result.get('table', 'YourTable')
    measures = result.get('measures', [])
    columns = result.get('columns', [])

    suggestions = [
        {
            'action': 'preview_data',
            'description': 'Preview sample data from this table',
            'tool': 'preview_table_data',
            'example': {'table': table_name, 'max_rows': 10}
        }
    ]

    if measures:
        first_measure = measures[0].get('MEASURE_NAME') or measures[0].get('[MEASURE_NAME]', 'TotalSales')
        suggestions.append({
            'action': 'analyze_measure',
            'description': 'Analyze a specific measure with DAX intelligence',
            'tool': 'dax_intelligence',
            'example': {'table': table_name, 'measure': first_measure, 'mode': 'analyze'}
        })
        suggestions.append({
            'action': 'check_dependencies',
            'description': 'Analyze measure dependencies',
            'tool': 'analyze_measure_dependencies',
            'example': {'table': table_name, 'measure': first_measure}
        })

    if columns:
        first_column = columns[0].get('COLUMN_NAME') or columns[0].get('[COLUMN_NAME]', 'Date')
        suggestions.append({
            'action': 'analyze_column',
            'description': 'Get value distribution for a column',
            'tool': 'get_column_value_distribution',
            'example': {'table': table_name, 'column': first_column, 'top_n': 10}
        })

    return suggestions


def _suggest_after_list_measures(result: Dict[str, Any], context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Suggestions after listing measures"""
    rows = result.get('rows', [])
    if not rows:
        return []

    first_measure = rows[0].get('MEASURE_NAME') or rows[0].get('[MEASURE_NAME]', 'TotalSales')
    table_name = rows[0].get('TABLE_NAME') or rows[0].get('[TABLE_NAME]', 'Sales')

    return [
        {
            'action': 'get_details',
            'description': 'Get detailed information about a specific measure including DAX formula',
            'tool': 'get_measure_details',
            'example': {'table': table_name, 'measure': first_measure}
        },
        {
            'action': 'analyze_dax',
            'description': 'Analyze DAX formula with syntax validation and context analysis',
            'tool': 'dax_intelligence',
            'example': {'table': table_name, 'measure': first_measure, 'mode': 'analyze'}
        },
        {
            'action': 'check_dependencies',
            'description': 'Analyze dependencies for a measure',
            'tool': 'analyze_measure_dependencies',
            'example': {'table': table_name, 'measure': first_measure}
        },
        {
            'action': 'search_usage',
            'description': 'Search for measures using specific DAX functions or patterns',
            'tool': 'search_string',
            'example': {'search_text': 'CALCULATE', 'search_in_expression': True}
        }
    ]


def _suggest_after_list_columns(result: Dict[str, Any], context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Suggestions after listing columns"""
    rows = result.get('rows', [])
    if not rows:
        return []

    first_column = rows[0].get('COLUMN_NAME') or rows[0].get('[COLUMN_NAME]', 'Date')
    table_name = rows[0].get('TABLE_NAME') or rows[0].get('[TABLE_NAME]', 'Sales')

    return [
        {
            'action': 'get_distribution',
            'description': 'Get value distribution for a column',
            'tool': 'get_column_value_distribution',
            'example': {'table': table_name, 'column': first_column, 'top_n': 10}
        },
        {
            'action': 'get_summary',
            'description': 'Get summary statistics for a column',
            'tool': 'get_column_summary',
            'example': {'table': table_name, 'column': first_column}
        },
        {
            'action': 'preview_data',
            'description': 'Preview sample data from the table',
            'tool': 'preview_table_data',
            'example': {'table': table_name, 'max_rows': 10}
        }
    ]


def _suggest_after_measure_details(result: Dict[str, Any], context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Suggestions after getting measure details"""
    table = context.get('table') or result.get('table', 'Sales')
    measure = context.get('measure') or result.get('measure', 'TotalSales')

    return [
        {
            'action': 'analyze_dax',
            'description': 'Analyze this DAX formula for syntax, context transitions, and optimization',
            'tool': 'dax_intelligence',
            'example': {'table': table, 'measure': measure, 'mode': 'analyze'}
        },
        {
            'action': 'check_dependencies',
            'description': 'Analyze what this measure depends on',
            'tool': 'analyze_measure_dependencies',
            'example': {'table': table, 'measure': measure}
        },
        {
            'action': 'check_impact',
            'description': 'Check what other objects depend on this measure',
            'tool': 'get_measure_impact',
            'example': {'table': table, 'measure': measure}
        }
    ]


def _suggest_after_preview_data(result: Dict[str, Any], context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Suggestions after previewing table data"""
    table = context.get('table', 'YourTable')

    return [
        {
            'action': 'describe_table',
            'description': 'Get full table structure with columns, measures, and relationships',
            'tool': 'describe_table',
            'example': {'table': table}
        },
        {
            'action': 'analyze_column',
            'description': 'Analyze column value distribution',
            'tool': 'get_column_value_distribution',
            'example': {'table': table, 'column': 'YourColumn', 'top_n': 10}
        },
        {
            'action': 'run_custom_query',
            'description': 'Run a custom DAX query on this table',
            'tool': 'run_dax',
            'example': {'query': f"EVALUATE TOPN(100, '{table}')", 'mode': 'auto'}
        }
    ]


def _suggest_after_run_dax(result: Dict[str, Any], context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Suggestions after running a DAX query"""
    suggestions = []

    # Check if query had performance issues
    if result.get('storage_engine_ms', 0) > 1000:
        suggestions.append({
            'action': 'optimize_performance',
            'description': 'Query took over 1 second - run comprehensive performance analysis',
            'tool': 'comprehensive_analysis',
            'example': {'scope': 'performance', 'depth': 'balanced'}
        })

    return suggestions


def _suggest_after_search_objects(result: Dict[str, Any], context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Suggestions after searching objects"""
    items = result.get('items', result.get('rows', []))
    if not items:
        return []

    suggestions = []

    # Check what types of objects were found
    for item in items[:3]:  # Only check first 3
        obj_type = item.get('TYPE', '').lower()
        name = item.get('NAME', '')
        table = item.get('TABLE_NAME', '')

        if obj_type == 'table' and table:
            suggestions.append({
                'action': 'explore_table',
                'description': f'Explore {table} in detail',
                'tool': 'describe_table',
                'example': {'table': table}
            })
            break
        elif obj_type == 'measure' and name and table:
            suggestions.append({
                'action': 'analyze_measure',
                'description': f'Analyze {name} with DAX intelligence',
                'tool': 'dax_intelligence',
                'example': {'table': table, 'measure': name, 'mode': 'analyze'}
            })
            break

    return suggestions


def _suggest_after_list_relationships(result: Dict[str, Any], context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Suggestions after listing relationships"""
    return [
        {
            'action': 'visualize_relationships',
            'description': 'Generate relationship graph visualization',
            'tool': 'generate_relationships_graph',
            'example': {}
        },
        {
            'action': 'analyze_integrity',
            'description': 'Check for relationship issues and best practices violations',
            'tool': 'comprehensive_analysis',
            'example': {'scope': 'integrity', 'depth': 'balanced'}
        }
    ]


def _suggest_after_analysis(result: Dict[str, Any], context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Suggestions after comprehensive analysis"""
    issues = result.get('issues', [])

    suggestions = []

    if issues:
        # High priority: suggest reviewing specific issues
        high_severity_issues = [i for i in issues if i.get('severity') in ['high', 'critical']]
        if high_severity_issues:
            suggestions.append({
                'action': 'review_critical_issues',
                'description': 'Review and fix critical/high severity issues first',
                'note': f'Found {len(high_severity_issues)} high/critical issues'
            })

    suggestions.extend([
        {
            'action': 'export_documentation',
            'description': 'Generate Word documentation with these findings',
            'tool': 'generate_model_documentation_word',
            'example': {'file_path': 'model_documentation.docx'}
        }
    ])

    return suggestions


def _suggest_after_connection(result: Dict[str, Any], context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Suggestions after connecting to Power BI (will be enhanced with proactive recommendations)"""
    return [
        {
            'action': 'explore_schema',
            'description': 'List all tables in the model',
            'tool': 'list_tables',
            'example': {}
        },
        {
            'action': 'quick_health_check',
            'description': 'Run a quick comprehensive analysis',
            'tool': 'comprehensive_analysis',
            'example': {'scope': 'all', 'depth': 'fast'}
        },
        {
            'action': 'search_model',
            'description': 'Search for specific objects in the model',
            'tool': 'search_objects',
            'example': {'pattern': '*', 'types': ['tables', 'measures']}
        }
    ]


def _get_workflow_hint(tool_name: str, result: Dict[str, Any], context: Dict[str, Any]) -> str:
    """Generate a workflow hint message"""

    hints_map = {
        'list_tables': lambda r, c: f"Found {len(r.get('rows', []))} tables. Next: Explore a table with describe_table or run simple_analysis for health check.",
        'describe_table': lambda r, c: f"Table '{c.get('table', 'table')}' has {len(r.get('columns', []))} columns and {len(r.get('measures', []))} measures. Next: Preview data or analyze measures.",
        'list_measures': lambda r, c: f"Found {len(r.get('rows', []))} measures. Next: Get details or analyze DAX with dax_intelligence.",
        'list_columns': lambda r, c: f"Found {len(r.get('rows', []))} columns. Next: Analyze value distribution or preview data.",
        'comprehensive_analysis': lambda r, c: f"Analysis complete. Found {len(r.get('issues', []))} issues. Next: Review findings and export documentation.",
        'connect_to_powerbi': lambda r, c: "Connected successfully. Next: Explore schema with simple_analysis or search_objects.",
        # NEW v6.5.0 hints
        'dax_intelligence': lambda r, c: f"DAX analysis complete. Found {len(r.get('issues', []))} issues and {len(r.get('optimizations', []))} optimization opportunities.",
        'simple_analysis': lambda r, c: f"Quick analysis complete. {r.get('table_count', 0)} tables, {r.get('measure_count', 0)} measures. Run full_analysis for detailed BPA.",
        'full_analysis': lambda r, c: f"Full analysis complete. Found {len(r.get('issues', []))} issues. Review high-priority items first.",
        'analyze_measure_dependencies': lambda r, c: f"Found {len(r.get('referenced_measures', []))} measure dependencies. Check impact before modifying.",
        'get_measure_impact': lambda r, c: f"Measure has {r.get('impact_score', {}).get('total_dependents', 0)} dependents. High-impact measures need careful testing.",
    }

    hint_fn = hints_map.get(tool_name)
    if hint_fn:
        try:
            return hint_fn(result, context)
        except Exception:
            return ""

    return ""


# ==================== NEW v6.5.0 Suggestion Functions ====================

def _suggest_after_dax_intelligence(result: Dict[str, Any], context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Suggestions after DAX intelligence analysis"""
    table = context.get('table') or result.get('table', '')
    measure = context.get('measure') or result.get('measure', '')
    suggestions = []

    # Check for optimization opportunities
    optimizations = result.get('optimizations', []) or result.get('code_improvements', [])
    if optimizations:
        suggestions.append({
            'action': 'apply_optimization',
            'description': 'Apply suggested DAX optimizations using measure operations',
            'tool': 'measure_operations',
            'example': {'operation': 'update', 'table': table, 'measure': measure}
        })

    # Check for dependencies
    suggestions.append({
        'action': 'check_dependencies',
        'description': 'Analyze what this measure depends on',
        'tool': 'analyze_measure_dependencies',
        'example': {'table': table, 'measure': measure}
    })

    # Check for impact
    suggestions.append({
        'action': 'check_impact',
        'description': 'See what depends on this measure before making changes',
        'tool': 'get_measure_impact',
        'example': {'table': table, 'measure': measure}
    })

    # If issues found, suggest batch fix
    issues = result.get('issues', [])
    if len(issues) > 3:
        suggestions.append({
            'action': 'review_all_measures',
            'description': 'Multiple issues found - consider reviewing all measures in table',
            'tool': 'dax_intelligence',
            'example': {'table': table, 'mode': 'analyze'}
        })

    return suggestions


def _suggest_after_dependencies(result: Dict[str, Any], context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Suggestions after dependency analysis"""
    table = context.get('table') or result.get('table', '')
    measure = context.get('measure') or result.get('measure', '')
    suggestions = []

    # Suggest impact check (inverse)
    suggestions.append({
        'action': 'check_impact',
        'description': 'Now check what depends ON this measure',
        'tool': 'get_measure_impact',
        'example': {'table': table, 'measure': measure}
    })

    # If complex dependencies, suggest DAX analysis
    ref_measures = result.get('referenced_measures', [])
    if len(ref_measures) > 3:
        suggestions.append({
            'action': 'analyze_dax',
            'description': 'Complex dependency chain - analyze DAX for optimization',
            'tool': 'dax_intelligence',
            'example': {'table': table, 'measure': measure, 'mode': 'analyze'}
        })

    # Suggest visualization
    suggestions.append({
        'action': 'visualize_dependencies',
        'description': 'Generate dependency diagram for documentation',
        'tool': 'analyze_measure_dependencies',
        'example': {'table': table, 'measure': measure, 'output_format': 'mermaid'}
    })

    return suggestions


def _suggest_after_impact(result: Dict[str, Any], context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Suggestions after impact analysis"""
    table = context.get('table') or result.get('table', '')
    measure = context.get('measure') or result.get('measure', '')
    suggestions = []

    impact_score = result.get('impact_score', {})
    total_deps = impact_score.get('total_dependents', 0)

    # Suggest dependency check (inverse)
    suggestions.append({
        'action': 'check_dependencies',
        'description': 'Now check what this measure depends ON',
        'tool': 'analyze_measure_dependencies',
        'example': {'table': table, 'measure': measure}
    })

    # If high impact, suggest thorough testing
    if total_deps > 5:
        suggestions.append({
            'action': 'analyze_dependents',
            'description': f'High impact ({total_deps} dependents) - analyze dependent measures',
            'tool': 'dax_intelligence',
            'example': {'table': table, 'measure': measure, 'mode': 'analyze'}
        })

    # If used in calc groups or RLS
    if impact_score.get('in_calculation_groups') or impact_score.get('in_rls_rules'):
        suggestions.append({
            'action': 'review_security',
            'description': 'Measure used in security/calc groups - review carefully before changes',
            'tool': 'full_analysis',
            'example': {'scope': 'security'}
        })

    return suggestions


def _suggest_after_simple_analysis(result: Dict[str, Any], context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Suggestions after simple analysis"""
    suggestions = []

    # Suggest full analysis for details
    suggestions.append({
        'action': 'full_analysis',
        'description': 'Run detailed BPA and performance analysis',
        'tool': 'full_analysis',
        'example': {'scope': 'all'}
    })

    # If many measures, suggest search
    measure_count = result.get('measure_count', 0)
    if measure_count > 50:
        suggestions.append({
            'action': 'search_measures',
            'description': 'Large model - use search to find specific measures',
            'tool': 'search_objects',
            'example': {'pattern': '*', 'types': ['measures']}
        })

    # Suggest documentation
    suggestions.append({
        'action': 'generate_docs',
        'description': 'Generate model documentation',
        'tool': 'generate_model_documentation_word',
        'example': {}
    })

    return suggestions


def _suggest_after_full_analysis(result: Dict[str, Any], context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Suggestions after full analysis"""
    suggestions = []
    issues = result.get('issues', [])

    # Group issues by type
    perf_issues = [i for i in issues if i.get('category') == 'performance']
    dax_issues = [i for i in issues if i.get('category') in ['anti_pattern', 'dax_complexity']]
    unused_issues = [i for i in issues if 'unused' in str(i.get('category', '')).lower()]

    if perf_issues:
        suggestions.append({
            'action': 'fix_performance',
            'description': f'{len(perf_issues)} performance issues - analyze with DAX intelligence',
            'tool': 'dax_intelligence',
            'example': {'mode': 'optimize'}
        })

    if dax_issues:
        suggestions.append({
            'action': 'review_dax',
            'description': f'{len(dax_issues)} DAX issues - review problematic measures',
            'tool': 'dax_intelligence',
            'example': {'mode': 'analyze'}
        })

    if unused_issues:
        suggestions.append({
            'action': 'cleanup_unused',
            'description': f'{len(unused_issues)} unused objects - consider cleanup',
            'tool': 'batch_operations',
            'example': {'operation': 'delete', 'preview': True}
        })

    # Always suggest documentation
    suggestions.append({
        'action': 'export_documentation',
        'description': 'Generate Word documentation with analysis findings',
        'tool': 'generate_model_documentation_word',
        'example': {}
    })

    return suggestions


def _suggest_after_pbip_analysis(result: Dict[str, Any], context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Suggestions after PBIP repository analysis"""
    suggestions = []

    # Suggest hybrid export for deeper analysis
    suggestions.append({
        'action': 'export_hybrid',
        'description': 'Export hybrid package for offline analysis with sample data',
        'tool': 'export_hybrid_analysis',
        'example': {}
    })

    # If HTML report generated
    if result.get('html_report_path'):
        suggestions.append({
            'action': 'view_report',
            'description': 'HTML report generated - open in browser for interactive analysis',
            'note': f"Report at: {result.get('html_report_path')}"
        })

    return suggestions


def _suggest_after_hybrid_export(result: Dict[str, Any], context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Suggestions after hybrid export"""
    suggestions = []
    export_path = result.get('export_path', result.get('path', ''))

    # Suggest analysis of exported model
    suggestions.append({
        'action': 'analyze_export',
        'description': 'Analyze the exported hybrid model',
        'tool': 'analyze_hybrid_model',
        'example': {'path': export_path}
    })

    return suggestions


def _suggest_after_hybrid_analysis(result: Dict[str, Any], context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Suggestions after hybrid model analysis"""
    suggestions = []

    # Suggest specific tool based on findings
    if result.get('measures'):
        suggestions.append({
            'action': 'review_measures',
            'description': 'Review measures found in hybrid analysis',
            'tool': 'dax_intelligence',
            'example': {'mode': 'analyze'}
        })

    if result.get('data_quality_issues'):
        suggestions.append({
            'action': 'investigate_data',
            'description': 'Data quality issues detected - investigate sample data',
            'tool': 'run_dax',
            'example': {'query': 'EVALUATE ...'}
        })

    return suggestions


def _suggest_after_batch_operations(result: Dict[str, Any], context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Suggestions after batch operations"""
    suggestions = []
    operation = context.get('operation', result.get('operation', ''))

    if operation == 'delete' and result.get('preview'):
        suggestions.append({
            'action': 'confirm_delete',
            'description': 'Preview shown - confirm deletion to execute',
            'tool': 'batch_operations',
            'example': {'operation': 'delete', 'confirm': True}
        })

    # After any batch operation, suggest validation
    suggestions.append({
        'action': 'validate_model',
        'description': 'After batch changes, validate model integrity',
        'tool': 'full_analysis',
        'example': {'scope': 'integrity'}
    })

    return suggestions


def _suggest_after_tmdl_operations(result: Dict[str, Any], context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Suggestions after TMDL operations"""
    suggestions = []
    operation = context.get('operation', result.get('operation', ''))

    if operation == 'export':
        suggestions.append({
            'action': 'analyze_tmdl',
            'description': 'Analyze exported TMDL for patterns',
            'tool': 'analyze_pbip_repository',
            'example': {'path': result.get('export_path', '')}
        })

    if operation in ['find_replace', 'bulk_rename']:
        suggestions.append({
            'action': 'validate_changes',
            'description': 'After TMDL changes, validate model',
            'tool': 'full_analysis',
            'example': {'scope': 'best_practices'}
        })

    return suggestions
