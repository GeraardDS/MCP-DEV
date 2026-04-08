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
    resolve_definition_path,
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

    info = {
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

    # Annotations (name-value pairs)
    annotations = visual_data.get('annotations', [])
    if annotations:
        info['annotations'] = annotations

    # Mobile layout presence
    info['has_mobile_layout'] = (file_path.parent / 'mobile.json').exists()

    return info


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
    is_group = (
        'visualGroup' in source_data
        or source_data.get('visual', {}).get('visualType') == 'SummarizeVisualContainer'
    )
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


def _op_create_visual(args: Dict[str, Any], definition_path: Path) -> Dict[str, Any]:
    """Create a new visual on a page from a template spec (absorbed from authoring_handler)."""
    from core.pbip.authoring.visual_builder import VisualBuilder

    page_id = args.get("page_id") or args.get("page_name")
    if not page_id:
        return {"success": False, "error": "page_id or page_name is required"}

    visual_type = args.get("visual_type")
    if not visual_type:
        return {"success": False, "error": "visual_type is required"}

    page_dir = _resolve_page_dir(definition_path, page_id)
    if not page_dir:
        return {"success": False, "error": f"Page not found: {page_id}"}

    builder = VisualBuilder(visual_type)

    pos = args.get("position", {})
    if pos:
        builder.position(
            x=pos.get("x", 0), y=pos.get("y", 0),
            width=pos.get("width", 300), height=pos.get("height", 200),
            z=pos.get("z", 0),
        )

    title = args.get("title")
    if title:
        builder.set_title(title)

    for m in args.get("measures", []):
        builder.add_measure(
            table=m.get("table", ""), measure=m.get("measure", ""),
            bucket=m.get("bucket", "Values"), display_name=m.get("display_name"),
        )

    for c in args.get("columns", []):
        builder.add_column(
            table=c.get("table", ""), column=c.get("column", ""),
            bucket=c.get("bucket", "Category"), display_name=c.get("display_name"),
        )

    parent_group = args.get("parent_group")
    if parent_group:
        builder.in_group(parent_group)

    for fmt in args.get("formatting", []):
        builder.set_formatting(
            config_type=fmt.get("config_type", ""),
            property_name=fmt.get("property_name", ""),
            value=fmt.get("value"),
        )

    visual_dict = builder.build()
    visuals_dir = page_dir / "visuals"
    visuals_dir.mkdir(exist_ok=True)
    visual_id = visual_dict["name"]
    visual_folder = visuals_dir / visual_id
    visual_folder.mkdir(exist_ok=True)

    _save_json_file(visual_folder / "visual.json", visual_dict)
    return {
        "success": True, "operation": "create",
        "visual_id": visual_id, "visual_type": visual_type,
        "page_id": page_dir.name, "path": str(visual_folder),
    }


def _op_create_visual_group(args: Dict[str, Any], definition_path: Path) -> Dict[str, Any]:
    """Create a visual group container on a page (absorbed from authoring_handler)."""
    from core.pbip.authoring.visual_builder import VisualBuilder

    page_id = args.get("page_id") or args.get("page_name")
    if not page_id:
        return {"success": False, "error": "page_id or page_name is required"}

    page_dir = _resolve_page_dir(definition_path, page_id)
    if not page_dir:
        return {"success": False, "error": f"Page not found: {page_id}"}

    group_name = args.get("group_name", "Visual Group")
    builder = VisualBuilder("visualGroup")
    pos = args.get("position", {})
    if pos:
        builder.position(
            x=pos.get("x", 0), y=pos.get("y", 0),
            width=pos.get("width", 400), height=pos.get("height", 300),
            z=pos.get("z", 0),
        )
    builder.set_group_name(group_name)

    visual_dict = builder.build()
    visual_id = visual_dict["name"]
    visuals_dir = page_dir / "visuals"
    visuals_dir.mkdir(exist_ok=True)
    visual_folder = visuals_dir / visual_id
    visual_folder.mkdir(exist_ok=True)

    _save_json_file(visual_folder / "visual.json", visual_dict)
    return {
        "success": True, "operation": "create_group",
        "visual_id": visual_id, "group_name": group_name,
        "page_id": page_dir.name, "path": str(visual_folder),
    }


def _op_delete_visual(args: Dict[str, Any], definition_path: Path) -> Dict[str, Any]:
    """Delete a visual (and children if it's a group) (absorbed from authoring_handler)."""
    from core.pbip.authoring.clone_engine import CloneEngine

    page_id = args.get("page_id") or args.get("page_name")
    visual_id = args.get("visual_id") or args.get("visual_name")
    if not page_id:
        return {"success": False, "error": "page_id or page_name is required"}
    if not visual_id:
        return {"success": False, "error": "visual_id or visual_name is required"}

    engine = CloneEngine()
    result = engine.delete_visual(
        definition_path=definition_path, page_id=page_id,
        visual_id=visual_id, delete_children=args.get("delete_children", True),
    )
    result["operation"] = "delete"
    return result


def _op_list_templates(args: Dict[str, Any], definition_path: Path) -> Dict[str, Any]:
    """List available visual templates (absorbed from authoring_handler)."""
    from core.pbip.authoring.visual_templates import get_template_catalog
    catalog = get_template_catalog()
    return {"success": True, "operation": "list_templates", "templates": catalog, "count": len(catalog)}


def _op_get_template(args: Dict[str, Any], definition_path: Path) -> Dict[str, Any]:
    """Get template for a visual type (absorbed from authoring_handler)."""
    from core.pbip.authoring.visual_templates import get_template, TEMPLATE_REGISTRY
    visual_type = args.get("visual_type")
    if not visual_type:
        return {"success": False, "error": "visual_type is required"}
    if visual_type not in TEMPLATE_REGISTRY:
        return {"success": False, "error": f"Unknown visual type: '{visual_type}'. Available: {', '.join(sorted(TEMPLATE_REGISTRY.keys()))}"}
    template = get_template(visual_type)
    return {"success": True, "operation": "get_template", "visual_type": visual_type, "template": template}


def _op_configure_slicer(args: Dict[str, Any], definition_path: Path) -> Dict[str, Any]:
    """Configure slicer settings (absorbed from slicer_operations_handler)."""
    from server.handlers.slicer_operations_handler import (
        _find_slicers, _configure_single_select_all,
    )
    display_name = args.get('display_name_filter') or args.get('display_name')
    entity = args.get('entity')
    property_name = args.get('property')
    dry_run = args.get('dry_run', False)

    slicers = _find_slicers(definition_path, display_name, entity, property_name)
    if not slicers:
        return {'success': False, 'error': 'No slicers found matching criteria'}

    changes = []
    errors = []
    for slicer in slicers:
        file_path = Path(slicer['file_path'])
        before_mode = slicer['selection_mode']
        if dry_run:
            changes.append({
                'display_name': slicer['display_name'], 'page_name': slicer.get('page_name', ''),
                'before_mode': before_mode, 'after_mode': 'single_select_all',
                'status': 'would_change' if before_mode != 'single_select_all' else 'already_configured'
            })
        else:
            visual_data = _load_json_file(file_path)
            if not visual_data:
                errors.append({'file_path': str(file_path), 'error': 'Failed to load'})
                continue
            _configure_single_select_all(visual_data)
            if _save_json_file(file_path, visual_data):
                changes.append({
                    'display_name': slicer['display_name'], 'page_name': slicer.get('page_name', ''),
                    'before_mode': before_mode, 'after_mode': 'single_select_all', 'status': 'changed'
                })
            else:
                errors.append({'file_path': str(file_path), 'error': 'Failed to save'})

    result = {'success': len(errors) == 0, 'operation': 'configure_slicer', 'dry_run': dry_run, 'changes': changes, 'changes_count': len(changes)}
    if errors:
        result['errors'] = errors
    return result


def _op_align(args: Dict[str, Any], definition_path: Path) -> Dict[str, Any]:
    """Align multiple visuals."""
    from core.pbip.visual_alignment_engine import align_visuals
    return align_visuals(
        definition_path=definition_path,
        page_name=args.get('page_name', ''),
        visual_names=args.get('visual_names', []),
        alignment=args.get('alignment', 'left'),
    )


def _op_add_field(args: Dict[str, Any], definition_path: Path) -> Dict[str, Any]:
    """Add a field to a visual's data role."""
    from core.pbip.field_binding_engine import add_field
    return add_field(
        definition_path=definition_path,
        page_name=args.get('page_name', ''),
        visual_name=args.get('visual_name', ''),
        table=args.get('table', ''),
        field=args.get('field', ''),
        bucket=args.get('bucket', 'Values'),
        field_type=args.get('field_type', 'Column'),
        display_name=args.get('display_name'),
    )


def _op_remove_field(args: Dict[str, Any], definition_path: Path) -> Dict[str, Any]:
    """Remove a field from a visual's data roles."""
    from core.pbip.field_binding_engine import remove_field
    return remove_field(
        definition_path=definition_path,
        page_name=args.get('page_name', ''),
        visual_name=args.get('visual_name', ''),
        table=args.get('table', ''),
        field=args.get('field', ''),
        bucket=args.get('bucket'),
    )


def _op_set_sort(args: Dict[str, Any], definition_path: Path) -> Dict[str, Any]:
    """Set sort field and direction on a visual."""
    visual_name = args.get('visual_name')
    page_name = args.get('page_name')
    sort_field = args.get('sort_field', '')
    sort_direction = args.get('sort_direction', 'Ascending')

    if not visual_name or not page_name or not sort_field:
        return {'success': False, 'error': 'set_sort requires: page_name, visual_name, sort_field'}

    visuals = _find_visuals(definition_path, visual_name=visual_name, page_name=page_name)
    if not visuals:
        return {'success': False, 'error': f'Visual not found: {visual_name} on {page_name}'}

    visual = visuals[0]
    file_path = Path(visual['file_path'])
    visual_data = _load_json_file(file_path)
    if not visual_data:
        return {'success': False, 'error': 'Failed to load visual.json'}

    parts = sort_field.split('.', 1)
    if len(parts) != 2:
        return {'success': False, 'error': 'sort_field must be Table.Field format'}

    table, field = parts
    sort_order = 1 if sort_direction == 'Ascending' else 2
    visual_section = visual_data.setdefault('visual', {})
    visual_section['sort'] = {
        "clauses": [{
            "field": {
                "Column": {
                    "Expression": {"SourceRef": {"Entity": table}},
                    "Property": field
                }
            },
            "direction": sort_order
        }]
    }

    dry_run = args.get('dry_run', False)
    if not dry_run:
        _save_json_file(file_path, visual_data)

    return {
        'success': True, 'operation': 'set_sort', 'dry_run': dry_run,
        'visual_name': visual_name, 'sort_field': sort_field, 'sort_direction': sort_direction
    }


def _op_set_action(args: Dict[str, Any], definition_path: Path) -> Dict[str, Any]:
    """Set action button configuration."""
    visual_name = args.get('visual_name')
    page_name = args.get('page_name')
    action_type = args.get('action_type')
    action_target = args.get('action_target', '')

    if not visual_name or not page_name or not action_type:
        return {'success': False, 'error': 'set_action requires: page_name, visual_name, action_type'}

    visuals = _find_visuals(definition_path, visual_name=visual_name, page_name=page_name)
    if not visuals:
        return {'success': False, 'error': f'Visual not found: {visual_name} on {page_name}'}

    visual = visuals[0]
    file_path = Path(visual['file_path'])
    visual_data = _load_json_file(file_path)
    if not visual_data:
        return {'success': False, 'error': 'Failed to load visual.json'}

    visual_section = visual_data.setdefault('visual', {})
    vc_objects = visual_section.setdefault('visualContainerObjects', {})
    action_config = [{
        "properties": {
            "type": {"expr": {"Literal": {"Value": f"'{action_type}'"}}},
        }
    }]
    if action_target:
        action_config[0]["properties"]["destination"] = {"expr": {"Literal": {"Value": f"'{action_target}'"}}}
    vc_objects['action'] = action_config

    dry_run = args.get('dry_run', False)
    if not dry_run:
        _save_json_file(file_path, visual_data)

    return {
        'success': True, 'operation': 'set_action', 'dry_run': dry_run,
        'visual_name': visual_name, 'action_type': action_type, 'action_target': action_target
    }


def _op_inject_code(args: Dict[str, Any], definition_path: Path) -> Dict[str, Any]:
    """Inject Deneb/Python/R code into a visual."""
    visual_name = args.get('visual_name')
    page_name = args.get('page_name')
    code_type = args.get('code_type')
    code = args.get('code', '')

    if not visual_name or not page_name or not code_type or not code:
        return {'success': False, 'error': 'inject_code requires: page_name, visual_name, code_type, code'}

    # Escape single quotes to prevent breaking PBIR Literal Value strings
    code = code.replace("'", "\\'")

    visuals = _find_visuals(definition_path, visual_name=visual_name, page_name=page_name)
    if not visuals:
        return {'success': False, 'error': f'Visual not found: {visual_name} on {page_name}'}

    visual = visuals[0]
    file_path = Path(visual['file_path'])
    visual_data = _load_json_file(file_path)
    if not visual_data:
        return {'success': False, 'error': 'Failed to load visual.json'}

    visual_section = visual_data.setdefault('visual', {})
    objects = visual_section.setdefault('objects', {})

    if code_type == 'deneb':
        provider = args.get('provider', 'vegaLite')
        objects['denebConfig'] = [{"properties": {
            "vegaSpec": {"expr": {"Literal": {"Value": f"'{code}'"}}},
            "provider": {"expr": {"Literal": {"Value": f"'{provider}'"}}},
        }}]
    elif code_type == 'python':
        objects['script'] = [{"properties": {
            "source": {"expr": {"Literal": {"Value": f"'{code}'"}}},
        }}]
    elif code_type == 'r':
        objects['script'] = [{"properties": {
            "source": {"expr": {"Literal": {"Value": f"'{code}'"}}},
        }}]
    else:
        return {'success': False, 'error': f'Unknown code_type: {code_type}. Use deneb, python, or r'}

    dry_run = args.get('dry_run', False)
    if not dry_run:
        _save_json_file(file_path, visual_data)

    return {
        'success': True, 'operation': 'inject_code', 'dry_run': dry_run,
        'visual_name': visual_name, 'code_type': code_type, 'code_length': len(code)
    }


def _op_update_formatting(args: Dict[str, Any], definition_path: Path) -> Dict[str, Any]:
    """High-level formatting update for common visual properties."""
    visual_name = args.get('visual_name')
    page_name = args.get('page_name')
    display_title = args.get('display_title')
    visual_type = args.get('visual_type')
    formatting_target = args.get('formatting_target')
    formatting_properties = args.get('formatting_properties', {})
    dry_run = args.get('dry_run', False)

    if not formatting_target or not formatting_properties:
        return {'success': False, 'error': 'update_formatting requires: formatting_target and formatting_properties'}

    visuals = _find_visuals(
        definition_path, display_title=display_title, visual_type=visual_type,
        visual_name=visual_name, page_name=page_name, include_hidden=True,
    )
    if not visuals:
        return {'success': False, 'error': 'No visuals found matching criteria'}

    # Map formatting_target to the correct objects section
    # visualContainerObjects targets: title, subtitle, divider, background, border, shadow, padding, spacing, header, tooltip
    # visual.objects targets: legend, categoryAxis, valueAxis, labels
    vc_targets = {'title', 'subtitle', 'divider', 'background', 'border', 'shadow', 'padding', 'spacing', 'header', 'tooltip'}
    obj_targets = {'legend', 'categoryAxis', 'valueAxis', 'labels'}

    is_vc = formatting_target in vc_targets
    is_obj = formatting_target in obj_targets

    if not is_vc and not is_obj:
        return {'success': False, 'error': f'Unknown formatting_target: {formatting_target}. Valid: {", ".join(sorted(vc_targets | obj_targets))}'}

    if is_obj:
        # For visual.objects targets, use the existing update_visual_config mechanism
        config_updates = []
        for prop_name, prop_value in formatting_properties.items():
            config_updates.append({
                'config_type': formatting_target,
                'property_name': prop_name,
                'property_value': prop_value,
                'value_type': 'auto',
            })
        updated_args = dict(args)
        updated_args['config_updates'] = config_updates
        return _op_update_visual_config(updated_args, definition_path)

    # For visualContainerObjects targets, apply updates directly
    changes = []
    errors = []

    for visual in visuals:
        file_path = Path(visual['file_path'])
        visual_data = _load_json_file(file_path)
        if not visual_data:
            errors.append({'file_path': str(file_path), 'error': 'Failed to load visual.json'})
            continue

        vc_objects = visual_data.setdefault('visualContainerObjects', {})
        target_array = vc_objects.setdefault(formatting_target, [])

        # Find or create the default (no-selector) entry
        target_entry = None
        for entry in target_array:
            if not entry.get('selector'):
                target_entry = entry
                break
        if target_entry is None:
            target_entry = {"properties": {}}
            target_array.append(target_entry)

        props = target_entry.setdefault('properties', {})
        visual_changes = []
        for prop_name, prop_value in formatting_properties.items():
            old_val = props.get(prop_name)
            # Format value using Power BI Literal expression pattern
            if isinstance(prop_value, bool):
                formatted = {"expr": {"Literal": {"Value": "true" if prop_value else "false"}}}
            elif isinstance(prop_value, (int, float)):
                formatted = {"expr": {"Literal": {"Value": f"{prop_value}D"}}}
            elif isinstance(prop_value, str):
                if prop_value.lower() in ('true', 'false'):
                    formatted = {"expr": {"Literal": {"Value": prop_value.lower()}}}
                elif prop_value.endswith('D') or prop_value.endswith('L') or (prop_value.startswith("'") and prop_value.endswith("'")):
                    formatted = {"expr": {"Literal": {"Value": prop_value}}}
                else:
                    formatted = {"expr": {"Literal": {"Value": f"'{prop_value}'"}}}
            else:
                formatted = {"expr": {"Literal": {"Value": str(prop_value)}}}
            props[prop_name] = formatted
            visual_changes.append(f"{formatting_target}.{prop_name} = {prop_value}")

        if visual_changes:
            change_record = {
                'display_title': visual['display_title'],
                'page_name': visual.get('page_name', ''),
                'visual_name': visual['visual_name'],
                'visual_type': visual['visual_type'],
                'config_changes': visual_changes,
                'status': 'would_change' if dry_run else 'changed',
            }
            if not dry_run:
                if _save_json_file(file_path, visual_data):
                    change_record['status'] = 'changed'
                else:
                    change_record['status'] = 'error'
                    errors.append({'file_path': str(file_path), 'error': 'Failed to save changes'})
            changes.append(change_record)

    result = {
        'success': len(errors) == 0,
        'operation': 'update_formatting',
        'dry_run': dry_run,
        'message': f'{"Would update" if dry_run else "Updated"} formatting in {len(changes)} visual(s)',
        'changes': changes,
        'changes_count': len(changes),
    }
    if errors:
        result['errors'] = errors
        result['errors_count'] = len(errors)
        result['message'] += f' with {len(errors)} error(s)'
    return result


def _op_manage_visual_calcs(args: Dict[str, Any], definition_path: Path) -> Dict[str, Any]:
    """Manage visual calculations."""
    from core.pbip.visual_calculations_engine import (
        list_calculations, add_calculation, update_calculation, delete_calculation,
    )
    sub_op = args.get('sub_operation', 'list')
    if sub_op == 'list':
        return list_calculations(definition_path, args.get('page_name'), args.get('visual_name'))
    elif sub_op == 'add':
        return add_calculation(definition_path, args.get('page_name', ''), args.get('visual_name', ''),
                               args.get('calc_name', ''), args.get('expression', ''))
    elif sub_op == 'update':
        return update_calculation(definition_path, args.get('page_name', ''), args.get('visual_name', ''),
                                  args.get('calc_name', ''), args.get('expression'))
    elif sub_op == 'delete':
        return delete_calculation(definition_path, args.get('page_name', ''), args.get('visual_name', ''),
                                  args.get('calc_name', ''))
    return {'success': False, 'error': f'Unknown sub_operation: {sub_op}'}


def _resolve_page_dir(definition_path: Path, page_id: str) -> Optional[Path]:
    """Resolve a page ID or display name to its directory."""
    pages_dir = definition_path / "pages"
    if not pages_dir.exists():
        return None
    direct = pages_dir / page_id
    if direct.exists() and direct.is_dir():
        return direct
    page_id_lower = page_id.lower()
    for page_folder in pages_dir.iterdir():
        if not page_folder.is_dir():
            continue
        page_json = _load_json_file(page_folder / "page.json")
        if page_json:
            display_name = page_json.get("displayName", "")
            if display_name.lower() == page_id_lower or page_id_lower in display_name.lower():
                return page_folder
    return None


def handle_visual_operations(args: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatch for all visual operations (expanded v12)."""
    operation = args.get('operation', 'list')
    pbip_path = args.get('pbip_path')

    if not pbip_path:
        return {
            'success': False,
            'error': 'pbip_path parameter is required - path to PBIP project, .Report folder, or definition folder',
        }

    resolved = resolve_definition_path(pbip_path)
    if 'error' in resolved:
        return {'success': False, 'error': resolved['error']}
    definition_path = resolved['path']

    ops = {
        'list': _op_list,
        'create': _op_create_visual,
        'create_group': _op_create_visual_group,
        'delete': _op_delete_visual,
        'update_position': _op_update_position,
        'update_visual_config': _op_update_visual_config,
        'update_formatting': _op_update_formatting,
        'align': _op_align,
        'add_field': _op_add_field,
        'remove_field': _op_remove_field,
        'set_sort': _op_set_sort,
        'set_action': _op_set_action,
        'inject_code': _op_inject_code,
        'manage_visual_calcs': _op_manage_visual_calcs,
        'configure_slicer': _op_configure_slicer,
        'list_templates': _op_list_templates,
        'get_template': _op_get_template,
        'replace_measure': _op_replace_measure,
        'sync_visual': _op_sync_visual,
        'sync_column_widths': _op_sync_column_widths,
        'sync_formatting': _op_sync_formatting,
    }
    op_func = ops.get(operation)
    if not op_func:
        valid = ", ".join(sorted(ops))
        return {'success': False, 'error': f'Unknown operation: {operation}. Valid: {valid}'}
    return op_func(args, definition_path)


def _op_sync_formatting(args: Dict[str, Any], definition_path: Path) -> Dict[str, Any]:
    """Copy all formatting (visual.objects + visualContainerObjects) from source to target visual(s).

    Preserves target visual identity (type, data bindings, position) but replaces
    all formatting properties from the source visual.
    """
    source_visual_name = args.get('source_visual_name')
    source_page = args.get('source_page')
    target_visual_name = args.get('target_visual_name')
    target_page = args.get('target_page')
    dry_run = args.get('dry_run', False)

    if not source_visual_name or not source_page:
        return {'success': False, 'error': 'sync_formatting requires: source_visual_name, source_page'}
    if not target_visual_name and not target_page:
        return {'success': False, 'error': 'sync_formatting requires: target_visual_name and/or target_page'}

    # Find source visual
    source_visuals = _find_visuals(
        definition_path, visual_name=source_visual_name, page_name=source_page, include_hidden=True,
    )
    if not source_visuals:
        return {'success': False, 'error': f'Source visual not found: {source_visual_name} on {source_page}'}

    source_visual = source_visuals[0]
    source_data = _load_json_file(Path(source_visual['file_path']))
    if not source_data:
        return {'success': False, 'error': 'Failed to load source visual.json'}

    # Extract formatting sections from source
    source_objects = source_data.get('visual', {}).get('objects', {})
    source_vc_objects = source_data.get('visualContainerObjects', {})

    # Find target visuals
    target_visuals = _find_visuals(
        definition_path, visual_name=target_visual_name, page_name=target_page, include_hidden=True,
    )
    if not target_visuals:
        return {'success': False, 'error': f'No target visuals found matching criteria'}

    changes = []
    errors = []

    for target in target_visuals:
        # Skip if target is the source
        if target['file_path'] == source_visual['file_path']:
            continue

        file_path = Path(target['file_path'])
        target_data = _load_json_file(file_path)
        if not target_data:
            errors.append({'file_path': str(file_path), 'error': 'Failed to load visual.json'})
            continue

        import copy
        # Copy visual.objects from source (deep copy to avoid shared references)
        if source_objects:
            target_data.setdefault('visual', {})['objects'] = copy.deepcopy(source_objects)

        # Copy visualContainerObjects from source
        if source_vc_objects:
            target_data['visualContainerObjects'] = copy.deepcopy(source_vc_objects)

        change_record = {
            'display_title': target.get('display_title', ''),
            'page_name': target.get('page_name', ''),
            'visual_name': target['visual_name'],
            'visual_type': target['visual_type'],
            'synced_objects': bool(source_objects),
            'synced_vc_objects': bool(source_vc_objects),
            'status': 'would_change' if dry_run else 'changed',
        }

        if not dry_run:
            if _save_json_file(file_path, target_data):
                change_record['status'] = 'changed'
            else:
                change_record['status'] = 'error'
                errors.append({'file_path': str(file_path), 'error': 'Failed to save changes'})

        changes.append(change_record)

    result = {
        'success': len(errors) == 0,
        'operation': 'sync_formatting',
        'dry_run': dry_run,
        'source': {
            'visual_name': source_visual['visual_name'],
            'page_name': source_visual.get('page_name', ''),
        },
        'message': f'{"Would sync" if dry_run else "Synced"} formatting to {len(changes)} visual(s)',
        'changes': changes,
        'changes_count': len(changes),
    }
    if errors:
        result['errors'] = errors
        result['errors_count'] = len(errors)
    return result


def register_visual_operations_handler(registry):
    """Register visual operations handler (expanded v12, includes sync ops)."""
    from server.tool_schemas import TOOL_SCHEMAS

    tool = ToolDefinition(
        name="07_Visual_Operations",
        description=(
            "Visual operations: list, create, delete, position, config, formatting, "
            "align, field binding, sort, actions, code injection, slicer config, "
            "visual calcs, templates, replace_measure, sync_visual, "
            "sync_column_widths, sync_formatting."
        ),
        handler=handle_visual_operations,
        input_schema=TOOL_SCHEMAS.get('visual_operations', {}),
        category="pbip",
        sort_order=73,
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    registry.register(tool)
    logger.info("Registered visual_operations handler (v12 + sync ops)")
