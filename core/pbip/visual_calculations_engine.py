"""
Visual Calculations Engine for PBIP Reports

Manages visual-level DAX calculations embedded in visual.json files.
Visual calculations are DAX expressions scoped to a single visual's
query context, stored in the visualCalculations section of visual.json.

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


def _find_visual_folder(
    page_folder: Path, visual_name: str
) -> Optional[Path]:
    """Find visual folder by visual name/ID or title (case-insensitive).

    Args:
        page_folder: Path to the page folder
        visual_name: Visual ID, name, or title text

    Returns:
        Path to the visual folder, or None if not found
    """
    visuals_dir = page_folder / "visuals"
    if not visuals_dir.exists():
        return None

    # Try direct ID match first
    direct = visuals_dir / visual_name
    if direct.is_dir():
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
            return visual_folder

        # Check visualGroup displayName
        vg = visual_data.get("visualGroup", {})
        if vg.get("displayName", "").lower() == name_lower:
            return visual_folder

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
                return visual_folder

    return None


def _get_visual_type(visual_data: Dict[str, Any]) -> str:
    """Extract visual type from visual.json data."""
    return visual_data.get("visual", {}).get("visualType", "unknown")


def _get_visual_title(visual_data: Dict[str, Any]) -> str:
    """Extract visual title from visual.json data."""
    vco = visual_data.get("visual", {}).get("visualContainerObjects", {})
    title_list = vco.get("title", [])
    for t in title_list:
        props = t.get("properties", {})
        text = props.get("text", {})
        expr = text.get("expr", {})
        lit = expr.get("Literal", {})
        val = lit.get("Value", "")
        if val:
            return val.strip("'")
    return ""


def list_calculations(
    definition_path: Path,
    page_name: str = None,
    visual_name: str = None,
) -> Dict[str, Any]:
    """List visual calculations across visuals.

    Args:
        definition_path: Path to the report's definition/ folder
        page_name: Optional page filter (display name or ID)
        visual_name: Optional visual filter (name or ID)

    Returns:
        Dict with success status and calculations list
    """
    pages_dir = definition_path / "pages"
    if not pages_dir.exists():
        return {"success": True, "calculations": [], "total_count": 0}

    # Determine which pages to scan
    if page_name:
        page_folder = _find_page_folder(definition_path, page_name)
        if not page_folder:
            return {"success": False, "error": f"Page not found: '{page_name}'"}
        page_folders = [page_folder]
    else:
        page_folders = [f for f in pages_dir.iterdir() if f.is_dir()]

    calculations: List[Dict[str, Any]] = []

    for pf in page_folders:
        p_display_name = get_page_display_name(pf)
        visuals_dir = pf / "visuals"
        if not visuals_dir.exists():
            continue

        # Determine which visuals to scan
        if visual_name:
            vf = _find_visual_folder(pf, visual_name)
            visual_folders = [vf] if vf else []
        else:
            visual_folders = [f for f in visuals_dir.iterdir() if f.is_dir()]

        for vf in visual_folders:
            visual_json_path = vf / "visual.json"
            visual_data = load_json_file(visual_json_path)
            if not visual_data:
                continue

            vis_calcs = (
                visual_data.get("visual", {}).get("visualCalculations", {})
            )
            calc_list = vis_calcs.get("calculations", [])

            for calc in calc_list:
                calculations.append({
                    "page": p_display_name,
                    "page_id": pf.name,
                    "visual_id": vf.name,
                    "visual_type": _get_visual_type(visual_data),
                    "visual_title": _get_visual_title(visual_data),
                    "name": calc.get("name", ""),
                    "expression": calc.get("expression", ""),
                    "result_type": calc.get("resultType", ""),
                })

    return {
        "success": True,
        "calculations": calculations,
        "total_count": len(calculations),
    }


def add_calculation(
    definition_path: Path,
    page_name: str,
    visual_name: str,
    name: str,
    expression: str,
    result_type: str = "double",
) -> Dict[str, Any]:
    """Add a visual calculation to a visual.

    Args:
        definition_path: Path to the report's definition/ folder
        page_name: Page display name or page ID
        visual_name: Visual name or ID
        name: Calculation name
        expression: DAX expression
        result_type: Result data type (default "double")

    Returns:
        Dict with success status and calculation details
    """
    if not name or not name.strip():
        return {"success": False, "error": "Calculation name is required"}
    if not expression or not expression.strip():
        return {"success": False, "error": "Calculation expression is required"}

    page_folder = _find_page_folder(definition_path, page_name)
    if not page_folder:
        return {"success": False, "error": f"Page not found: '{page_name}'"}

    visual_folder = _find_visual_folder(page_folder, visual_name)
    if not visual_folder:
        return {"success": False, "error": f"Visual not found: '{visual_name}'"}

    visual_json_path = visual_folder / "visual.json"
    visual_data = load_json_file(visual_json_path)
    if not visual_data:
        return {"success": False, "error": f"Could not read visual.json for '{visual_name}'"}

    # Navigate to or create the visualCalculations section
    visual_section = visual_data.setdefault("visual", {})
    vis_calcs = visual_section.setdefault("visualCalculations", {})
    calc_list = vis_calcs.setdefault("calculations", [])

    # Check for duplicate name
    for existing in calc_list:
        if existing.get("name") == name:
            return {
                "success": False,
                "error": (
                    f"Visual calculation '{name}' already exists on this visual. "
                    f"Use update_calculation to modify it."
                ),
            }

    # Add the calculation
    calc_entry: Dict[str, Any] = {
        "name": name,
        "expression": expression,
        "resultType": result_type,
    }
    calc_list.append(calc_entry)

    if not save_json_file(visual_json_path, visual_data):
        return {"success": False, "error": "Failed to write visual.json"}

    return {
        "success": True,
        "page": get_page_display_name(page_folder),
        "visual_id": visual_folder.name,
        "calculation": name,
        "expression": expression,
        "result_type": result_type,
    }


def update_calculation(
    definition_path: Path,
    page_name: str,
    visual_name: str,
    name: str,
    expression: str = None,
) -> Dict[str, Any]:
    """Update a visual calculation's expression.

    Args:
        definition_path: Path to the report's definition/ folder
        page_name: Page display name or page ID
        visual_name: Visual name or ID
        name: Calculation name to update
        expression: New DAX expression (None to keep current)

    Returns:
        Dict with success status and updated calculation details
    """
    if expression is None:
        return {"success": False, "error": "Expression must be provided for update"}

    page_folder = _find_page_folder(definition_path, page_name)
    if not page_folder:
        return {"success": False, "error": f"Page not found: '{page_name}'"}

    visual_folder = _find_visual_folder(page_folder, visual_name)
    if not visual_folder:
        return {"success": False, "error": f"Visual not found: '{visual_name}'"}

    visual_json_path = visual_folder / "visual.json"
    visual_data = load_json_file(visual_json_path)
    if not visual_data:
        return {"success": False, "error": f"Could not read visual.json for '{visual_name}'"}

    vis_calcs = visual_data.get("visual", {}).get("visualCalculations", {})
    calc_list = vis_calcs.get("calculations", [])

    # Find the calculation
    target_calc = None
    for calc in calc_list:
        if calc.get("name") == name:
            target_calc = calc
            break

    if target_calc is None:
        return {
            "success": False,
            "error": f"Visual calculation '{name}' not found on this visual",
        }

    old_expression = target_calc.get("expression", "")
    target_calc["expression"] = expression

    if not save_json_file(visual_json_path, visual_data):
        return {"success": False, "error": "Failed to write visual.json"}

    return {
        "success": True,
        "page": get_page_display_name(page_folder),
        "visual_id": visual_folder.name,
        "calculation": name,
        "old_expression": old_expression,
        "new_expression": expression,
    }


def delete_calculation(
    definition_path: Path,
    page_name: str,
    visual_name: str,
    name: str,
) -> Dict[str, Any]:
    """Delete a visual calculation.

    Args:
        definition_path: Path to the report's definition/ folder
        page_name: Page display name or page ID
        visual_name: Visual name or ID
        name: Calculation name to delete

    Returns:
        Dict with success status and deletion details
    """
    page_folder = _find_page_folder(definition_path, page_name)
    if not page_folder:
        return {"success": False, "error": f"Page not found: '{page_name}'"}

    visual_folder = _find_visual_folder(page_folder, visual_name)
    if not visual_folder:
        return {"success": False, "error": f"Visual not found: '{visual_name}'"}

    visual_json_path = visual_folder / "visual.json"
    visual_data = load_json_file(visual_json_path)
    if not visual_data:
        return {"success": False, "error": f"Could not read visual.json for '{visual_name}'"}

    vis_calcs = visual_data.get("visual", {}).get("visualCalculations", {})
    calc_list = vis_calcs.get("calculations", [])

    # Find and remove the calculation
    original_count = len(calc_list)
    calc_list = [c for c in calc_list if c.get("name") != name]

    if len(calc_list) == original_count:
        return {
            "success": False,
            "error": f"Visual calculation '{name}' not found on this visual",
        }

    # Update the calculations list
    if calc_list:
        vis_calcs["calculations"] = calc_list
    else:
        # Remove the entire visualCalculations section if empty
        visual_data.get("visual", {}).pop("visualCalculations", None)

    if not save_json_file(visual_json_path, visual_data):
        return {"success": False, "error": "Failed to write visual.json"}

    return {
        "success": True,
        "page": get_page_display_name(page_folder),
        "visual_id": visual_folder.name,
        "deleted_calculation": name,
        "remaining_calculations": len(calc_list),
    }
