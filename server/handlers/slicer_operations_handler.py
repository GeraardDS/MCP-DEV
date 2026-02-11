"""
Slicer Operations Handler
Tool 13: Configure Power BI slicer/visual settings in PBIP files

Operations:
- list: Find and list slicers matching criteria with their current configuration
- configure_single_select: Change slicer to single-select with "All" selected
- list_interactions: List visual interactions (cross-filtering settings) from page.json
- set_interaction: Set interaction type between two visuals on a page
- bulk_set_interactions: Set multiple interactions at once
"""
from typing import Dict, Any, List, Optional
import logging
from pathlib import Path
from server.registry import ToolDefinition
from core.utilities.pbip_utils import (
    normalize_path as _normalize_path,
    find_definition_folder as _find_definition_folder,
    load_json_file as _load_json_file,
    save_json_file as _save_json_file,
    get_page_display_name as _get_page_display_name,
)

logger = logging.getLogger(__name__)

# Visual types that are slicers (standard slicer + advanced/chiclet slicers)
SLICER_VISUAL_TYPES = {'slicer', 'advancedSlicerVisual'}


def _extract_slicer_info(visual_data: Dict, file_path: Path) -> Optional[Dict]:
    """Extract slicer information from visual.json"""
    visual = visual_data.get('visual', {})

    # Check if it's a slicer (standard or advanced/chiclet)
    visual_type = visual.get('visualType', '')
    if visual_type not in SLICER_VISUAL_TYPES:
        return None

    # Extract field information
    query_state = visual.get('query', {}).get('queryState', {})
    values_projections = query_state.get('Values', {}).get('projections', [])

    if not values_projections:
        return None

    field_info = values_projections[0].get('field', {})
    column_info = field_info.get('Column', {})

    if not column_info:
        return None

    entity = column_info.get('Expression', {}).get('SourceRef', {}).get('Entity', '')
    property_name = column_info.get('Property', '')

    # Get display name from various sources
    display_name = None

    # Try visualContainerObjects.title first
    vc_objects = visual.get('visualContainerObjects', {})
    title_config = vc_objects.get('title', [])
    if title_config and len(title_config) > 0:
        title_props = title_config[0].get('properties', {})
        title_text = title_props.get('text', {})
        if 'expr' in title_text:
            literal = title_text['expr'].get('Literal', {})
            display_name = literal.get('Value', '').strip("'")

    # Try projection displayName
    if not display_name:
        display_name = values_projections[0].get('displayName', '')

    # Try nativeQueryRef
    if not display_name:
        display_name = values_projections[0].get('nativeQueryRef', '')

    # Fallback to property name
    if not display_name:
        display_name = property_name

    # Get current selection mode
    objects = visual.get('objects', {})
    selection = objects.get('selection', [{}])
    selection_props = selection[0].get('properties', {}) if selection else {}

    data_config = objects.get('data', [{}])
    data_props = data_config[0].get('properties', {}) if data_config else {}

    # Check single select settings
    single_select = False
    strict_single_select = False
    select_all_checkbox = False
    is_inverted_selection = False

    if 'singleSelect' in selection_props:
        single_select = selection_props['singleSelect'].get('expr', {}).get('Literal', {}).get('Value', 'false') == 'true'

    if 'strictSingleSelect' in selection_props:
        strict_single_select = selection_props['strictSingleSelect'].get('expr', {}).get('Literal', {}).get('Value', 'false') == 'true'

    if 'selectAllCheckboxEnabled' in selection_props:
        select_all_checkbox = selection_props['selectAllCheckboxEnabled'].get('expr', {}).get('Literal', {}).get('Value', 'false') == 'true'

    if 'isInvertedSelectionMode' in data_props:
        is_inverted_selection = data_props['isInvertedSelectionMode'].get('expr', {}).get('Literal', {}).get('Value', 'false') == 'true'

    # Get current filter/selections
    general_config = objects.get('general', [{}])
    general_props = general_config[0].get('properties', {}) if general_config else {}

    current_filter = general_props.get('filter', {}).get('filter', {})
    selected_values = []

    if current_filter:
        where_clause = current_filter.get('Where', [])
        for condition in where_clause:
            in_clause = condition.get('Condition', {}).get('In', {})
            values = in_clause.get('Values', [])
            for value_list in values:
                for value_item in value_list:
                    literal = value_item.get('Literal', {})
                    val = literal.get('Value', '')
                    # Clean up the value
                    if val.startswith("'") and val.endswith("'"):
                        val = val[1:-1]
                    selected_values.append(val)

    # Determine selection mode string
    if is_inverted_selection and (single_select or strict_single_select):
        selection_mode = "single_select_all"  # Single select with "All" selected
    elif single_select or strict_single_select:
        selection_mode = "single_select"
    else:
        selection_mode = "multi_select"

    # Build relative path for readability
    try:
        rel_path = str(file_path.relative_to(file_path.parent.parent.parent.parent.parent))
    except ValueError:
        rel_path = str(file_path)

    # Limit selected_values to prevent large responses
    MAX_SELECTED_VALUES = 5
    total_selected_count = len(selected_values)
    limited_selected_values = selected_values[:MAX_SELECTED_VALUES]

    return {
        'file_path': str(file_path),
        'relative_path': rel_path,
        'visual_name': visual_data.get('name', ''),
        'display_name': display_name,
        'entity': entity,
        'property': property_name,
        'field_reference': f"{entity}[{property_name}]",
        'selection_mode': selection_mode,
        'single_select': single_select,
        'strict_single_select': strict_single_select,
        'select_all_checkbox': select_all_checkbox,
        'is_inverted_selection': is_inverted_selection,
        'selected_values': limited_selected_values,
        'selected_values_count': total_selected_count,
        'selected_values_truncated': total_selected_count > MAX_SELECTED_VALUES,
        'has_filter': bool(current_filter)
    }


def _find_slicers(definition_path: Path, display_name: Optional[str], entity: Optional[str], property_name: Optional[str]) -> List[Dict]:
    """Find all slicers matching the criteria"""
    matching_slicers = []

    # Search in pages folder
    pages_path = definition_path / "pages"
    if not pages_path.exists():
        return matching_slicers

    # Build page name cache for efficiency
    page_name_cache: Dict[str, str] = {}

    # Iterate through all pages
    for page_folder in pages_path.iterdir():
        if not page_folder.is_dir():
            continue

        # Get page display name (cached)
        page_id = page_folder.name
        if page_id not in page_name_cache:
            page_name_cache[page_id] = _get_page_display_name(page_folder)
        page_display_name = page_name_cache[page_id]

        visuals_path = page_folder / "visuals"
        if not visuals_path.exists():
            continue

        # Iterate through all visuals
        for visual_folder in visuals_path.iterdir():
            if not visual_folder.is_dir():
                continue

            visual_json_path = visual_folder / "visual.json"
            if not visual_json_path.exists():
                continue

            visual_data = _load_json_file(visual_json_path)
            if not visual_data:
                continue

            slicer_info = _extract_slicer_info(visual_data, visual_json_path)
            if not slicer_info:
                continue

            # Add page information
            slicer_info['page_id'] = page_id
            slicer_info['page_name'] = page_display_name

            # Apply filters
            matches = True

            if display_name:
                # Case-insensitive partial match on display name
                if display_name.lower() not in slicer_info['display_name'].lower():
                    matches = False

            if entity:
                # Case-insensitive match on entity
                if entity.lower() != slicer_info['entity'].lower():
                    matches = False

            if property_name:
                # Case-insensitive match on property
                if property_name.lower() != slicer_info['property'].lower():
                    matches = False

            if matches:
                matching_slicers.append(slicer_info)

    return matching_slicers


# ============================================
# Visual Interaction Helper Functions
# ============================================

def _get_visual_display_info(visuals_path: Path) -> Dict[str, Dict]:
    """
    Build a cache of visual name -> display info for all visuals on a page.
    Returns dict: {visual_name: {'display_title': str, 'visual_type': str}}
    """
    visual_info_cache: Dict[str, Dict] = {}

    if not visuals_path.exists():
        return visual_info_cache

    for visual_folder in visuals_path.iterdir():
        if not visual_folder.is_dir():
            continue

        visual_json_path = visual_folder / "visual.json"
        if not visual_json_path.exists():
            continue

        visual_data = _load_json_file(visual_json_path)
        if not visual_data:
            continue

        visual_name = visual_data.get('name', visual_folder.name)
        visual_type = visual_data.get('visual', {}).get('visualType', 'unknown')

        # Get display title
        display_title = None
        vc_objects = visual_data.get('visual', {}).get('visualContainerObjects', {})
        title_config = vc_objects.get('title', [])
        if title_config and len(title_config) > 0:
            title_props = title_config[0].get('properties', {})
            title_text = title_props.get('text', {})
            if 'expr' in title_text:
                literal = title_text['expr'].get('Literal', {})
                value = literal.get('Value', '')
                if value.startswith("'") and value.endswith("'"):
                    display_title = value[1:-1]
                else:
                    display_title = value

        visual_info_cache[visual_name] = {
            'display_title': display_title or visual_name,
            'visual_type': visual_type
        }

    return visual_info_cache


def _get_page_interactions(page_folder: Path) -> List[Dict]:
    """
    Get visual interactions from a page's page.json file.
    Returns list of interaction dicts with source, target, type.
    """
    page_json_path = page_folder / "page.json"
    if not page_json_path.exists():
        return []

    page_data = _load_json_file(page_json_path)
    if not page_data:
        return []

    return page_data.get('visualInteractions', [])


def _set_page_interactions(page_folder: Path, interactions: List[Dict]) -> bool:
    """
    Set visual interactions in a page's page.json file.
    Returns True if successful.
    """
    page_json_path = page_folder / "page.json"
    if not page_json_path.exists():
        return False

    page_data = _load_json_file(page_json_path)
    if not page_data:
        return False

    page_data['visualInteractions'] = interactions
    return _save_json_file(page_json_path, page_data)


def _find_interactions(
    definition_path: Path,
    page_name: Optional[str] = None,
    source_visual: Optional[str] = None,
    target_visual: Optional[str] = None,
    interaction_type: Optional[str] = None,
    include_visual_info: bool = True
) -> Dict[str, Any]:
    """
    Find visual interactions across all pages matching criteria.

    Args:
        definition_path: Path to PBIP definition folder
        page_name: Filter by page name (case-insensitive partial match)
        source_visual: Filter by source visual name or display title
        target_visual: Filter by target visual name or display title
        interaction_type: Filter by interaction type (NoFilter, Filter, Highlight)
        include_visual_info: Include visual display titles in results

    Returns:
        Dict with pages and their interactions
    """
    pages_path = definition_path / "pages"
    if not pages_path.exists():
        return {'pages': [], 'total_interactions': 0}

    result_pages = []
    total_interactions = 0

    for page_folder in pages_path.iterdir():
        if not page_folder.is_dir():
            continue

        # Skip if filtering by page name and no match
        page_id = page_folder.name
        page_display_name = _get_page_display_name(page_folder)

        if page_name and page_name.lower() not in page_display_name.lower():
            continue

        # Get interactions for this page
        interactions = _get_page_interactions(page_folder)
        if not interactions:
            continue

        # Build visual info cache if needed for filtering or display
        visual_info_cache: Dict[str, Dict] = {}
        if include_visual_info or source_visual or target_visual:
            visuals_path = page_folder / "visuals"
            visual_info_cache = _get_visual_display_info(visuals_path)

        # Filter and enrich interactions
        filtered_interactions = []
        for interaction in interactions:
            source_id = interaction.get('source', '')
            target_id = interaction.get('target', '')
            int_type = interaction.get('type', '')

            # Apply filters
            if interaction_type and int_type.lower() != interaction_type.lower():
                continue

            # Filter by source visual
            if source_visual:
                source_info = visual_info_cache.get(source_id, {})
                source_title = source_info.get('display_title', source_id)
                if (source_visual.lower() not in source_id.lower() and
                    source_visual.lower() not in source_title.lower()):
                    continue

            # Filter by target visual
            if target_visual:
                target_info = visual_info_cache.get(target_id, {})
                target_title = target_info.get('display_title', target_id)
                if (target_visual.lower() not in target_id.lower() and
                    target_visual.lower() not in target_title.lower()):
                    continue

            # Build interaction record
            int_record: Dict[str, Any] = {
                'source': source_id,
                'target': target_id,
                'type': int_type
            }

            # Add visual info if requested
            if include_visual_info:
                source_info = visual_info_cache.get(source_id, {})
                target_info = visual_info_cache.get(target_id, {})
                int_record['source_title'] = source_info.get('display_title', source_id)
                int_record['source_type'] = source_info.get('visual_type', 'unknown')
                int_record['target_title'] = target_info.get('display_title', target_id)
                int_record['target_type'] = target_info.get('visual_type', 'unknown')

            filtered_interactions.append(int_record)

        if filtered_interactions:
            result_pages.append({
                'page_id': page_id,
                'page_name': page_display_name,
                'interactions': filtered_interactions,
                'interaction_count': len(filtered_interactions)
            })
            total_interactions += len(filtered_interactions)

    return {
        'pages': result_pages,
        'total_interactions': total_interactions,
        'page_count': len(result_pages)
    }


def _set_interaction(
    definition_path: Path,
    page_name: str,
    source_visual: str,
    target_visual: str,
    interaction_type: str
) -> Dict[str, Any]:
    """
    Set an interaction between two visuals on a page.

    Args:
        definition_path: Path to PBIP definition folder
        page_name: Page name to modify (case-insensitive partial match)
        source_visual: Source visual name/ID
        target_visual: Target visual name/ID
        interaction_type: Interaction type (NoFilter, Filter, Highlight)

    Returns:
        Dict with success status and details
    """
    # Validate interaction type
    valid_types = {'NoFilter', 'Filter', 'Highlight'}
    if interaction_type not in valid_types:
        return {
            'success': False,
            'error': f'Invalid interaction_type: {interaction_type}. Must be one of: {", ".join(valid_types)}'
        }

    pages_path = definition_path / "pages"
    if not pages_path.exists():
        return {'success': False, 'error': 'No pages folder found'}

    # Find matching page
    matching_page = None
    for page_folder in pages_path.iterdir():
        if not page_folder.is_dir():
            continue

        page_display_name = _get_page_display_name(page_folder)
        if page_name.lower() in page_display_name.lower():
            matching_page = page_folder
            break

    if not matching_page:
        return {'success': False, 'error': f'No page found matching: {page_name}'}

    # Verify visuals exist on page
    visuals_path = matching_page / "visuals"
    visual_info_cache = _get_visual_display_info(visuals_path)

    # Resolve visual names (could be display title or ID)
    source_id = None
    target_id = None

    for visual_id, info in visual_info_cache.items():
        if visual_id == source_visual or info.get('display_title', '').lower() == source_visual.lower():
            source_id = visual_id
        if visual_id == target_visual or info.get('display_title', '').lower() == target_visual.lower():
            target_id = visual_id

    if not source_id:
        return {'success': False, 'error': f'Source visual not found: {source_visual}'}
    if not target_id:
        return {'success': False, 'error': f'Target visual not found: {target_visual}'}

    # Get current interactions
    interactions = _get_page_interactions(matching_page)

    # Find and update or add interaction
    found = False
    for interaction in interactions:
        if interaction.get('source') == source_id and interaction.get('target') == target_id:
            old_type = interaction.get('type')
            interaction['type'] = interaction_type
            found = True
            break

    if not found:
        interactions.append({
            'source': source_id,
            'target': target_id,
            'type': interaction_type
        })

    # Save updated interactions
    if _set_page_interactions(matching_page, interactions):
        return {
            'success': True,
            'page_name': _get_page_display_name(matching_page),
            'source_visual': source_id,
            'target_visual': target_id,
            'interaction_type': interaction_type,
            'action': 'updated' if found else 'added'
        }
    else:
        return {'success': False, 'error': 'Failed to save page.json'}


def _bulk_set_interactions(
    definition_path: Path,
    page_name: str,
    interactions: List[Dict[str, str]],
    replace_all: bool = False
) -> Dict[str, Any]:
    """
    Set multiple interactions at once on a page.

    Args:
        definition_path: Path to PBIP definition folder
        page_name: Page name to modify
        interactions: List of {source, target, type} dicts
        replace_all: If True, replace all existing interactions. If False, merge/update.

    Returns:
        Dict with success status and details
    """
    valid_types = {'NoFilter', 'Filter', 'Highlight'}

    pages_path = definition_path / "pages"
    if not pages_path.exists():
        return {'success': False, 'error': 'No pages folder found'}

    # Find matching page
    matching_page = None
    for page_folder in pages_path.iterdir():
        if not page_folder.is_dir():
            continue
        page_display_name = _get_page_display_name(page_folder)
        if page_name.lower() in page_display_name.lower():
            matching_page = page_folder
            break

    if not matching_page:
        return {'success': False, 'error': f'No page found matching: {page_name}'}

    # Get visual info for name resolution
    visuals_path = matching_page / "visuals"
    visual_info_cache = _get_visual_display_info(visuals_path)

    # Resolve and validate interactions
    resolved_interactions = []
    errors = []

    for i, int_spec in enumerate(interactions):
        source = int_spec.get('source', '')
        target = int_spec.get('target', '')
        int_type = int_spec.get('type', '')

        if int_type not in valid_types:
            errors.append(f'Interaction {i}: Invalid type "{int_type}"')
            continue

        # Resolve source
        source_id = None
        for visual_id, info in visual_info_cache.items():
            if visual_id == source or info.get('display_title', '').lower() == source.lower():
                source_id = visual_id
                break

        if not source_id:
            errors.append(f'Interaction {i}: Source visual not found: {source}')
            continue

        # Resolve target
        target_id = None
        for visual_id, info in visual_info_cache.items():
            if visual_id == target or info.get('display_title', '').lower() == target.lower():
                target_id = visual_id
                break

        if not target_id:
            errors.append(f'Interaction {i}: Target visual not found: {target}')
            continue

        resolved_interactions.append({
            'source': source_id,
            'target': target_id,
            'type': int_type
        })

    if errors and not resolved_interactions:
        return {'success': False, 'errors': errors}

    # Get current interactions (if merging)
    if replace_all:
        final_interactions = resolved_interactions
    else:
        current_interactions = _get_page_interactions(matching_page)

        # Build lookup for efficient merge
        interaction_lookup = {}
        for interaction in current_interactions:
            key = f"{interaction.get('source')}|{interaction.get('target')}"
            interaction_lookup[key] = interaction

        # Update/add resolved interactions
        for interaction in resolved_interactions:
            key = f"{interaction['source']}|{interaction['target']}"
            interaction_lookup[key] = interaction

        final_interactions = list(interaction_lookup.values())

    # Save
    if _set_page_interactions(matching_page, final_interactions):
        result = {
            'success': True,
            'page_name': _get_page_display_name(matching_page),
            'interactions_set': len(resolved_interactions),
            'total_interactions': len(final_interactions),
            'replace_mode': replace_all
        }
        if errors:
            result['warnings'] = errors
        return result
    else:
        return {'success': False, 'error': 'Failed to save page.json'}


def _configure_single_select_all(visual_data: Dict) -> Dict:
    """
    Configure a slicer for single-select with "All" selected.

    Changes made:
    1. Set selection.singleSelect = true
    2. Set selection.strictSingleSelect = true
    3. Set selection.selectAllCheckboxEnabled = true
    4. Set data.isInvertedSelectionMode = true
    5. Remove any filter from general properties
    """
    visual = visual_data.get('visual', {})
    objects = visual.setdefault('objects', {})

    # Configure selection properties
    selection = objects.setdefault('selection', [{'properties': {}}])
    if not selection:
        selection = [{'properties': {}}]
        objects['selection'] = selection

    selection_props = selection[0].setdefault('properties', {})

    # Set single select options
    selection_props['strictSingleSelect'] = {
        'expr': {
            'Literal': {
                'Value': 'true'
            }
        }
    }
    selection_props['selectAllCheckboxEnabled'] = {
        'expr': {
            'Literal': {
                'Value': 'true'
            }
        }
    }
    selection_props['singleSelect'] = {
        'expr': {
            'Literal': {
                'Value': 'true'
            }
        }
    }

    # Configure data properties for inverted selection mode
    data = objects.setdefault('data', [{'properties': {}}])
    if not data:
        data = [{'properties': {}}]
        objects['data'] = data

    data_props = data[0].setdefault('properties', {})

    # Set inverted selection mode (means "All" is selected)
    data_props['isInvertedSelectionMode'] = {
        'expr': {
            'Literal': {
                'Value': 'true'
            }
        }
    }

    # Remove any existing filter from general properties
    general = objects.get('general', [])
    if general and len(general) > 0:
        general_props = general[0].get('properties', {})
        if 'filter' in general_props:
            del general_props['filter']

    return visual_data


def _op_list_slicers(args: Dict[str, Any], definition_path: Path,
                     display_name, entity, property_name) -> Dict[str, Any]:
    """List slicers with their current configuration."""
    slicers = _find_slicers(definition_path, display_name, entity, property_name)

    if not slicers:
        return {
            'success': True,
            'message': 'No slicers found matching the criteria',
            'slicers': [],
            'count': 0
        }

    summary_only = args.get('summary_only', True)

    if summary_only:
        condensed_slicers = []
        for slicer in slicers:
            condensed = {
                'display_name': slicer['display_name'],
                'page_name': slicer.get('page_name', ''),
                'field_reference': slicer['field_reference'],
                'selection_mode': slicer['selection_mode'],
                'visual_name': slicer['visual_name']
            }
            if slicer.get('selected_values_count', 0) > 0:
                condensed['selected_count'] = slicer['selected_values_count']
            condensed_slicers.append(condensed)

        return {
            'success': True,
            'slicers': condensed_slicers,
            'count': len(slicers),
            'hint': 'Use summary_only=false for full details including file paths'
        }

    return {
        'success': True,
        'message': f'Found {len(slicers)} slicer(s) matching criteria',
        'slicers': slicers,
        'count': len(slicers)
    }


def _op_configure_single_select(args: Dict[str, Any], definition_path: Path,
                                display_name, entity, property_name) -> Dict[str, Any]:
    """Configure slicers for single-select mode."""
    slicers = _find_slicers(definition_path, display_name, entity, property_name)

    if not slicers:
        return {
            'success': False,
            'error': 'No slicers found matching the criteria. Use operation "list" to see available slicers.'
        }

    dry_run = args.get('dry_run', False)
    changes = []
    errors = []

    for slicer in slicers:
        file_path = Path(slicer['file_path'])
        before_mode = slicer['selection_mode']

        if dry_run:
            status = 'would_change' if before_mode != 'single_select_all' else 'already_configured'
            changes.append({
                'display_name': slicer['display_name'],
                'page_name': slicer.get('page_name', ''),
                'field_reference': slicer['field_reference'],
                'before_mode': before_mode,
                'after_mode': 'single_select_all',
                'status': status
            })
        else:
            visual_data = _load_json_file(file_path)
            if not visual_data:
                errors.append({'file_path': str(file_path), 'error': 'Failed to load visual.json'})
                continue

            modified_data = _configure_single_select_all(visual_data)

            if _save_json_file(file_path, modified_data):
                changes.append({
                    'display_name': slicer['display_name'],
                    'page_name': slicer.get('page_name', ''),
                    'field_reference': slicer['field_reference'],
                    'before_mode': before_mode,
                    'after_mode': 'single_select_all',
                    'status': 'changed'
                })
            else:
                errors.append({'file_path': str(file_path), 'error': 'Failed to save changes'})

    result = {
        'success': len(errors) == 0,
        'operation': 'configure_single_select',
        'dry_run': dry_run,
        'message': f'{"Would modify" if dry_run else "Modified"} {len(changes)} slicer(s)',
        'changes': changes,
        'changes_count': len(changes)
    }

    if errors:
        result['errors'] = errors
        result['errors_count'] = len(errors)
        result['message'] += f' with {len(errors)} error(s)'

    return result


def _op_list_interactions(args: Dict[str, Any], definition_path: Path) -> Dict[str, Any]:
    """List visual interactions from page.json files."""
    result = _find_interactions(
        definition_path,
        page_name=args.get('page_name'),
        source_visual=args.get('source_visual'),
        target_visual=args.get('target_visual'),
        interaction_type=args.get('interaction_type'),
        include_visual_info=args.get('include_visual_info', True)
    )

    if result['total_interactions'] == 0:
        return {
            'success': True,
            'message': 'No visual interactions found matching the criteria',
            'pages': [],
            'total_interactions': 0,
            'hint': 'Visual interactions define cross-filtering behavior. Default behavior is "Filter" - NoFilter/Highlight are only stored when explicitly set.'
        }

    summary_only = args.get('summary_only', True)
    if summary_only:
        summary_pages = []
        for page in result['pages']:
            type_counts = {}
            for interaction in page['interactions']:
                int_type = interaction.get('type', 'Unknown')
                type_counts[int_type] = type_counts.get(int_type, 0) + 1

            summary_pages.append({
                'page_name': page['page_name'],
                'interaction_count': page['interaction_count'],
                'by_type': type_counts,
            })

        return {
            'success': True,
            'pages': summary_pages,
            'total_interactions': result['total_interactions'],
            'page_count': result['page_count'],
            'hint': 'Use page_name filter and summary_only=false to see individual interactions'
        }

    MAX_INTERACTIONS_PER_PAGE = 25
    capped_pages = []
    for page in result['pages']:
        page_copy = dict(page)
        if len(page_copy['interactions']) > MAX_INTERACTIONS_PER_PAGE:
            page_copy['interactions'] = page_copy['interactions'][:MAX_INTERACTIONS_PER_PAGE]
            page_copy['truncated'] = True
        capped_pages.append(page_copy)

    return {
        'success': True,
        'pages': capped_pages,
        'total_interactions': result['total_interactions'],
        'page_count': result['page_count']
    }


def _op_set_interaction(args: Dict[str, Any], definition_path: Path) -> Dict[str, Any]:
    """Set a single interaction between two visuals."""
    page_name_param = args.get('page_name')
    source_visual = args.get('source_visual')
    target_visual = args.get('target_visual')
    interaction_type = args.get('interaction_type')
    dry_run = args.get('dry_run', False)

    if not all([page_name_param, source_visual, target_visual, interaction_type]):
        return {
            'success': False,
            'error': 'set_interaction requires: page_name, source_visual, target_visual, interaction_type'
        }

    if dry_run:
        return {
            'success': True,
            'dry_run': True,
            'message': f'Would set interaction: {source_visual} -> {target_visual} = {interaction_type} on page matching "{page_name_param}"'
        }

    return _set_interaction(
        definition_path,
        page_name=page_name_param,
        source_visual=source_visual,
        target_visual=target_visual,
        interaction_type=interaction_type
    )


def _op_bulk_set_interactions(args: Dict[str, Any], definition_path: Path) -> Dict[str, Any]:
    """Set multiple interactions at once."""
    page_name_param = args.get('page_name')
    interactions_list = args.get('interactions', [])
    replace_all = args.get('replace_all', False)
    dry_run = args.get('dry_run', False)

    if not page_name_param:
        return {'success': False, 'error': 'bulk_set_interactions requires: page_name'}

    if not interactions_list:
        return {'success': False, 'error': 'bulk_set_interactions requires: interactions (array of {source, target, type})'}

    if dry_run:
        return {
            'success': True,
            'dry_run': True,
            'message': f'Would set {len(interactions_list)} interaction(s) on page matching "{page_name_param}"',
            'replace_all': replace_all,
            'interactions_preview': interactions_list[:5] if len(interactions_list) > 5 else interactions_list
        }

    return _bulk_set_interactions(
        definition_path,
        page_name=page_name_param,
        interactions=interactions_list,
        replace_all=replace_all
    )


def handle_slicer_operations(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle slicer configuration operations - dispatches to per-operation functions."""
    operation = args.get('operation', 'list')
    pbip_path = args.get('pbip_path')

    if not pbip_path:
        return {
            'success': False,
            'error': 'pbip_path parameter is required - path to PBIP project, .Report folder, or definition folder'
        }

    definition_path = _find_definition_folder(pbip_path)
    if not definition_path:
        return {
            'success': False,
            'error': f'Could not find definition folder in: {pbip_path}. Ensure path points to a valid PBIP project.'
        }

    display_name = args.get('display_name')
    entity = args.get('entity')
    property_name = args.get('property')

    if operation == 'list':
        return _op_list_slicers(args, definition_path, display_name, entity, property_name)
    elif operation == 'configure_single_select':
        return _op_configure_single_select(args, definition_path, display_name, entity, property_name)
    elif operation == 'list_interactions':
        return _op_list_interactions(args, definition_path)
    elif operation == 'set_interaction':
        return _op_set_interaction(args, definition_path)
    elif operation == 'bulk_set_interactions':
        return _op_bulk_set_interactions(args, definition_path)

    return {
        'success': False,
        'error': f'Unknown operation: {operation}. Valid operations: list, configure_single_select, list_interactions, set_interaction, bulk_set_interactions'
    }


def register_slicer_operations_handler(registry):
    """Register slicer operations handler"""
    from server.tool_schemas import TOOL_SCHEMAS

    tool = ToolDefinition(
        name="07_Slicer_Operations",
        description="[PBIP] Configure Power BI slicer settings and visual interactions - list slicers, configure single-select, list/set cross-filtering interactions between visuals",
        handler=handle_slicer_operations,
        input_schema=TOOL_SCHEMAS.get('slicer_operations', {}),
        category="pbip",
        sort_order=73  # 07 = PBIP Analysis
    )
    registry.register(tool)

    logger.info("Registered slicer_operations handler")
