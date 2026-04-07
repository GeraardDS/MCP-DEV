"""
Field Binding Engine for PBIP Reports

Add, remove, and clear fields from visual data role buckets.
Uses data_binding_builder.py for constructing projection entries
and reads/writes visual.json files directly.

No MCP awareness — pure domain logic operating on PBIP file structures.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.utilities.pbip_utils import (
    load_json_file,
    save_json_file,
    get_page_display_name,
)

logger = logging.getLogger(__name__)


def _find_page_folder(definition_path: Path, page_name: str) -> Optional[Path]:
    """Find page folder by display name (case-insensitive partial match) or page ID.

    Args:
        definition_path: Path to the report's definition/ folder
        page_name: Page display name or page ID

    Returns:
        Path to the page folder, or None if not found
    """
    pages_dir = definition_path / "pages"
    if not pages_dir.exists():
        return None

    # Try direct ID match first
    direct = pages_dir / page_name
    if direct.is_dir():
        return direct

    # Fall back to display name matching (case-insensitive)
    name_lower = page_name.lower()
    for page_folder in pages_dir.iterdir():
        if not page_folder.is_dir():
            continue
        display_name = get_page_display_name(page_folder)
        if display_name.lower() == name_lower or name_lower in display_name.lower():
            return page_folder

    return None


def _find_visual_json(
    definition_path: Path, page_name: str, visual_name: str
) -> Optional[Path]:
    """Find visual.json by page name + visual name/ID/title (case-insensitive).

    Args:
        definition_path: Path to the report's definition/ folder
        page_name: Page display name or page ID
        visual_name: Visual ID, name, or title text

    Returns:
        Path to the visual.json file, or None if not found
    """
    page_folder = _find_page_folder(definition_path, page_name)
    if not page_folder:
        return None

    visuals_dir = page_folder / "visuals"
    if not visuals_dir.exists():
        return None

    # Try direct ID match first
    direct = visuals_dir / visual_name / "visual.json"
    if direct.exists():
        return direct

    # Fall back to name/title matching
    name_lower = visual_name.lower()
    for visual_folder in visuals_dir.iterdir():
        if not visual_folder.is_dir():
            continue
        visual_json_path = visual_folder / "visual.json"
        visual_data = load_json_file(visual_json_path)
        if not visual_data:
            continue

        # Check visual name field
        if visual_data.get("name", "").lower() == name_lower:
            return visual_json_path

        # Check visualGroup displayName
        vg = visual_data.get("visualGroup", {})
        if vg.get("displayName", "").lower() == name_lower:
            return visual_json_path

        # Check title in visualContainerObjects
        vco = visual_data.get("visual", {}).get("visualContainerObjects", {})
        title_list = vco.get("title", [])
        for t in title_list:
            props = t.get("properties", {})
            text = props.get("text", {})
            expr = text.get("expr", {})
            lit = expr.get("Literal", {})
            val = lit.get("Value", "")
            if val and name_lower in val.lower().strip("'"):
                return visual_json_path

    return None


def _get_query_state(visual_data: Dict[str, Any]) -> Dict[str, Any]:
    """Get or create the queryState dict from visual data.

    Args:
        visual_data: The visual.json data dict

    Returns:
        The queryState dict (created in place if not present)
    """
    visual_section = visual_data.setdefault("visual", {})
    query = visual_section.setdefault("query", {})
    return query.setdefault("queryState", {})


def _matches_field(
    projection: Dict[str, Any], table: str, field: str
) -> bool:
    """Check if a projection matches a given table + field combination.

    Handles both Column and Measure field types.

    Args:
        projection: A projection entry from queryState
        table: Table/entity name to match
        field: Field/property name to match

    Returns:
        True if the projection references this table.field
    """
    field_ref = projection.get("field", {})

    for field_type in ("Column", "Measure", "HierarchyLevel"):
        type_ref = field_ref.get(field_type)
        if not type_ref:
            continue

        if field_type == "HierarchyLevel":
            # HierarchyLevel has nested Expression.Hierarchy.Expression.SourceRef
            hierarchy_ref = type_ref.get("Expression", {}).get("Hierarchy", {})
            entity = (
                hierarchy_ref.get("Expression", {}).get("SourceRef", {}).get("Entity", "")
            )
            level = type_ref.get("Level", "")
            if entity == table and level == field:
                return True
        else:
            entity = (
                type_ref.get("Expression", {}).get("SourceRef", {}).get("Entity", "")
            )
            prop = type_ref.get("Property", "")
            if entity == table and prop == field:
                return True

    # Also check queryRef as fallback
    query_ref = projection.get("queryRef", "")
    if query_ref == f"{table}.{field}":
        return True

    return False


def add_field(
    definition_path: Path,
    page_name: str,
    visual_name: str,
    table: str,
    field: str,
    bucket: str,
    field_type: str = "Column",
    display_name: str = None,
) -> Dict[str, Any]:
    """Add a field to a visual's data role bucket.

    Uses data_binding_builder for building the projection entry.

    Args:
        definition_path: Path to the report's definition/ folder
        page_name: Page display name or page ID
        visual_name: Visual name or ID
        table: Source table/entity name
        field: Field/property name
        bucket: Data role bucket name (e.g., "Category", "Y", "Values", "Rows")
        field_type: "Column", "Measure", or "Hierarchy" (default "Column")
        display_name: Optional display name override

    Returns:
        Dict with success status and field binding details
    """
    # Lazy import to avoid circular dependency at module load time
    from core.pbip.authoring.data_binding_builder import (
        build_measure_binding,
        build_column_binding,
    )

    if not table or not field:
        return {"success": False, "error": "Both table and field are required"}
    if not bucket:
        return {"success": False, "error": "Bucket name is required"}

    visual_json_path = _find_visual_json(definition_path, page_name, visual_name)
    if not visual_json_path:
        return {
            "success": False,
            "error": f"Visual not found: page='{page_name}', visual='{visual_name}'",
        }

    visual_data = load_json_file(visual_json_path)
    if not visual_data:
        return {"success": False, "error": "Could not read visual.json"}

    query_state = _get_query_state(visual_data)

    # Build the projection based on field type
    field_type_lower = field_type.lower()
    if field_type_lower == "measure":
        projection = build_measure_binding(table, field, display_name)
    elif field_type_lower in ("column", "hierarchy"):
        projection = build_column_binding(table, field, display_name)
    else:
        return {
            "success": False,
            "error": f"Invalid field_type: '{field_type}'. Use 'Column', 'Measure', or 'Hierarchy'",
        }

    # Add to the bucket's projections
    bucket_data = query_state.setdefault(bucket, {})
    projections = bucket_data.setdefault("projections", [])

    # Check for duplicate
    for existing in projections:
        if _matches_field(existing, table, field):
            return {
                "success": False,
                "error": f"Field '{table}.{field}' already exists in bucket '{bucket}'",
            }

    projections.append(projection)

    if not save_json_file(visual_json_path, visual_data):
        return {"success": False, "error": "Failed to write visual.json"}

    return {
        "success": True,
        "visual_id": visual_json_path.parent.name,
        "table": table,
        "field": field,
        "bucket": bucket,
        "field_type": field_type,
        "total_fields_in_bucket": len(projections),
    }


def remove_field(
    definition_path: Path,
    page_name: str,
    visual_name: str,
    table: str,
    field: str,
    bucket: str = None,
) -> Dict[str, Any]:
    """Remove a field from a visual's data roles.

    If bucket is not specified, removes the field from all buckets.

    Args:
        definition_path: Path to the report's definition/ folder
        page_name: Page display name or page ID
        visual_name: Visual name or ID
        table: Source table/entity name
        field: Field/property name
        bucket: Optional bucket to remove from (None = all buckets)

    Returns:
        Dict with success status and removal details
    """
    if not table or not field:
        return {"success": False, "error": "Both table and field are required"}

    visual_json_path = _find_visual_json(definition_path, page_name, visual_name)
    if not visual_json_path:
        return {
            "success": False,
            "error": f"Visual not found: page='{page_name}', visual='{visual_name}'",
        }

    visual_data = load_json_file(visual_json_path)
    if not visual_data:
        return {"success": False, "error": "Could not read visual.json"}

    query_state = visual_data.get("visual", {}).get("query", {}).get("queryState", {})
    if not query_state:
        return {"success": False, "error": "Visual has no query state (no fields bound)"}

    removed_from: List[str] = []

    buckets_to_check = [bucket] if bucket else list(query_state.keys())

    for b in buckets_to_check:
        if b not in query_state:
            continue
        projections = query_state[b].get("projections", [])
        original_count = len(projections)
        projections = [p for p in projections if not _matches_field(p, table, field)]
        if len(projections) < original_count:
            query_state[b]["projections"] = projections
            removed_from.append(b)

    if not removed_from:
        scope = f"bucket '{bucket}'" if bucket else "any bucket"
        return {
            "success": False,
            "error": f"Field '{table}.{field}' not found in {scope}",
        }

    if not save_json_file(visual_json_path, visual_data):
        return {"success": False, "error": "Failed to write visual.json"}

    return {
        "success": True,
        "visual_id": visual_json_path.parent.name,
        "table": table,
        "field": field,
        "removed_from_buckets": removed_from,
    }


def clear_fields(
    definition_path: Path,
    page_name: str,
    visual_name: str,
    bucket: str = None,
) -> Dict[str, Any]:
    """Clear all fields from a bucket (or all buckets if not specified).

    Args:
        definition_path: Path to the report's definition/ folder
        page_name: Page display name or page ID
        visual_name: Visual name or ID
        bucket: Optional bucket to clear (None = clear all buckets)

    Returns:
        Dict with success status and clearing details
    """
    visual_json_path = _find_visual_json(definition_path, page_name, visual_name)
    if not visual_json_path:
        return {
            "success": False,
            "error": f"Visual not found: page='{page_name}', visual='{visual_name}'",
        }

    visual_data = load_json_file(visual_json_path)
    if not visual_data:
        return {"success": False, "error": "Could not read visual.json"}

    query_state = visual_data.get("visual", {}).get("query", {}).get("queryState", {})
    if not query_state:
        return {
            "success": True,
            "visual_id": visual_json_path.parent.name,
            "cleared_buckets": [],
            "fields_removed": 0,
            "note": "Visual has no query state — nothing to clear",
        }

    cleared_buckets: List[str] = []
    total_removed = 0

    if bucket:
        if bucket not in query_state:
            return {
                "success": False,
                "error": (
                    f"Bucket '{bucket}' not found. "
                    f"Available buckets: {', '.join(query_state.keys())}"
                ),
            }
        count = len(query_state[bucket].get("projections", []))
        query_state[bucket]["projections"] = []
        cleared_buckets.append(bucket)
        total_removed = count
    else:
        for b, b_data in query_state.items():
            count = len(b_data.get("projections", []))
            if count > 0:
                b_data["projections"] = []
                cleared_buckets.append(b)
                total_removed += count

    if not save_json_file(visual_json_path, visual_data):
        return {"success": False, "error": "Failed to write visual.json"}

    return {
        "success": True,
        "visual_id": visual_json_path.parent.name,
        "cleared_buckets": cleared_buckets,
        "fields_removed": total_removed,
    }
