"""
Extension Measures Engine for PBIP Reports

Manages report-level extension measures stored in definition/reportExtensions.json.
Extension measures are DAX measures defined at the report level rather than in
the semantic model, useful for report-specific calculations.

No MCP awareness — pure domain logic operating on PBIP file structures.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.utilities.pbip_utils import load_json_file, save_json_file

logger = logging.getLogger(__name__)

# Schema version for reportExtensions.json
_EXTENSIONS_SCHEMA = (
    "https://developer.microsoft.com/json-schemas/fabric/item/report/"
    "definition/reportExtensions/1.1.0/schema.json"
)


def _get_extensions_path(definition_path: Path) -> Path:
    """Get the path to reportExtensions.json."""
    return definition_path / "reportExtensions.json"


def _load_extensions(definition_path: Path) -> Optional[Dict[str, Any]]:
    """Load reportExtensions.json, returning None if it doesn't exist or is invalid."""
    ext_path = _get_extensions_path(definition_path)
    if not ext_path.exists():
        return None
    return load_json_file(ext_path)


def _ensure_extensions(definition_path: Path) -> Dict[str, Any]:
    """Load or create the reportExtensions structure.

    Returns:
        The extensions dict (either loaded from disk or a new skeleton)
    """
    data = _load_extensions(definition_path)
    if data is not None:
        return data
    return {
        "$schema": _EXTENSIONS_SCHEMA,
        "entities": [],
    }


def _find_measure(
    entities: List[Dict[str, Any]], name: str
) -> Optional[Dict[str, Any]]:
    """Find a measure by name across all entities.

    Returns:
        Tuple-like dict with 'entity_index', 'measure_index', and 'measure' keys,
        or None if not found.
    """
    for ei, entity in enumerate(entities):
        for mi, measure in enumerate(entity.get("measures", [])):
            if measure.get("name") == name:
                return {
                    "entity_index": ei,
                    "measure_index": mi,
                    "measure": measure,
                    "table": entity.get("name", ""),
                }
    return None


def _find_or_create_entity(
    entities: List[Dict[str, Any]], table_ref: str
) -> Dict[str, Any]:
    """Find an entity by table name, or create one if it doesn't exist.

    Args:
        entities: The entities list from reportExtensions
        table_ref: Table/entity name to find or create

    Returns:
        The matching or newly created entity dict
    """
    for entity in entities:
        if entity.get("name") == table_ref:
            return entity

    new_entity: Dict[str, Any] = {
        "name": table_ref,
        "measures": [],
    }
    entities.append(new_entity)
    return new_entity


def list_measures(definition_path: Path) -> Dict[str, Any]:
    """List all extension measures from reportExtensions.json.

    Args:
        definition_path: Path to the report's definition/ folder

    Returns:
        Dict with success status and measures list grouped by table
    """
    data = _load_extensions(definition_path)
    if data is None:
        return {
            "success": True,
            "measures": [],
            "total_count": 0,
            "note": "No reportExtensions.json found — no extension measures defined",
        }

    entities = data.get("entities", [])
    measures_list: List[Dict[str, Any]] = []

    for entity in entities:
        table_name = entity.get("name", "")
        for measure in entity.get("measures", []):
            measures_list.append({
                "name": measure.get("name", ""),
                "table": table_name,
                "expression": measure.get("expression", ""),
                "data_type": measure.get("dataType", ""),
                "format_string": measure.get("formatString"),
                "description": measure.get("description"),
            })

    return {
        "success": True,
        "measures": measures_list,
        "total_count": len(measures_list),
        "entity_count": len(entities),
    }


def add_measure(
    definition_path: Path,
    name: str,
    expression: str,
    table_ref: str,
    data_type: str = "double",
    format_string: str = None,
    description: str = None,
) -> Dict[str, Any]:
    """Add a new extension measure.

    Args:
        definition_path: Path to the report's definition/ folder
        name: Measure name
        expression: DAX expression
        table_ref: Table/entity to associate the measure with
        data_type: Data type (default "double")
        format_string: Optional format string (e.g., "0.00%")
        description: Optional description

    Returns:
        Dict with success status and measure details
    """
    if not name or not name.strip():
        return {"success": False, "error": "Measure name is required"}
    if not expression or not expression.strip():
        return {"success": False, "error": "Measure expression is required"}
    if not table_ref or not table_ref.strip():
        return {"success": False, "error": "Table reference (table_ref) is required"}

    data = _ensure_extensions(definition_path)
    entities = data.setdefault("entities", [])

    # Check for duplicate name
    existing = _find_measure(entities, name)
    if existing is not None:
        return {
            "success": False,
            "error": (
                f"Measure '{name}' already exists in entity '{existing['table']}'. "
                f"Use update_measure to modify it."
            ),
        }

    # Find or create the entity for this table
    entity = _find_or_create_entity(entities, table_ref)
    measures = entity.setdefault("measures", [])

    # Build the measure entry
    measure_entry: Dict[str, Any] = {
        "name": name,
        "expression": expression,
        "dataType": data_type,
    }
    if format_string is not None:
        measure_entry["formatString"] = format_string
    if description is not None:
        measure_entry["description"] = description

    measures.append(measure_entry)

    ext_path = _get_extensions_path(definition_path)
    if not save_json_file(ext_path, data):
        return {"success": False, "error": "Failed to write reportExtensions.json"}

    return {
        "success": True,
        "measure": name,
        "table": table_ref,
        "expression": expression,
        "data_type": data_type,
    }


def update_measure(
    definition_path: Path,
    name: str,
    expression: str = None,
    format_string: str = None,
    description: str = None,
) -> Dict[str, Any]:
    """Update an existing extension measure.

    Args:
        definition_path: Path to the report's definition/ folder
        name: Measure name to update
        expression: New DAX expression (None to keep current)
        format_string: New format string (None to keep current)
        description: New description (None to keep current)

    Returns:
        Dict with success status and updated measure details
    """
    if expression is None and format_string is None and description is None:
        return {"success": False, "error": "At least one field to update must be provided"}

    data = _load_extensions(definition_path)
    if data is None:
        return {"success": False, "error": "No reportExtensions.json found"}

    entities = data.get("entities", [])
    found = _find_measure(entities, name)
    if found is None:
        return {"success": False, "error": f"Measure '{name}' not found in reportExtensions"}

    measure = found["measure"]
    updated_fields: List[str] = []

    if expression is not None:
        measure["expression"] = expression
        updated_fields.append("expression")
    if format_string is not None:
        measure["formatString"] = format_string
        updated_fields.append("formatString")
    if description is not None:
        measure["description"] = description
        updated_fields.append("description")

    ext_path = _get_extensions_path(definition_path)
    if not save_json_file(ext_path, data):
        return {"success": False, "error": "Failed to write reportExtensions.json"}

    return {
        "success": True,
        "measure": name,
        "table": found["table"],
        "updated_fields": updated_fields,
    }


def delete_measure(definition_path: Path, name: str) -> Dict[str, Any]:
    """Delete an extension measure.

    Args:
        definition_path: Path to the report's definition/ folder
        name: Measure name to delete

    Returns:
        Dict with success status and deletion details
    """
    data = _load_extensions(definition_path)
    if data is None:
        return {"success": False, "error": "No reportExtensions.json found"}

    entities = data.get("entities", [])
    found = _find_measure(entities, name)
    if found is None:
        return {"success": False, "error": f"Measure '{name}' not found in reportExtensions"}

    entity_idx = found["entity_index"]
    measure_idx = found["measure_index"]
    table_name = found["table"]

    # Remove the measure
    entities[entity_idx]["measures"].pop(measure_idx)

    # Clean up empty entities
    if not entities[entity_idx].get("measures"):
        entities.pop(entity_idx)

    ext_path = _get_extensions_path(definition_path)
    if not save_json_file(ext_path, data):
        return {"success": False, "error": "Failed to write reportExtensions.json"}

    return {
        "success": True,
        "deleted_measure": name,
        "table": table_name,
        "remaining_measures": sum(len(e.get("measures", [])) for e in entities),
    }
