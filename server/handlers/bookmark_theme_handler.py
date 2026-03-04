"""
Bookmark & Theme Compliance Handler
Handles PBIP bookmark analysis and theme compliance tools
"""
from typing import Dict, Any
import logging
import os
from pathlib import Path
from server.registry import ToolDefinition
from core.utilities.pbip_utils import normalize_path as _normalize_path

logger = logging.getLogger(__name__)


def _find_report_folder(pbip_path: str) -> str:
    """Find the .Report folder from a PBIP path."""
    path_obj = Path(pbip_path)

    # Check if path is already a .Report folder
    if path_obj.name.endswith('.Report') and path_obj.is_dir():
        return str(path_obj)

    # If it's a .pbip file, look for sibling .Report folder
    if path_obj.suffix == '.pbip':
        base_name = path_obj.stem
        report_folder = path_obj.parent / f"{base_name}.Report"
        if report_folder.is_dir():
            return str(report_folder)

    # If it's a directory, look for .Report folder inside
    if path_obj.is_dir():
        for item in path_obj.iterdir():
            if item.is_dir() and item.name.endswith('.Report'):
                return str(item)

    raise FileNotFoundError(f"No .Report folder found in: {pbip_path}")


def handle_analyze_bookmarks(args: Dict[str, Any]) -> Dict[str, Any]:
    """Analyze bookmarks in a PBIP report and generate HTML analysis."""
    pbip_path = args.get('pbip_path')
    auto_open = args.get('auto_open', True)
    output_path = args.get('output_path')

    if not pbip_path:
        return {
            'success': False,
            'error': 'pbip_path parameter is required - path to PBIP project or .Report folder'
        }

    try:
        # Normalize path
        normalized_path = _normalize_path(pbip_path)

        # Find report folder
        report_folder = _find_report_folder(normalized_path)

        # Import analyzer and generator
        from core.pbip.pbip_bookmark_analyzer import PbipBookmarkAnalyzer
        from core.pbip.pbip_bookmark_html_generator import generate_bookmark_analysis_html

        # Run analysis
        analyzer = PbipBookmarkAnalyzer()
        analysis_data = analyzer.analyze_bookmarks(report_folder)

        # Get model name from path
        model_name = Path(report_folder).stem.replace('.Report', '')

        # Generate HTML report
        html_path = generate_bookmark_analysis_html(
            analysis_data=analysis_data,
            model_name=model_name,
            auto_open=auto_open,
            output_path=output_path
        )

        if html_path:
            summary = analysis_data.get('summary', {})
            return {
                'success': True,
                'html_report': html_path,
                'message': f'Bookmark analysis HTML generated: {html_path}',
                'summary': {
                    'total_bookmarks': summary.get('total_bookmarks', 0),
                    'categories': summary.get('by_category', {}),
                    'orphaned_count': summary.get('orphaned_count', 0),
                    'avg_complexity': summary.get('avg_complexity', 0),
                    'issue_count': summary.get('issue_count', 0)
                }
            }
        else:
            return {
                'success': False,
                'error': 'Failed to generate HTML report'
            }

    except FileNotFoundError as e:
        return {
            'success': False,
            'error': str(e)
        }
    except Exception as e:
        logger.error(f"Error analyzing bookmarks: {e}", exc_info=True)
        return {
            'success': False,
            'error': f'Error analyzing bookmarks: {str(e)}'
        }


def handle_theme_compliance(args: Dict[str, Any]) -> Dict[str, Any]:
    """Analyze theme compliance in a PBIP report and generate HTML analysis."""
    pbip_path = args.get('pbip_path')
    theme_path = args.get('theme_path')
    auto_open = args.get('auto_open', True)
    output_path = args.get('output_path')

    if not pbip_path:
        return {
            'success': False,
            'error': 'pbip_path parameter is required - path to PBIP project or .Report folder'
        }

    try:
        # Normalize path
        normalized_path = _normalize_path(pbip_path)

        # Find report folder
        report_folder = _find_report_folder(normalized_path)

        # Import analyzer and generator
        from core.pbip.pbip_theme_compliance_analyzer import PbipThemeComplianceAnalyzer
        from core.pbip.pbip_theme_compliance_html_generator import generate_theme_compliance_html

        # Normalize theme path if provided
        if theme_path:
            theme_path = _normalize_path(theme_path)

        # Run analysis
        analyzer = PbipThemeComplianceAnalyzer()
        analysis_data = analyzer.analyze_theme_compliance(
            report_folder=report_folder,
            theme_path=theme_path
        )

        # Get model name from path
        model_name = Path(report_folder).stem.replace('.Report', '')

        # Generate HTML report
        html_path = generate_theme_compliance_html(
            analysis_data=analysis_data,
            model_name=model_name,
            auto_open=auto_open,
            output_path=output_path
        )

        if html_path:
            summary = analysis_data.get('summary', {})
            return {
                'success': True,
                'html_report': html_path,
                'message': f'Theme compliance HTML generated: {html_path}',
                'summary': {
                    'compliance_score': summary.get('compliance_score', 0),
                    'theme_name': summary.get('theme_name', 'Unknown'),
                    'theme_source': summary.get('theme_source', 'Unknown'),
                    'total_pages': summary.get('total_pages', 0),
                    'total_visuals': summary.get('total_visuals', 0),
                    'compliant_visuals': summary.get('compliant_visuals', 0),
                    'unique_colors': summary.get('unique_colors', 0),
                    'unique_fonts': summary.get('unique_fonts', 0),
                    'total_violations': summary.get('total_violations', 0),
                    'warning_count': summary.get('warning_count', 0)
                }
            }
        else:
            return {
                'success': False,
                'error': 'Failed to generate HTML report'
            }

    except FileNotFoundError as e:
        return {
            'success': False,
            'error': str(e)
        }
    except Exception as e:
        logger.error(f"Error analyzing theme compliance: {e}", exc_info=True)
        return {
            'success': False,
            'error': f'Error analyzing theme compliance: {str(e)}'
        }


def register_bookmark_theme_handlers(registry):
    """Register bookmark and theme compliance handlers"""
    from server.tool_schemas import TOOL_SCHEMAS

    tools = [
        ToolDefinition(
            name="07_Analyze_Bookmarks",
            description="Analyze bookmarks in a PBIP report with HTML output",
            handler=handle_analyze_bookmarks,
            input_schema=TOOL_SCHEMAS.get('analyze_bookmarks', {}),
            category="pbip",
            sort_order=75  # 07 = PBIP Analysis
        ),
        ToolDefinition(
            name="07_Analyze_Theme_Compliance",
            description="Analyze theme compliance in a PBIP report with HTML output",
            handler=handle_theme_compliance,
            input_schema=TOOL_SCHEMAS.get('analyze_theme_compliance', {}),
            category="pbip",
            sort_order=76  # 07 = PBIP Analysis
        ),
    ]

    for tool in tools:
        registry.register(tool)

    logger.info(f"Registered {len(tools)} bookmark/theme handlers")
