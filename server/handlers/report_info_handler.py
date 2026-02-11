"""
Report Info Handler
Tool 14: Get PBIP report structure information

Returns pure data about:
- All pages in the report
- Filters on all pages (report-level filters from report.json)
- Filter pane filters per page
- All visual items per page
"""
from typing import Dict, Any, List, Optional
import logging
import json
import os
import re
from pathlib import Path
from server.registry import ToolDefinition
from core.validation.error_handler import ErrorHandler

logger = logging.getLogger(__name__)


def _normalize_path(path: str) -> str:
    """Normalize path to handle Unix-style paths on Windows"""
    normalized_path = path

    # Convert WSL/Unix paths to Windows paths on Windows systems
    if re.match(r'^/mnt/([a-z])/', path, re.IGNORECASE):
        drive_letter = re.match(r'^/mnt/([a-z])/', path, re.IGNORECASE).group(1)
        rest_of_path = path[7:].replace('/', '\\')
        normalized_path = f"{drive_letter.upper()}:\\{rest_of_path}"
    elif path.startswith('/'):
        normalized_path = path.replace('/', '\\')

    return normalized_path


def _find_definition_folder(pbip_path: str) -> Optional[Path]:
    """Find the definition folder for a PBIP project"""
    path = Path(_normalize_path(pbip_path))

    if not path.exists():
        return None

    # If it's a .pbip file, look for .Report folder
    if path.is_file() and path.suffix == '.pbip':
        # Look for {name}.Report folder
        report_folder = path.parent / f"{path.stem}.Report"
        if report_folder.exists():
            definition = report_folder / "definition"
            if definition.exists():
                return definition

    # If it's a .Report folder
    if path.is_dir() and path.name.endswith('.Report'):
        definition = path / "definition"
        if definition.exists():
            return definition

    # If it's already a definition folder
    if path.is_dir() and path.name == "definition":
        return path

    # If it's a directory, search for .Report folders
    if path.is_dir():
        for item in path.iterdir():
            if item.is_dir() and item.name.endswith('.Report'):
                definition = item / "definition"
                if definition.exists():
                    return definition
        # Also check if definition exists directly
        definition = path / "definition"
        if definition.exists():
            return definition

    return None


def _load_json_file(file_path: Path) -> Optional[Dict]:
    """Load JSON file safely"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load JSON from {file_path}: {e}")
        return None


def _extract_field_reference(field_data: Dict) -> Optional[Dict]:
    """Extract field reference from a field definition"""
    result = {}

    # Handle Column reference
    if 'Column' in field_data:
        column = field_data['Column']
        entity = column.get('Expression', {}).get('SourceRef', {}).get('Entity', '')
        property_name = column.get('Property', '')
        result = {
            'type': 'column',
            'entity': entity,
            'property': property_name,
            'reference': f"{entity}[{property_name}]"
        }
    # Handle Measure reference
    elif 'Measure' in field_data:
        measure = field_data['Measure']
        entity = measure.get('Expression', {}).get('SourceRef', {}).get('Entity', '')
        property_name = measure.get('Property', '')
        result = {
            'type': 'measure',
            'entity': entity,
            'property': property_name,
            'reference': f"[{property_name}]"
        }
    # Handle Aggregation
    elif 'Aggregation' in field_data:
        agg = field_data['Aggregation']
        expression = agg.get('Expression', {})
        if 'Column' in expression:
            column = expression['Column']
            entity = column.get('Expression', {}).get('SourceRef', {}).get('Entity', '')
            property_name = column.get('Property', '')
            agg_func = agg.get('Function', 0)
            agg_names = {0: 'Sum', 1: 'Avg', 2: 'Min', 3: 'Max', 4: 'Count', 5: 'CountDistinct'}
            result = {
                'type': 'aggregation',
                'entity': entity,
                'property': property_name,
                'function': agg_names.get(agg_func, str(agg_func)),
                'reference': f"{agg_names.get(agg_func, 'Agg')}({entity}[{property_name}])"
            }
    # Handle HierarchyLevel
    elif 'HierarchyLevel' in field_data:
        hier = field_data['HierarchyLevel']
        entity = hier.get('Expression', {}).get('Hierarchy', {}).get('Expression', {}).get('SourceRef', {}).get('Entity', '')
        hierarchy = hier.get('Expression', {}).get('Hierarchy', {}).get('Hierarchy', '')
        level = hier.get('Level', '')
        result = {
            'type': 'hierarchy_level',
            'entity': entity,
            'hierarchy': hierarchy,
            'level': level,
            'reference': f"{entity}[{hierarchy}].[{level}]"
        }

    return result if result else None


def _extract_filter_values(filter_data: Dict) -> List[str]:
    """Extract filter values from filter definition"""
    values = []

    where_clause = filter_data.get('Where', [])
    for condition in where_clause:
        in_clause = condition.get('Condition', {}).get('In', {})
        filter_values = in_clause.get('Values', [])
        for value_list in filter_values:
            for value_item in value_list:
                literal = value_item.get('Literal', {})
                val = literal.get('Value', '')
                # Clean up the value
                if isinstance(val, str):
                    if val.startswith("'") and val.endswith("'"):
                        val = val[1:-1]
                values.append(val)

    return values


def _extract_filters_from_config(filter_config: Dict) -> List[Dict]:
    """Extract filters from a filterConfig structure (used in both report.json and page.json)"""
    filters = []

    page_filters = filter_config.get('filters', [])

    for flt in page_filters:
        filter_info = {
            'name': flt.get('name', ''),
            'type': flt.get('type', ''),
            'how_created': flt.get('howCreated', '')
        }

        # Check for ordinal (report-level filters have this)
        if 'ordinal' in flt:
            filter_info['ordinal'] = flt.get('ordinal')

        # Extract field reference
        field = flt.get('field', {})
        field_ref = _extract_field_reference(field)
        if field_ref:
            filter_info['field'] = field_ref

        # Extract filter values
        filter_def = flt.get('filter', {})
        if filter_def:
            filter_info['values'] = _extract_filter_values(filter_def)
        else:
            # No filter applied means "All" is selected
            filter_info['values'] = ['(All)']

        # Check for additional settings
        objects = flt.get('objects', {})
        general = objects.get('general', [])
        if general and len(general) > 0:
            props = general[0].get('properties', {})
            # Check for inverted selection mode
            if 'isInvertedSelectionMode' in props:
                expr = props['isInvertedSelectionMode'].get('expr', {})
                literal = expr.get('Literal', {})
                if literal.get('Value') == 'true':
                    filter_info['is_inverted'] = True
            # Check for single select requirement
            if 'requireSingleSelect' in props:
                expr = props['requireSingleSelect'].get('expr', {})
                literal = expr.get('Literal', {})
                if literal.get('Value') == 'true':
                    filter_info['single_select'] = True

        filters.append(filter_info)

    return filters


def _extract_page_filters(page_data: Dict) -> List[Dict]:
    """Extract filter pane filters from page.json"""
    filter_config = page_data.get('filterConfig', {})
    return _extract_filters_from_config(filter_config)


def _extract_report_filters(report_data: Dict) -> List[Dict]:
    """Extract 'Filters on all pages' from report.json"""
    filter_config = report_data.get('filterConfig', {})
    return _extract_filters_from_config(filter_config)


def _extract_visual_info(visual_data: Dict, visual_path: Path) -> Dict:
    """Extract information about a visual"""
    visual = visual_data.get('visual', {})
    visual_group = visual_data.get('visualGroup', {})

    result = {
        'name': visual_data.get('name', ''),
        'position': visual_data.get('position', {}),
        'is_hidden': visual_data.get('isHidden', False),
        'parent_group': visual_data.get('parentGroupName', None)
    }

    # Visual type and query info
    if visual:
        result['visual_type'] = visual.get('visualType', '')

        # Get title if available
        vc_objects = visual.get('visualContainerObjects', {})
        title_config = vc_objects.get('title', [])
        if title_config and len(title_config) > 0:
            title_props = title_config[0].get('properties', {})
            title_text = title_props.get('text', {})
            if 'expr' in title_text:
                literal = title_text['expr'].get('Literal', {})
                title = literal.get('Value', '').strip("'")
                result['title'] = title

        # Extract fields used in the visual
        query = visual.get('query', {})
        query_state = query.get('queryState', {})

        fields = []
        for bucket_name, bucket_data in query_state.items():
            projections = bucket_data.get('projections', [])
            for proj in projections:
                field_data = proj.get('field', {})
                field_ref = _extract_field_reference(field_data)
                if field_ref:
                    field_info = {
                        'bucket': bucket_name,
                        'display_name': proj.get('displayName', proj.get('nativeQueryRef', '')),
                        'query_ref': proj.get('queryRef', ''),
                        **field_ref
                    }
                    fields.append(field_info)

        if fields:
            result['fields'] = fields

        # Check for sync group (slicers)
        sync_group = visual.get('syncGroup', {})
        if sync_group:
            result['sync_group'] = sync_group.get('groupName', '')

    # Visual group info
    if visual_group:
        result['is_group'] = True
        result['group_display_name'] = visual_group.get('displayName', '')
        result['group_mode'] = visual_group.get('groupMode', '')

    return result


def _get_page_display_name(page_folder: Path) -> Optional[str]:
    """Get just the display name from page.json without loading visuals.
    Used for early filtering by page name to avoid loading visual JSON files."""
    page_json_path = page_folder / "page.json"
    if not page_json_path.exists():
        return None
    page_data = _load_json_file(page_json_path)
    if not page_data:
        return None
    return page_data.get('displayName', page_folder.name)


def _summarize_visual(visual_info: Dict) -> Dict:
    """Create a compact summary of a visual for summary_only mode."""
    summary = {
        'name': visual_info.get('name', ''),
        'visual_type': visual_info.get('visual_type', ''),
    }
    if visual_info.get('title'):
        summary['title'] = visual_info['title']
    if visual_info.get('is_hidden'):
        summary['is_hidden'] = True
    if visual_info.get('is_group'):
        summary['is_group'] = True
        if visual_info.get('group_display_name'):
            summary['group_display_name'] = visual_info['group_display_name']
    if visual_info.get('sync_group'):
        summary['sync_group'] = visual_info['sync_group']
    # Flatten fields to compact strings: "bucket: reference"
    fields = visual_info.get('fields', [])
    if fields:
        summary['fields'] = [
            f"{f.get('bucket', '?')}: {f.get('reference', f.get('display_name', '?'))}"
            for f in fields
        ]
    return summary


def _summarize_filter(filter_info: Dict) -> Dict:
    """Create a compact summary of a filter for summary_only mode."""
    MAX_FILTER_VALUES = 10
    ref = filter_info.get('field', {}).get('reference', filter_info.get('name', '?'))
    summary = {'field': ref, 'type': filter_info.get('type', '')}
    values = filter_info.get('values', [])
    if values and values != ['(All)']:
        if len(values) > MAX_FILTER_VALUES:
            summary['values'] = values[:MAX_FILTER_VALUES]
            summary['values_truncated'] = len(values)
        else:
            summary['values'] = values
    if filter_info.get('is_inverted'):
        summary['is_inverted'] = True
    return summary


def _get_page_info(page_folder: Path, summary_only: bool = False) -> Dict:
    """Get complete information for a page.

    Args:
        page_folder: Path to the page folder
        summary_only: If True, return compact visual/filter info to reduce token usage
    """
    page_json_path = page_folder / "page.json"
    if not page_json_path.exists():
        return None

    page_data = _load_json_file(page_json_path)
    if not page_data:
        return None

    page_info = {
        'page_id': page_folder.name,
        'display_name': page_data.get('displayName', page_folder.name),
    }

    if not summary_only:
        page_info['display_option'] = page_data.get('displayOption', '')
        page_info['width'] = page_data.get('width', 0)
        page_info['height'] = page_data.get('height', 0)

    # Extract filter pane filters
    filters = _extract_page_filters(page_data)
    if summary_only:
        page_info['filter_pane_filters'] = [_summarize_filter(f) for f in filters]
    else:
        page_info['filter_pane_filters'] = filters
    page_info['filter_count'] = len(filters)

    # Extract visuals
    visuals = []
    visuals_path = page_folder / "visuals"

    if visuals_path.exists():
        for visual_folder in visuals_path.iterdir():
            if not visual_folder.is_dir():
                continue

            visual_json_path = visual_folder / "visual.json"
            if not visual_json_path.exists():
                continue

            visual_data = _load_json_file(visual_json_path)
            if not visual_data:
                continue

            visual_info = _extract_visual_info(visual_data, visual_json_path)
            visuals.append(visual_info)

    if summary_only:
        page_info['visuals'] = [_summarize_visual(v) for v in visuals]
    else:
        page_info['visuals'] = visuals
    page_info['visual_count'] = len(visuals)

    return page_info


def handle_report_info(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle report info request"""
    pbip_path = args.get('pbip_path')
    include_visuals = args.get('include_visuals', True)
    include_filters = args.get('include_filters', True)
    page_filter = args.get('page_name', None)
    summary_only = args.get('summary_only', True)
    max_visuals_per_page = args.get('max_visuals_per_page', 50)

    if not pbip_path:
        return {
            'success': False,
            'error': 'pbip_path parameter is required - path to PBIP project, .Report folder, or definition folder'
        }

    # Find definition folder
    definition_path = _find_definition_folder(pbip_path)
    if not definition_path:
        return {
            'success': False,
            'error': f'Could not find definition folder in: {pbip_path}. Ensure path points to a valid PBIP project.'
        }

    # Get pages folder
    pages_path = definition_path / "pages"
    if not pages_path.exists():
        return {
            'success': False,
            'error': f'No pages folder found in: {definition_path}'
        }

    # Load report.json for "Filters on all pages"
    report_json_path = definition_path / "report.json"
    report_level_filters = []
    if report_json_path.exists():
        report_data = _load_json_file(report_json_path)
        if report_data:
            report_level_filters = _extract_report_filters(report_data)

    # Collect page information
    pages = []
    total_visuals = 0
    total_filters = 0
    visual_type_counts = {}

    for page_folder in pages_path.iterdir():
        if not page_folder.is_dir():
            continue

        # Early filter: check display name before loading visuals
        if page_filter:
            display_name = _get_page_display_name(page_folder)
            if not display_name or page_filter.lower() not in display_name.lower():
                continue

        page_info = _get_page_info(page_folder, summary_only=summary_only)
        if not page_info:
            continue

        # Count statistics (use visual_count which is always present)
        total_visuals += page_info['visual_count']
        total_filters += page_info['filter_count']

        # Count visual types from visuals list (present in both modes)
        for visual in page_info.get('visuals', []):
            vtype = visual.get('visual_type', 'unknown')
            if vtype:
                visual_type_counts[vtype] = visual_type_counts.get(vtype, 0) + 1

        # Apply max_visuals_per_page cap (stats already counted above)
        if max_visuals_per_page > 0 and 'visuals' in page_info:
            visuals_list = page_info['visuals']
            if len(visuals_list) > max_visuals_per_page:
                page_info['visuals'] = visuals_list[:max_visuals_per_page]
                page_info['visuals_truncated'] = True

        # Optionally exclude visuals/filters from response
        if not include_visuals:
            page_info.pop('visuals', None)
        if not include_filters:
            page_info.pop('filter_pane_filters', None)

        pages.append(page_info)

    # Sort pages by display name
    pages.sort(key=lambda x: x.get('display_name', ''))

    # Summarize report-level filters if summary_only
    if summary_only and report_level_filters:
        report_level_filters = [_summarize_filter(f) for f in report_level_filters]

    result = {
        'success': True,
        'summary': {
            'total_pages': len(pages),
            'total_visuals': total_visuals,
            'total_filter_pane_filters': total_filters,
            'filters_on_all_pages_count': len(report_level_filters),
            'visual_types': visual_type_counts
        },
        'filters_on_all_pages': report_level_filters,
        'pages': pages
    }

    # Optionally exclude report-level filters
    if not include_filters:
        result.pop('filters_on_all_pages', None)

    return result


def register_report_info_handler(registry):
    """Register report info handler"""
    from server.tool_schemas import TOOL_SCHEMAS

    tool = ToolDefinition(
        name="07_Report_Info",
        description="[PBIP] Get report structure info - all pages, filters on all pages, filter pane filters per page, and visual items per page",
        handler=handle_report_info,
        input_schema=TOOL_SCHEMAS.get('report_info', {}),
        category="pbip",
        sort_order=71  # 07 = PBIP Analysis
    )
    registry.register(tool)

    logger.info("Registered report_info handler")
