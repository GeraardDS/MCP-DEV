"""
Visual Operations Handler
Tool: Configure Power BI visual properties in PBIP files

Operations:
- list: Find and list visuals matching criteria with their current configuration
- update_position: Update position and/or size of matching visuals
- replace_measure: Replace a measure in visuals while keeping the display name
- sync_visual: Sync a visual (including visual groups with children) from source page to matching visuals on other pages
- sync_column_widths: Sync only columnWidth settings from source matrix to target matrices (preserves all other visual properties)
- update_visual_config: Update visual formatting properties (axis settings, labels, colors, etc.)
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


MAX_PARENT_DEPTH = 50  # Safety limit to prevent infinite loops in parent traversal


def _get_parent_group_offset(visual_data: Dict, visuals_path: Path) -> Dict[str, float]:
    """
    Calculate the cumulative offset from all parent groups.

    Power BI stores visual positions relative to their parent group.
    This function walks up the parent chain and sums all offsets to get
    the total offset that needs to be added to get absolute position,
    or subtracted to convert absolute to relative.

    Returns: {'x': total_x_offset, 'y': total_y_offset}
    """
    total_x = 0.0
    total_y = 0.0

    parent_name = visual_data.get('parentGroupName')
    visited = set()  # Prevent infinite loops
    depth = 0

    while parent_name and parent_name not in visited and depth < MAX_PARENT_DEPTH:
        visited.add(parent_name)
        depth += 1

        # Find the parent group's visual.json
        parent_path = visuals_path / parent_name / "visual.json"
        if not parent_path.exists():
            break

        parent_data = _load_json_file(parent_path)
        if not parent_data:
            break

        # Add parent's position to total offset
        parent_position = parent_data.get('position', {})
        total_x += parent_position.get('x', 0)
        total_y += parent_position.get('y', 0)

        # Move to next parent
        parent_name = parent_data.get('parentGroupName')

    return {'x': total_x, 'y': total_y}


def _get_visual_title(visual_data: Dict) -> Optional[str]:
    """Extract the display title from visual.json"""
    visual = visual_data.get('visual', {})
    vc_objects = visual.get('visualContainerObjects', {})

    # Try to get title from visualContainerObjects
    title_config = vc_objects.get('title', [])
    if title_config and len(title_config) > 0:
        title_props = title_config[0].get('properties', {})
        title_text = title_props.get('text', {})
        if 'expr' in title_text:
            literal = title_text['expr'].get('Literal', {})
            value = literal.get('Value', '')
            # Remove surrounding quotes
            if value.startswith("'") and value.endswith("'"):
                return value[1:-1]
            return value

    return None


def _extract_visual_info(visual_data: Dict, file_path: Path, visuals_path: Path) -> Dict:
    """Extract visual information from visual.json

    Positions are returned as ABSOLUTE positions (as shown in Power BI UI),
    calculated by adding parent group offsets to the relative position stored in JSON.
    """
    visual = visual_data.get('visual', {})
    position = visual_data.get('position', {})

    # Get visual type
    visual_type = visual.get('visualType', 'unknown')

    # Get display title
    display_title = _get_visual_title(visual_data)

    # Get relative position and size (as stored in JSON)
    relative_x = position.get('x', 0)
    relative_y = position.get('y', 0)
    z = position.get('z', 0)
    height = position.get('height', 0)
    width = position.get('width', 0)
    tab_order = position.get('tabOrder', 0)

    # Calculate parent group offset
    parent_offset = _get_parent_group_offset(visual_data, visuals_path)

    # Calculate absolute position (as shown in Power BI UI)
    absolute_x = relative_x + parent_offset['x']
    absolute_y = relative_y + parent_offset['y']

    # Check visibility
    is_hidden = visual_data.get('isHidden', False)
    parent_group = visual_data.get('parentGroupName')

    return {
        'file_path': str(file_path),
        'visual_name': visual_data.get('name', ''),
        'display_title': display_title,
        'visual_type': visual_type,
        'position': {
            'x': absolute_x,  # Absolute position (as shown in Power BI)
            'y': absolute_y,  # Absolute position (as shown in Power BI)
            'z': z,
            'height': height,
            'width': width,
            'tab_order': tab_order
        },
        '_relative_position': {  # Internal: relative position as stored in JSON
            'x': relative_x,
            'y': relative_y
        },
        '_parent_offset': parent_offset,  # Internal: for position calculations
        'is_hidden': is_hidden,
        'parent_group': parent_group
    }


def _find_visuals(
    definition_path: Path,
    display_title: Optional[str] = None,
    visual_type: Optional[str] = None,
    visual_name: Optional[str] = None,
    page_name: Optional[str] = None,
    include_hidden: bool = True
) -> List[Dict]:
    """Find all visuals matching the criteria"""
    matching_visuals = []

    # Search in pages folder
    pages_path = definition_path / "pages"
    if not pages_path.exists():
        return matching_visuals

    # Iterate through all pages
    for page_folder in pages_path.iterdir():
        if not page_folder.is_dir():
            continue

        # Get page display name
        page_id = page_folder.name
        page_display_name = _get_page_display_name(page_folder)

        # Filter by page name if specified
        if page_name:
            if page_name.lower() not in page_display_name.lower():
                continue

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

            visual_info = _extract_visual_info(visual_data, visual_json_path, visuals_path)

            # Skip hidden visuals unless requested
            if not include_hidden and visual_info['is_hidden']:
                continue

            # Add page information
            visual_info['page_id'] = page_id
            visual_info['page_name'] = page_display_name

            # Apply filters
            matches = True

            if display_title:
                # Case-insensitive partial match on display title
                if not visual_info['display_title'] or display_title.lower() not in visual_info['display_title'].lower():
                    matches = False

            if visual_type:
                # Case-insensitive match on visual type
                if visual_type.lower() != visual_info['visual_type'].lower():
                    matches = False

            if visual_name:
                # Case-insensitive match on visual name (ID)
                if visual_name.lower() != visual_info['visual_name'].lower():
                    matches = False

            if matches:
                matching_visuals.append(visual_info)

    return matching_visuals


def _update_visual_position(
    visual_data: Dict,
    x: Optional[float] = None,
    y: Optional[float] = None,
    width: Optional[float] = None,
    height: Optional[float] = None,
    z: Optional[int] = None,
    parent_offset: Optional[Dict[str, float]] = None
) -> Dict:
    """Update visual position and/or size

    Args:
        visual_data: The visual.json data
        x: Absolute x position (as shown in Power BI UI)
        y: Absolute y position (as shown in Power BI UI)
        width: Width (not affected by parent offset)
        height: Height (not affected by parent offset)
        z: Z-index (not affected by parent offset)
        parent_offset: Dict with 'x' and 'y' parent group offsets to subtract

    The x and y values are expected to be absolute positions (as displayed in Power BI).
    They will be converted to relative positions by subtracting the parent offset.
    """
    position = visual_data.setdefault('position', {})
    offset = parent_offset or {'x': 0, 'y': 0}

    if x is not None:
        # Convert absolute position to relative by subtracting parent offset
        position['x'] = x - offset['x']
    if y is not None:
        # Convert absolute position to relative by subtracting parent offset
        position['y'] = y - offset['y']
    if width is not None:
        position['width'] = width
    if height is not None:
        position['height'] = height
    if z is not None:
        position['z'] = z

    return visual_data


def _find_child_visuals(parent_name: str, visuals_path: Path) -> List[Dict]:
    """
    Find all child visuals that belong to a parent group.

    Args:
        parent_name: The visual name/ID of the parent group
        visuals_path: Path to the visuals folder for the page

    Returns:
        List of dicts with 'name', 'path', and 'data' for each child visual
    """
    children = []

    if not visuals_path.exists():
        return children

    for visual_folder in visuals_path.iterdir():
        if not visual_folder.is_dir():
            continue

        visual_json_path = visual_folder / "visual.json"
        if not visual_json_path.exists():
            continue

        visual_data = _load_json_file(visual_json_path)
        if not visual_data:
            continue

        # Check if this visual belongs to the parent group
        if visual_data.get('parentGroupName') == parent_name:
            children.append({
                'name': visual_data.get('name', visual_folder.name),
                'path': visual_json_path,
                'data': visual_data
            })

    return children


def _sync_visual_content(
    source_data: Dict,
    target_data: Dict,
    sync_position: bool = False
) -> Dict:
    """
    Sync visual content from source to target, preserving target's identity.

    Args:
        source_data: The source visual.json data to copy from
        target_data: The target visual.json data to update
        sync_position: If True, also copy position. If False, preserve target's position.

    Returns:
        Updated target_data with synced content
    """
    import copy

    # Deep copy source to avoid modifying original
    synced_data = copy.deepcopy(source_data)

    # Always preserve target's identity (name/ID)
    synced_data['name'] = target_data.get('name')

    # Preserve target's parentGroupName if it exists
    if 'parentGroupName' in target_data:
        synced_data['parentGroupName'] = target_data['parentGroupName']
    elif 'parentGroupName' in synced_data:
        del synced_data['parentGroupName']

    # Handle position syncing
    if not sync_position:
        # Preserve target's position
        if 'position' in target_data:
            synced_data['position'] = target_data['position']

    return synced_data


def _sync_column_widths(
    source_data: Dict,
    target_data: Dict
) -> Dict[str, Any]:
    """
    Sync only the columnWidth settings from source to target visual.

    This is a targeted sync that ONLY copies the columnWidth array from
    visual.objects.columnWidth, preserving everything else in the target visual.

    Args:
        source_data: The source visual.json data to copy columnWidth from
        target_data: The target visual.json data to update

    Returns:
        Dict with 'modified': bool, 'target_data': updated target data,
        'source_widths': the widths copied, 'previous_widths': the widths replaced
    """
    import copy

    # Deep copy target to avoid modifying original
    updated_target = copy.deepcopy(target_data)

    # Get source columnWidth
    source_visual = source_data.get('visual', {})
    source_objects = source_visual.get('objects', {})
    source_column_widths = source_objects.get('columnWidth', [])

    if not source_column_widths:
        return {
            'modified': False,
            'target_data': updated_target,
            'source_widths': None,
            'previous_widths': None,
            'reason': 'Source visual has no columnWidth settings'
        }

    # Get target's current columnWidth for reporting
    target_visual = updated_target.setdefault('visual', {})
    target_objects = target_visual.setdefault('objects', {})
    previous_widths = target_objects.get('columnWidth', [])

    # Copy source columnWidth to target
    target_objects['columnWidth'] = copy.deepcopy(source_column_widths)

    return {
        'modified': True,
        'target_data': updated_target,
        'source_widths': source_column_widths,
        'previous_widths': previous_widths if previous_widths else None
    }


def _replace_measure_in_visual(
    visual_data: Dict,
    source_entity: str,
    source_property: str,
    target_entity: str,
    target_property: str,
    new_display_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Replace a measure reference in visual projections.

    Searches through all query state projections (Values, Rows, Columns, etc.)
    and replaces measures matching source_entity/source_property with target values.

    Returns: Dict with 'modified': bool, 'changes': list of change descriptions
    """
    changes = []
    modified = False

    visual = visual_data.get('visual', {})
    query = visual.get('query', {})
    query_state = query.get('queryState', {})

    # Search through all projection areas (Values, Rows, Columns, etc.)
    for area_name, area_data in query_state.items():
        projections = area_data.get('projections', []) if isinstance(area_data, dict) else []

        for i, projection in enumerate(projections):
            field = projection.get('field', {})
            measure = field.get('Measure', {})

            if not measure:
                continue

            expression = measure.get('Expression', {})
            source_ref = expression.get('SourceRef', {})
            current_entity = source_ref.get('Entity', '')
            current_property = measure.get('Property', '')

            # Check if this matches the source measure (case-insensitive comparison)
            if (current_entity.lower() == source_entity.lower() and
                current_property.lower() == source_property.lower()):

                # Store original values for reporting
                original_entity = current_entity
                original_property = current_property
                original_display_name = projection.get('displayName', projection.get('nativeQueryRef', ''))

                # Update the measure reference
                source_ref['Entity'] = target_entity
                measure['Property'] = target_property

                # Update queryRef and nativeQueryRef
                old_query_ref = projection.get('queryRef', '')
                projection['queryRef'] = f"{target_entity}.{target_property}"
                projection['nativeQueryRef'] = target_property

                # Handle display name
                if new_display_name:
                    projection['displayName'] = new_display_name
                elif 'displayName' not in projection:
                    # If there was no displayName, set it to preserve the header
                    projection['displayName'] = original_display_name or original_property
                # else: keep existing displayName (the original header)

                changes.append({
                    'area': area_name,
                    'index': i,
                    'from': {
                        'entity': original_entity,
                        'property': original_property,
                        'display_name': original_display_name
                    },
                    'to': {
                        'entity': target_entity,
                        'property': target_property,
                        'display_name': projection.get('displayName', target_property)
                    }
                })
                modified = True

    return {
        'modified': modified,
        'changes': changes
    }


def _update_visual_config_property(
    visual_data: Dict,
    config_type: str,
    property_name: str,
    property_value: Any,
    selector_metadata: Optional[str] = None,
    value_type: str = "auto"
) -> Dict[str, Any]:
    """
    Update a visual configuration property.

    Args:
        visual_data: The visual.json data
        config_type: Object type to modify (e.g., 'categoryAxis', 'valueAxis', 'labels', 'legend')
        property_name: The property to update (e.g., 'fontSize', 'labelDisplayUnits', 'labelOverflow')
        property_value: The new value to set
        selector_metadata: Optional selector to match specific series (e.g., 'm Measure.WF2-Blank')
        value_type: How to format the value - 'auto', 'literal', 'boolean', 'number', 'string'

    Returns:
        Dict with 'modified': bool, 'change': description of the change
    """
    visual = visual_data.get('visual', {})
    objects = visual.setdefault('objects', {})

    # Ensure the config_type exists as an array
    if config_type not in objects:
        objects[config_type] = []

    config_array = objects[config_type]

    # Format the value based on type
    def format_value(val, vtype):
        if vtype == "auto":
            # Auto-detect type
            if isinstance(val, bool):
                return {"expr": {"Literal": {"Value": "true" if val else "false"}}}
            elif isinstance(val, (int, float)):
                # Numbers get D suffix in Power BI
                return {"expr": {"Literal": {"Value": f"{val}D"}}}
            elif isinstance(val, str):
                # Check if it's already formatted (ends with D, L, or is a quoted string)
                if val.endswith('D') or val.endswith('L') or (val.startswith("'") and val.endswith("'")):
                    return {"expr": {"Literal": {"Value": val}}}
                elif val.lower() in ['true', 'false']:
                    return {"expr": {"Literal": {"Value": val.lower()}}}
                else:
                    # Assume it's a pre-formatted Power BI value
                    return {"expr": {"Literal": {"Value": val}}}
        elif vtype == "literal":
            return {"expr": {"Literal": {"Value": str(val)}}}
        elif vtype == "boolean":
            return {"expr": {"Literal": {"Value": "true" if val else "false"}}}
        elif vtype == "number":
            return {"expr": {"Literal": {"Value": f"{val}D"}}}
        elif vtype == "string":
            return {"expr": {"Literal": {"Value": f"'{val}'"}}}
        return {"expr": {"Literal": {"Value": str(val)}}}

    formatted_value = format_value(property_value, value_type)

    # Find the right entry to modify
    target_entry = None
    target_index = -1

    if selector_metadata:
        # Look for entry with matching selector
        for i, entry in enumerate(config_array):
            selector = entry.get('selector', {})
            if selector.get('metadata') == selector_metadata:
                target_entry = entry
                target_index = i
                break

        # If not found, create a new entry with the selector
        if target_entry is None:
            target_entry = {
                "properties": {},
                "selector": {"metadata": selector_metadata}
            }
            config_array.append(target_entry)
            target_index = len(config_array) - 1
    else:
        # Use the first entry without a selector, or create one
        for i, entry in enumerate(config_array):
            if 'selector' not in entry or not entry.get('selector'):
                target_entry = entry
                target_index = i
                break

        if target_entry is None:
            if len(config_array) > 0:
                # Use the first entry
                target_entry = config_array[0]
                target_index = 0
            else:
                # Create a new entry
                target_entry = {"properties": {}}
                config_array.append(target_entry)
                target_index = 0

    # Update the property
    properties = target_entry.setdefault('properties', {})
    old_value = properties.get(property_name)
    properties[property_name] = formatted_value

    return {
        'modified': True,
        'change': {
            'config_type': config_type,
            'property_name': property_name,
            'selector_metadata': selector_metadata,
            'old_value': old_value,
            'new_value': formatted_value,
            'entry_index': target_index
        }
    }


def _remove_visual_config_property(
    visual_data: Dict,
    config_type: str,
    property_name: str,
    selector_metadata: Optional[str] = None
) -> Dict[str, Any]:
    """
    Remove a visual configuration property (for cases where removing means 'Auto').

    Args:
        visual_data: The visual.json data
        config_type: Object type (e.g., 'categoryAxis', 'valueAxis', 'labels')
        property_name: The property to remove
        selector_metadata: Optional selector to match specific series

    Returns:
        Dict with 'modified': bool, 'change': description of the change
    """
    visual = visual_data.get('visual', {})
    objects = visual.get('objects', {})

    if config_type not in objects:
        return {'modified': False, 'change': None}

    config_array = objects[config_type]

    for entry in config_array:
        selector = entry.get('selector', {})
        selector_match = selector.get('metadata') == selector_metadata if selector_metadata else ('selector' not in entry or not entry.get('selector'))

        if selector_match:
            properties = entry.get('properties', {})
            if property_name in properties:
                old_value = properties.pop(property_name)
                return {
                    'modified': True,
                    'change': {
                        'config_type': config_type,
                        'property_name': property_name,
                        'selector_metadata': selector_metadata,
                        'old_value': old_value,
                        'new_value': None,
                        'action': 'removed'
                    }
                }

    return {'modified': False, 'change': None}


def _op_list(args: Dict[str, Any], definition_path: Path) -> Dict[str, Any]:
    """Find and list visuals with their current configuration."""
    display_title = args.get('display_title')
    visual_type = args.get('visual_type')
    visual_name = args.get('visual_name')
    page_name = args.get('page_name')
    include_hidden = args.get('include_hidden', True)

    visuals = _find_visuals(
        definition_path,
        display_title=display_title,
        visual_type=visual_type,
        visual_name=visual_name,
        page_name=page_name,
        include_hidden=include_hidden
    )

    if not visuals:
        return {
            'success': True,
            'message': 'No visuals found matching the criteria',
            'visuals': [],
            'count': 0
        }

    # Check for summary_only mode (default: True to reduce response size)
    summary_only = args.get('summary_only', True)

    if summary_only:
        # Return condensed visual info
        condensed_visuals = []
        for visual in visuals:
            condensed = {
                'display_title': visual['display_title'],
                'page_name': visual.get('page_name', ''),
                'visual_type': visual['visual_type'],
                'visual_name': visual['visual_name'],
                'position': visual['position']
            }
            if visual.get('is_hidden'):
                condensed['is_hidden'] = True
            condensed_visuals.append(condensed)

        return {
            'success': True,
            'message': f'Found {len(visuals)} visual(s) matching criteria',
            'visuals': condensed_visuals,
            'count': len(visuals),
            'summary_only': True,
            'hint': 'Use summary_only=false for full details including file paths',
            'note': 'Positions are absolute (as shown in Power BI UI), accounting for parent group offsets'
        }

    # Strip internal fields from full output
    clean_visuals = []
    for visual in visuals:
        clean_visual = {k: v for k, v in visual.items() if not k.startswith('_')}
        clean_visuals.append(clean_visual)

    return {
        'success': True,
        'message': f'Found {len(visuals)} visual(s) matching criteria',
        'visuals': clean_visuals,
        'count': len(visuals)
    }


def _op_update_position(args: Dict[str, Any], definition_path: Path) -> Dict[str, Any]:
    """Update position and/or size of matching visuals."""
    display_title = args.get('display_title')
    visual_type = args.get('visual_type')
    visual_name = args.get('visual_name')
    page_name = args.get('page_name')
    include_hidden = args.get('include_hidden', True)

    # Get position/size parameters
    new_x = args.get('x')
    new_y = args.get('y')
    new_width = args.get('width')
    new_height = args.get('height')
    new_z = args.get('z')

    # Validate that at least one position/size parameter is provided
    if all(v is None for v in [new_x, new_y, new_width, new_height, new_z]):
        return {
            'success': False,
            'error': 'At least one position/size parameter is required: x, y, width, height, or z'
        }

    # Find matching visuals
    visuals = _find_visuals(
        definition_path,
        display_title=display_title,
        visual_type=visual_type,
        visual_name=visual_name,
        page_name=page_name,
        include_hidden=include_hidden
    )

    if not visuals:
        return {
            'success': False,
            'error': 'No visuals found matching the criteria. Use operation "list" to see available visuals.'
        }

    # Check for dry_run mode
    dry_run = args.get('dry_run', False)

    changes = []
    errors = []

    for visual in visuals:
        file_path = Path(visual['file_path'])

        # Capture before state
        before_position = visual['position'].copy()

        # Calculate after state
        after_position = before_position.copy()
        if new_x is not None:
            after_position['x'] = new_x
        if new_y is not None:
            after_position['y'] = new_y
        if new_width is not None:
            after_position['width'] = new_width
        if new_height is not None:
            after_position['height'] = new_height
        if new_z is not None:
            after_position['z'] = new_z

        # Check if anything would change
        position_changed = before_position != after_position

        if dry_run:
            # Just report what would change
            status = 'would_change' if position_changed else 'no_change'
            changes.append({
                'display_title': visual['display_title'],
                'page_name': visual.get('page_name', ''),
                'visual_name': visual['visual_name'],
                'before': {
                    'x': before_position.get('x'),
                    'y': before_position.get('y'),
                    'width': before_position.get('width'),
                    'height': before_position.get('height')
                },
                'after': {
                    'x': after_position.get('x'),
                    'y': after_position.get('y'),
                    'width': after_position.get('width'),
                    'height': after_position.get('height')
                },
                'status': status
            })
        else:
            if not position_changed:
                changes.append({
                    'display_title': visual['display_title'],
                    'page_name': visual.get('page_name', ''),
                    'visual_name': visual['visual_name'],
                    'status': 'no_change'
                })
                continue

            # Load, modify, and save
            visual_data = _load_json_file(file_path)
            if not visual_data:
                errors.append({
                    'file_path': str(file_path),
                    'error': 'Failed to load visual.json'
                })
                continue

            # Apply position changes
            # Pass parent offset so absolute positions are converted to relative
            parent_offset = visual.get('_parent_offset', {'x': 0, 'y': 0})
            modified_data = _update_visual_position(
                visual_data,
                x=new_x,
                y=new_y,
                width=new_width,
                height=new_height,
                z=new_z,
                parent_offset=parent_offset
            )

            # Save changes
            if _save_json_file(file_path, modified_data):
                changes.append({
                    'display_title': visual['display_title'],
                    'page_name': visual.get('page_name', ''),
                    'visual_name': visual['visual_name'],
                    'before': {
                        'x': before_position.get('x'),
                        'y': before_position.get('y'),
                        'width': before_position.get('width'),
                        'height': before_position.get('height')
                    },
                    'after': {
                        'x': after_position.get('x'),
                        'y': after_position.get('y'),
                        'width': after_position.get('width'),
                        'height': after_position.get('height')
                    },
                    'status': 'changed'
                })
            else:
                errors.append({
                    'file_path': str(file_path),
                    'error': 'Failed to save changes'
                })

    result = {
        'success': len(errors) == 0,
        'operation': 'update_position',
        'dry_run': dry_run,
        'message': f'{"Would modify" if dry_run else "Modified"} {len([c for c in changes if c.get("status") in ["changed", "would_change"]])} visual(s)',
        'changes': changes,
        'changes_count': len(changes)
    }

    if errors:
        result['errors'] = errors
        result['errors_count'] = len(errors)
        result['message'] += f' with {len(errors)} error(s)'

    return result


def _op_replace_measure(args: Dict[str, Any], definition_path: Path) -> Dict[str, Any]:
    """Replace a measure in visuals while keeping the display name."""
    display_title = args.get('display_title')
    visual_type = args.get('visual_type')
    visual_name = args.get('visual_name')
    page_name = args.get('page_name')
    include_hidden = args.get('include_hidden', True)

    # Get replace_measure parameters
    source_entity = args.get('source_entity')
    source_property = args.get('source_property')
    target_entity = args.get('target_entity')
    target_property = args.get('target_property')
    new_display_name = args.get('new_display_name')
    dry_run = args.get('dry_run', False)

    # Validate required parameters
    if not all([source_entity, source_property, target_entity, target_property]):
        return {
            'success': False,
            'error': 'replace_measure requires: source_entity, source_property, target_entity, target_property'
        }

    # Find matching visuals
    visuals = _find_visuals(
        definition_path,
        display_title=display_title,
        visual_type=visual_type,
        visual_name=visual_name,
        page_name=page_name,
        include_hidden=include_hidden
    )

    if not visuals:
        return {
            'success': True,
            'message': 'No visuals found matching the criteria',
            'changes': [],
            'count': 0
        }

    all_changes = []
    errors = []
    visuals_modified = 0

    for visual in visuals:
        file_path = Path(visual['file_path'])

        # Load visual data
        visual_data = _load_json_file(file_path)
        if not visual_data:
            errors.append({
                'file_path': str(file_path),
                'error': 'Failed to load visual.json'
            })
            continue

        # Try to replace measure
        result = _replace_measure_in_visual(
            visual_data,
            source_entity,
            source_property,
            target_entity,
            target_property,
            new_display_name
        )

        if result['modified']:
            change_record = {
                'display_title': visual['display_title'],
                'page_name': visual.get('page_name', ''),
                'visual_name': visual['visual_name'],
                'visual_type': visual['visual_type'],
                'measure_changes': result['changes'],
                'status': 'would_change' if dry_run else 'changed'
            }

            if not dry_run:
                # Save the modified visual
                if _save_json_file(file_path, visual_data):
                    change_record['status'] = 'changed'
                    visuals_modified += 1
                else:
                    change_record['status'] = 'error'
                    errors.append({
                        'file_path': str(file_path),
                        'error': 'Failed to save changes'
                    })
            else:
                visuals_modified += 1

            all_changes.append(change_record)

    result = {
        'success': len(errors) == 0,
        'operation': 'replace_measure',
        'dry_run': dry_run,
        'message': f'{"Would replace" if dry_run else "Replaced"} measure in {visuals_modified} visual(s)',
        'source': {
            'entity': source_entity,
            'property': source_property
        },
        'target': {
            'entity': target_entity,
            'property': target_property
        },
        'changes': all_changes,
        'changes_count': len(all_changes)
    }

    if new_display_name:
        result['new_display_name'] = new_display_name

    if errors:
        result['errors'] = errors
        result['errors_count'] = len(errors)
        result['message'] += f' with {len(errors)} error(s)'

    return result


def _op_sync_visual(args: Dict[str, Any], definition_path: Path) -> Dict[str, Any]:
    """Sync a visual (including visual groups with children) from source page to matching visuals on other pages."""
    display_title = args.get('display_title')

    # Sync-specific parameters
    source_visual_name = args.get('source_visual_name')
    source_page = args.get('source_page')
    sync_position = args.get('sync_position', True)
    sync_children = args.get('sync_children', True)
    dry_run = args.get('dry_run', False)
    target_pages = args.get('target_pages')  # Optional: list of page names to sync to
    # New parameters for flexible target matching
    target_display_title = args.get('target_display_title')  # Match targets by display title
    target_visual_type = args.get('target_visual_type')  # Match targets by visual type

    # Validate required parameters
    if not source_visual_name and not display_title:
        return {
            'success': False,
            'error': 'sync_visual requires either source_visual_name or display_title parameter to identify the source visual'
        }

    # Find source visual
    source_visuals = _find_visuals(
        definition_path,
        visual_name=source_visual_name,
        display_title=display_title if not source_visual_name else None,
        page_name=source_page,
        include_hidden=True
    )

    if not source_visuals:
        search_criteria = source_visual_name or display_title
        return {
            'success': False,
            'error': f'No source visual found matching: {search_criteria}. Use operation "list" to see available visuals.'
        }

    # Determine source visual
    source_visual = None
    if source_page:
        # Find visual on specific source page
        for v in source_visuals:
            if source_page.lower() in v.get('page_name', '').lower():
                source_visual = v
                break
        if not source_visual:
            return {
                'success': False,
                'error': f'Source visual not found on page matching: {source_page}'
            }
    else:
        # Use the first found visual as source
        source_visual = source_visuals[0]

    source_page_name = source_visual.get('page_name', '')
    source_file_path = Path(source_visual['file_path'])
    source_visuals_path = source_file_path.parent.parent  # Go up from visual.json -> visual_folder -> visuals
    source_visual_id = source_visual.get('visual_name', '')  # The actual visual ID

    # Load source visual data
    source_data = _load_json_file(source_file_path)
    if not source_data:
        return {
            'success': False,
            'error': f'Failed to load source visual from: {source_file_path}'
        }

    # Check if source is a visual group and find children
    source_children = []
    is_group = 'visualGroup' in source_data.get('visual', {})
    if is_group and sync_children:
        source_children = _find_child_visuals(source_visual_id, source_visuals_path)

    # Find target visuals
    # If target_display_title or target_visual_type is specified, use those for matching
    # Otherwise, fall back to matching by visual_name (original behavior)
    if target_display_title or target_visual_type:
        # Flexible matching: find visuals by title/type on other pages
        all_potential_targets = _find_visuals(
            definition_path,
            display_title=target_display_title,
            visual_type=target_visual_type,
            include_hidden=True
        )
        target_visuals = []
        for v in all_potential_targets:
            # Skip the source visual itself (same page)
            if v.get('page_name', '') == source_page_name:
                continue
            # Filter by target_pages if specified
            if target_pages:
                if not any(tp.lower() in v.get('page_name', '').lower() for tp in target_pages):
                    continue
            target_visuals.append(v)
    else:
        # Original behavior: find visuals with same visual_name on other pages
        all_matching_visuals = _find_visuals(
            definition_path,
            visual_name=source_visual_id,
            include_hidden=True
        )
        target_visuals = []
        for v in all_matching_visuals:
            if v.get('page_name', '') != source_page_name:
                # Filter by target_pages if specified
                if target_pages:
                    if not any(tp.lower() in v.get('page_name', '').lower() for tp in target_pages):
                        continue
                target_visuals.append(v)

    if not target_visuals:
        hint = ''
        if not target_display_title and not target_visual_type:
            hint = ' Tip: Use target_display_title or target_visual_type to match visuals by title/type instead of visual ID.'
        return {
            'success': True,
            'message': f'Source visual found on page "{source_page_name}", but no matching visuals found on other pages to sync to.{hint}',
            'source': {
                'visual_name': source_visual_id,
                'display_title': source_visual.get('display_title'),
                'visual_type': source_visual.get('visual_type'),
                'page': source_page_name,
                'is_group': is_group,
                'children_count': len(source_children) if is_group else 0
            },
            'targets_found': 0
        }

    # Perform sync
    changes = []
    errors = []

    for target_visual in target_visuals:
        target_file_path = Path(target_visual['file_path'])
        target_visuals_path = target_file_path.parent.parent
        target_page_name = target_visual.get('page_name', '')

        target_visual_id = target_visual.get('visual_name', '')

        # Load target visual data
        target_data = _load_json_file(target_file_path)
        if not target_data:
            errors.append({
                'page': target_page_name,
                'visual_name': target_visual_id,
                'error': 'Failed to load target visual'
            })
            continue

        # Sync the main visual
        synced_data = _sync_visual_content(source_data, target_data, sync_position)

        change_record = {
            'page': target_page_name,
            'target_visual_name': target_visual_id,
            'target_display_title': target_visual.get('display_title'),
            'visual_type': target_visual.get('visual_type', 'unknown'),
            'position_synced': sync_position,
            'children_synced': [],
            'status': 'would_sync' if dry_run else 'synced'
        }

        if not dry_run:
            if not _save_json_file(target_file_path, synced_data):
                errors.append({
                    'page': target_page_name,
                    'visual_name': target_visual_id,
                    'error': 'Failed to save synced visual'
                })
                continue

        # Sync children if this is a group
        if is_group and sync_children and source_children:
            for source_child in source_children:
                child_name = source_child['name']

                # Find matching child on target page
                target_child_path = target_visuals_path / child_name / "visual.json"
                if not target_child_path.exists():
                    change_record['children_synced'].append({
                        'name': child_name,
                        'status': 'skipped_not_found'
                    })
                    continue

                target_child_data = _load_json_file(target_child_path)
                if not target_child_data:
                    change_record['children_synced'].append({
                        'name': child_name,
                        'status': 'skipped_load_failed'
                    })
                    continue

                # Sync child content
                synced_child = _sync_visual_content(
                    source_child['data'],
                    target_child_data,
                    sync_position
                )

                if not dry_run:
                    if _save_json_file(target_child_path, synced_child):
                        change_record['children_synced'].append({
                            'name': child_name,
                            'status': 'synced'
                        })
                    else:
                        change_record['children_synced'].append({
                            'name': child_name,
                            'status': 'save_failed'
                        })
                else:
                    change_record['children_synced'].append({
                        'name': child_name,
                        'status': 'would_sync'
                    })

        changes.append(change_record)

    # Build a descriptive source identifier for the message
    source_desc = source_visual.get('display_title') or source_visual_id
    result = {
        'success': len(errors) == 0,
        'operation': 'sync_visual',
        'dry_run': dry_run,
        'message': f'{"Would sync" if dry_run else "Synced"} visual "{source_desc}" from "{source_page_name}" to {len(changes)} page(s)',
        'source': {
            'visual_name': source_visual_id,
            'display_title': source_visual.get('display_title'),
            'visual_type': source_visual.get('visual_type'),
            'page': source_page_name,
            'is_group': is_group,
            'children_count': len(source_children) if is_group else 0
        },
        'target_matching': {
            'by_display_title': target_display_title,
            'by_visual_type': target_visual_type
        } if (target_display_title or target_visual_type) else 'by_visual_name',
        'sync_position': sync_position,
        'sync_children': sync_children,
        'changes': changes,
        'changes_count': len(changes)
    }

    if errors:
        result['errors'] = errors
        result['errors_count'] = len(errors)
        result['message'] += f' with {len(errors)} error(s)'

    return result


def _op_sync_column_widths(args: Dict[str, Any], definition_path: Path) -> Dict[str, Any]:
    """Sync only columnWidth settings from source matrix to target matrices."""
    display_title = args.get('display_title')

    # Sync column widths parameters
    source_visual_name = args.get('source_visual_name')
    source_page = args.get('source_page')
    dry_run = args.get('dry_run', False)
    target_pages = args.get('target_pages')  # Optional: list of page names to sync to
    target_display_title = args.get('target_display_title')  # Match targets by display title
    target_visual_type = args.get('target_visual_type')  # Match targets by visual type

    # Validate required parameters - need to identify source visual
    if not source_visual_name and not display_title:
        return {
            'success': False,
            'error': 'sync_column_widths requires either source_visual_name or display_title parameter to identify the source visual'
        }

    # Find source visual
    source_visuals = _find_visuals(
        definition_path,
        visual_name=source_visual_name,
        display_title=display_title if not source_visual_name else None,
        page_name=source_page,
        include_hidden=True
    )

    if not source_visuals:
        search_criteria = source_visual_name or display_title
        return {
            'success': False,
            'error': f'No source visual found matching: {search_criteria}. Use operation "list" to see available visuals.'
        }

    # Determine source visual
    source_visual = None
    if source_page:
        # Find visual on specific source page
        for v in source_visuals:
            if source_page.lower() in v.get('page_name', '').lower():
                source_visual = v
                break
        if not source_visual:
            return {
                'success': False,
                'error': f'Source visual not found on page matching: {source_page}'
            }
    else:
        # Use the first found visual as source
        source_visual = source_visuals[0]

    source_page_name = source_visual.get('page_name', '')
    source_file_path = Path(source_visual['file_path'])
    source_visual_id = source_visual.get('visual_name', '')

    # Load source visual data
    source_data = _load_json_file(source_file_path)
    if not source_data:
        return {
            'success': False,
            'error': f'Failed to load source visual from: {source_file_path}'
        }

    # Check if source has columnWidth settings
    source_column_widths = source_data.get('visual', {}).get('objects', {}).get('columnWidth', [])
    if not source_column_widths:
        return {
            'success': False,
            'error': f'Source visual has no columnWidth settings to sync. Visual type: {source_visual.get("visual_type")}'
        }

    # Find target visuals
    if target_display_title or target_visual_type:
        # Flexible matching: find visuals by title/type on other pages
        all_potential_targets = _find_visuals(
            definition_path,
            display_title=target_display_title,
            visual_type=target_visual_type,
            include_hidden=True
        )
        target_visuals = []
        for v in all_potential_targets:
            # Skip the source visual itself (same visual on same page)
            if v.get('visual_name') == source_visual_id and v.get('page_name', '') == source_page_name:
                continue
            # Filter by target_pages if specified
            if target_pages:
                if not any(tp.lower() in v.get('page_name', '').lower() for tp in target_pages):
                    continue
            target_visuals.append(v)
    else:
        # Find all matrix visuals (or same visual type as source) on other pages
        source_visual_type = source_visual.get('visual_type', 'pivotTable')
        all_potential_targets = _find_visuals(
            definition_path,
            visual_type=source_visual_type,
            include_hidden=True
        )
        target_visuals = []
        for v in all_potential_targets:
            # Skip the source visual itself
            if v.get('visual_name') == source_visual_id and v.get('page_name', '') == source_page_name:
                continue
            # Filter by target_pages if specified
            if target_pages:
                if not any(tp.lower() in v.get('page_name', '').lower() for tp in target_pages):
                    continue
            target_visuals.append(v)

    if not target_visuals:
        return {
            'success': True,
            'message': f'Source visual found on page "{source_page_name}" with {len(source_column_widths)} column width setting(s), but no matching target visuals found to sync to.',
            'source': {
                'visual_name': source_visual_id,
                'display_title': source_visual.get('display_title'),
                'visual_type': source_visual.get('visual_type'),
                'page': source_page_name,
                'column_widths_count': len(source_column_widths)
            },
            'targets_found': 0,
            'hint': 'Use target_display_title or target_visual_type to match target visuals.'
        }

    # Perform column width sync
    changes = []
    errors = []

    for target_visual in target_visuals:
        target_file_path = Path(target_visual['file_path'])
        target_page_name = target_visual.get('page_name', '')
        target_visual_id = target_visual.get('visual_name', '')

        # Load target visual data
        target_data = _load_json_file(target_file_path)
        if not target_data:
            errors.append({
                'page': target_page_name,
                'visual_name': target_visual_id,
                'error': 'Failed to load target visual'
            })
            continue

        # Sync column widths
        sync_result = _sync_column_widths(source_data, target_data)

        change_record = {
            'page': target_page_name,
            'target_visual_name': target_visual_id,
            'target_display_title': target_visual.get('display_title'),
            'visual_type': target_visual.get('visual_type', 'unknown'),
            'column_widths_synced': len(source_column_widths),
            'had_previous_widths': sync_result.get('previous_widths') is not None,
            'status': 'would_sync' if dry_run else 'synced'
        }

        if not sync_result['modified']:
            change_record['status'] = 'skipped'
            change_record['reason'] = sync_result.get('reason', 'Unknown')
            changes.append(change_record)
            continue

        if not dry_run:
            if not _save_json_file(target_file_path, sync_result['target_data']):
                errors.append({
                    'page': target_page_name,
                    'visual_name': target_visual_id,
                    'error': 'Failed to save synced visual'
                })
                continue

        changes.append(change_record)

    # Build result
    source_desc = source_visual.get('display_title') or source_visual_id
    result = {
        'success': len(errors) == 0,
        'operation': 'sync_column_widths',
        'dry_run': dry_run,
        'message': f'{"Would sync" if dry_run else "Synced"} column widths from "{source_desc}" on "{source_page_name}" to {len([c for c in changes if c.get("status") in ["synced", "would_sync"]])} visual(s)',
        'source': {
            'visual_name': source_visual_id,
            'display_title': source_visual.get('display_title'),
            'visual_type': source_visual.get('visual_type'),
            'page': source_page_name,
            'column_widths_count': len(source_column_widths)
        },
        'target_matching': {
            'by_display_title': target_display_title,
            'by_visual_type': target_visual_type
        } if (target_display_title or target_visual_type) else 'by_visual_type',
        'changes': changes,
        'changes_count': len(changes)
    }

    if errors:
        result['errors'] = errors
        result['errors_count'] = len(errors)
        result['message'] += f' with {len(errors)} error(s)'

    return result


def _op_update_visual_config(args: Dict[str, Any], definition_path: Path) -> Dict[str, Any]:
    """Update visual formatting properties (axis settings, labels, colors, etc.)."""
    display_title = args.get('display_title')
    visual_type = args.get('visual_type')
    visual_name = args.get('visual_name')
    page_name = args.get('page_name')
    include_hidden = args.get('include_hidden', True)

    # Update visual formatting/configuration properties
    config_type = args.get('config_type')  # e.g., 'categoryAxis', 'valueAxis', 'labels', 'legend'
    property_name = args.get('property_name')  # e.g., 'fontSize', 'labelDisplayUnits', 'labelOverflow'
    property_value = args.get('property_value')  # The new value
    selector_metadata = args.get('selector_metadata')  # Optional: for series-specific settings
    value_type = args.get('value_type', 'auto')  # How to format: 'auto', 'literal', 'boolean', 'number', 'string'
    remove_property = args.get('remove_property', False)  # Set to True to remove the property (for 'Auto' settings)
    dry_run = args.get('dry_run', False)

    # Support for batch updates - array of config changes
    config_updates = args.get('config_updates')  # Array of {config_type, property_name, property_value, selector_metadata}

    # Validate parameters
    if not config_updates:
        if not config_type or not property_name:
            return {
                'success': False,
                'error': 'update_visual_config requires either: (config_type + property_name + property_value) OR config_updates array'
            }
        if property_value is None and not remove_property:
            return {
                'success': False,
                'error': 'property_value is required unless remove_property is True'
            }
        # Convert single update to array format
        config_updates = [{
            'config_type': config_type,
            'property_name': property_name,
            'property_value': property_value,
            'selector_metadata': selector_metadata,
            'value_type': value_type,
            'remove_property': remove_property
        }]

    # Find matching visuals
    visuals = _find_visuals(
        definition_path,
        display_title=display_title,
        visual_type=visual_type,
        visual_name=visual_name,
        page_name=page_name,
        include_hidden=include_hidden
    )

    if not visuals:
        return {
            'success': False,
            'error': 'No visuals found matching the criteria. Use operation "list" to see available visuals.'
        }

    changes = []
    errors = []

    for visual in visuals:
        file_path = Path(visual['file_path'])

        # Load visual data
        visual_data = _load_json_file(file_path)
        if not visual_data:
            errors.append({
                'file_path': str(file_path),
                'error': 'Failed to load visual.json'
            })
            continue

        visual_changes = []
        visual_modified = False

        # Apply all config updates
        for update in config_updates:
            update_config_type = update.get('config_type')
            update_property_name = update.get('property_name')
            update_property_value = update.get('property_value')
            update_selector = update.get('selector_metadata')
            update_value_type = update.get('value_type', 'auto')
            update_remove = update.get('remove_property', False)

            if update_remove:
                result = _remove_visual_config_property(
                    visual_data,
                    update_config_type,
                    update_property_name,
                    update_selector
                )
            else:
                result = _update_visual_config_property(
                    visual_data,
                    update_config_type,
                    update_property_name,
                    update_property_value,
                    update_selector,
                    update_value_type
                )

            if result['modified']:
                visual_modified = True
                visual_changes.append(result['change'])

        if visual_modified:
            change_record = {
                'display_title': visual['display_title'],
                'page_name': visual.get('page_name', ''),
                'visual_name': visual['visual_name'],
                'visual_type': visual['visual_type'],
                'config_changes': visual_changes,
                'status': 'would_change' if dry_run else 'changed'
            }

            if not dry_run:
                if _save_json_file(file_path, visual_data):
                    change_record['status'] = 'changed'
                else:
                    change_record['status'] = 'error'
                    errors.append({
                        'file_path': str(file_path),
                        'error': 'Failed to save changes'
                    })

            changes.append(change_record)

    result = {
        'success': len(errors) == 0,
        'operation': 'update_visual_config',
        'dry_run': dry_run,
        'message': f'{"Would update" if dry_run else "Updated"} config in {len(changes)} visual(s)',
        'changes': changes,
        'changes_count': len(changes)
    }

    if errors:
        result['errors'] = errors
        result['errors_count'] = len(errors)
        result['message'] += f' with {len(errors)} error(s)'

    return result


def _resolve_definition_path(pbip_path: str) -> Dict[str, Any]:
    """Resolve and validate the definition path from a PBIP path.

    Returns a dict with 'path' on success or 'error' on failure.
    """
    definition_path = _find_definition_folder(pbip_path)
    if not definition_path:
        return {
            'error': (
                f'Could not find definition folder in: {pbip_path}.'
                ' Ensure path points to a valid PBIP project.'
            )
        }
    return {'path': definition_path}


def handle_visual_operations(args: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatch for visual list, position, and config operations."""
    operation = args.get('operation', 'list')
    pbip_path = args.get('pbip_path')

    if not pbip_path:
        return {
            'success': False,
            'error': (
                'pbip_path parameter is required'
                ' - path to PBIP project, .Report folder,'
                ' or definition folder'
            ),
        }

    resolved = _resolve_definition_path(pbip_path)
    if 'error' in resolved:
        return {'success': False, 'error': resolved['error']}
    definition_path = resolved['path']

    ops = {
        'list': _op_list,
        'update_position': _op_update_position,
        'update_visual_config': _op_update_visual_config,
    }
    op_func = ops.get(operation)
    if not op_func:
        valid = ", ".join(ops)
        return {
            'success': False,
            'error': (
                f'Unknown operation: {operation}.'
                f' Valid: {valid}'
            ),
        }
    return op_func(args, definition_path)


def handle_visual_sync(args: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatch for visual sync operations."""
    operation = args.get('operation')
    pbip_path = args.get('pbip_path')

    if not pbip_path:
        return {
            'success': False,
            'error': (
                'pbip_path parameter is required'
                ' - path to PBIP project, .Report folder,'
                ' or definition folder'
            ),
        }

    if not operation:
        return {
            'success': False,
            'error': 'operation parameter is required',
        }

    resolved = _resolve_definition_path(pbip_path)
    if 'error' in resolved:
        return {'success': False, 'error': resolved['error']}
    definition_path = resolved['path']

    ops = {
        'replace_measure': _op_replace_measure,
        'sync_visual': _op_sync_visual,
        'sync_column_widths': _op_sync_column_widths,
    }
    op_func = ops.get(operation)
    if not op_func:
        valid = ", ".join(ops)
        return {
            'success': False,
            'error': (
                f'Unknown operation: {operation}.'
                f' Valid: {valid}'
            ),
        }
    return op_func(args, definition_path)


def register_visual_operations_handler(registry):
    """Register visual operations handler (list, position, config)."""
    from server.tool_schemas import TOOL_SCHEMAS

    tool = ToolDefinition(
        name="08_Visual_Operations",
        description=(
            "Edit visual properties: list,"
            " resize/reposition, update_visual_config."
        ),
        handler=handle_visual_operations,
        input_schema=TOOL_SCHEMAS.get('visual_operations', {}),
        category="pbip",
        sort_order=80,
    )
    registry.register(tool)
    logger.info("Registered visual_operations handler")


def register_visual_sync_handler(registry):
    """Register visual sync handler (replace, sync)."""
    from server.tool_schemas import TOOL_SCHEMAS

    tool = ToolDefinition(
        name="08_Visual_Sync",
        description=(
            "Sync and replace visuals: replace_measure,"
            " sync_visual, sync_column_widths."
        ),
        handler=handle_visual_sync,
        input_schema=TOOL_SCHEMAS.get('visual_sync', {}),
        category="pbip",
        sort_order=81,
    )
    registry.register(tool)
    logger.info("Registered visual_sync handler")
