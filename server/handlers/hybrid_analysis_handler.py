"""
Hybrid Analysis MCP Tool Handlers

Provides MCP tool handlers for PBIP dependency analysis.
"""

import logging
import traceback
from pathlib import Path
from typing import Dict, Any

from core.utilities.pbip_dependency_html_generator import generate_pbip_dependency_html
from server.registry import ToolDefinition
from server.tool_schemas import TOOL_SCHEMAS
from server.pbip_cache import pbip_cache, normalize_pbip_path

logger = logging.getLogger(__name__)


def handle_generate_pbip_dependency_diagram(args: Dict[str, Any]) -> Dict[str, Any]:
    """Generate an interactive HTML dependency diagram for a PBIP project."""
    try:
        pbip_folder_path = args.get('pbip_folder_path', '')
        auto_open = args.get('auto_open', True)
        output_path = args.get('output_path')
        main_item = args.get('main_item')

        # Use shared cache for parsing + dependency analysis
        path = normalize_pbip_path(pbip_folder_path)
        data = pbip_cache.get_or_parse(path)

        model_data = data.model_data
        report_data = data.report_data
        dependency_data = data.dependencies

        # Derive model name from path
        p = Path(path)
        model_name = p.stem.replace('.SemanticModel', '') if p.name.endswith('.SemanticModel') else p.name

        logger.info(f"Generating PBIP dependency diagram for: {model_name}")

        logger.info(f"    ✓ Analyzed {dependency_data['summary']['total_measures']} measures, "
                   f"{dependency_data['summary']['total_columns']} columns")
        if report_data:
            logger.info(f"    ✓ Analyzed {dependency_data['summary'].get('total_visuals', 0)} visuals "
                       f"across {dependency_data['summary'].get('total_pages', 0)} pages")

        # Step 4: Generate HTML diagram
        logger.info("  - Generating interactive HTML diagram...")
        html_path = generate_pbip_dependency_html(
            dependency_data=dependency_data,
            model_name=model_name,
            auto_open=auto_open,
            output_path=output_path,
            main_item=main_item
        )

        if html_path:
            logger.info(f"  ✓ Diagram generated: {html_path}")
            return {
                'success': True,
                'message': f"✓ PBIP dependency diagram generated successfully",
                'diagram_path': html_path,
                'model_name': model_name,
                'initial_selection': main_item if main_item else 'First measure in model',
                'summary': {
                    'visuals': dependency_data['summary'].get('total_visuals', 0),
                    'pages': dependency_data['summary'].get('total_pages', 0),
                    'measures': dependency_data['summary']['total_measures'],
                    'columns': dependency_data['summary']['total_columns'],
                    'field_parameters': len(dependency_data.get('column_to_field_params', {})),
                    'unused_measures': dependency_data['summary']['unused_measures'],
                    'unused_columns': dependency_data['summary']['unused_columns']
                },
                'features': [
                    'Left sidebar with ALL measures, columns, and field parameters',
                    'Click any item in sidebar to view its dependencies in tables',
                    'Search/filter items by name',
                    'Items grouped by table with expand/collapse',
                    'Clean table-based upstream & downstream dependency view',
                    'Model overview with statistics',
                    'Auto-opens in browser' if auto_open else 'Saved to file'
                ]
            }
        else:
            return {
                'success': False,
                'error': 'Failed to generate HTML diagram',
                'error_type': 'generation_error'
            }

    except Exception as e:
        logger.error(f"Error generating PBIP dependency diagram: {str(e)}\n{traceback.format_exc()}")
        return {
            'success': False,
            'error': f"Diagram generation failed: {str(e)}",
            'error_type': 'generation_error',
            'context': {
                'pbip_folder_path': pbip_folder_path
            }
        }


def register_hybrid_analysis_handlers(registry):
    """Register hybrid analysis tool handlers"""

    registry.register(ToolDefinition(
        name='07_PBIP_Dependency_Analysis',
        description='Interactive HTML dependency analysis for PBIP project. Sidebar with measures/columns/field parameters, upstream/downstream tables. Auto-opens in browser.',
        handler=handle_generate_pbip_dependency_diagram,
        input_schema=TOOL_SCHEMAS.get('pbip_dependency_analysis', {}),
        category='pbip',
        sort_order=72,  # 07 = PBIP Analysis
        annotations={"readOnlyHint": True},
    ))

    logger.info("Registered 1 hybrid analysis handler")
